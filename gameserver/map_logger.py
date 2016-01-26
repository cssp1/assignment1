#!/usr/bin/env python

import SpinChatClient
import SpinChatProtocol
import SpinNoSQL
import SpinJSON
import traceback
import time
from twisted.internet import reactor

nosql_client = None

def path_diff(a, b):
    if len(a) != len(b):
        return 'length mismatch'
    for ea, eb, in zip(a, b):
        if ea['xy'] != eb['xy']:
            return 'xy mismatch %r %r' % (ea, eb)
        if abs(ea.get('eta',0) - eb.get('eta',0)) > 0.75:
            return 'eta mismatch %r %r' % (ea, eb)
    return None

IGNORE_KEYS = set(['LOCK_GENERATION', 'LOCK_TIME', 'LOCK_OWNER', 'last_mtime',
                   'LOCK_STATE', # <- should be consistent for "long" client-visible locks,
                   # but is not updated for quick server-only critical sections
                   ])

def dict_diff(a, b):
    ret = []

    for k, v in a.iteritems():
        if k in IGNORE_KEYS: continue
        elif k == 'base_map_path':
            if v is None and (k not in b or b[k] is None): continue
            delta = path_diff(b[k], v)
            if delta:
                ret.append(delta)
        elif b.get(k) != v:
            ret.append('%s != %r %r' % (k, v, b.get(k,'MISSING')))
    for k, v in b.iteritems():
        if k in IGNORE_KEYS: continue
        elif k not in a:
            ret.append('%s != %r %r' % (k,'MISSING',v))
    return ', '.join(ret)

class MapLogger(object):
    def __init__(self, region_id, record = False, debug = False, verbose = False):
        self.region_id = region_id
        self.state = None # map state
        self.snapshot_time = -1
        self.in_sync = False
        self.record = record
        self.debug = debug
        self.verbose = verbose

    # name of the table to write logging records to, if recording is enabled
    def log_table_name(self):
        if self.record:
            return nosql_client.region_table_name(self.region_id, 'log')
        return None

    def do_get_snapshot(self):
        state = dict((x['base_id'], x) for x in nosql_client.get_map_features(self.region_id))
        last_t = max(x.get('last_mtime',-1) for x in state.itervalues())
        return state, last_t

    def get_snapshot(self):
        self.state, self.snapshot_time = self.do_get_snapshot()
        self.in_sync = False
        if self.verbose: print 'got snapshot of', len(self.state), 'features', len(SpinJSON.dumps(self.state)), 'bytes'
        tbl = self.log_table_name()
        if tbl:
            nosql_client.log_record(tbl, self.snapshot_time, {'feature_snapshot':self.state}, log_ident = False)

    def check(self):
        if not self.debug: return
        test, test_t = self.do_get_snapshot()
        my_bases = set(self.state.iterkeys())
        test_bases = set(test.iterkeys())
        mine_not_test = my_bases - test_bases
        test_not_mine = test_bases - my_bases
        if mine_not_test:
            print 'I have bases not in snapshot', mine_not_test
        if test_not_mine:
            print 'Snapshot has bases I do not have', test_not_mine
        for tk, tv, in test.iteritems():
            if tk in self.state:
                if tv != self.state[tk] and dict_diff(self.state[tk], tv):
                    print 'Mismatch on', tk, dict_diff(self.state[tk], tv)
                    print 'MINE', self.state[tk]
                    print 'THEIRS', tv
    # apply all incremental updates between snapshot and map_time
    def catchup(self, map_time):
        if self.verbose: print 'catching up since', self.snapshot_time
        for update in nosql_client.get_map_features(self.region_id, updated_since = self.snapshot_time):
            if update.get('last_mtime') > map_time: continue # not received yet
            self.apply_update(update['base_id'], update, map_time)
        self.in_sync = True
        if self.verbose: print 'catchup done'

    def apply_update(self, base_id, base_data, map_time):
        if map_time is None: # legacy server didn't supply the time
            map_time = int(time.time())

        incremental = False
        if 'preserve_locks' in base_data:
            incremental = True
            del base_data['preserve_locks']

        if base_data.get('DELETED'):
            ui_data = 'DELETED'
            if base_id in self.state:
                del self.state[base_id]
        else:
            ui_data = ('incr' if incremental else 'full') + ' ' + repr(base_data)
            if base_id in self.state and incremental:
                if base_id in self.state:
                    for k, v in base_data.iteritems():
                        if v is None:
                            del self.state[base_id][k]
                        elif k == 'LOCK_STATE' and v == 0:
                            del self.state[base_id][k]
                        else:
                            self.state[base_id][k] = v
            elif not incremental:
                self.state[base_id] = base_data # full replacement

        tbl = self.log_table_name()
        if tbl:
            nosql_client.log_record(tbl, map_time, {'feature_update':base_data}, log_ident = False)

        print base_id, ui_data

    def recv(self, msg):
        try:
            return self.do_recv(msg)
        except Exception as e:
            sys.stderr.write(traceback.format_exc(e))

    def do_recv(self, msg):
        if msg['channel'] != 'CONTROL' or msg['sender']['method'] != 'broadcast_map_update' or \
           msg['sender']['args'].get('region_id') != self.region_id:
            return
        args = msg['sender']['args']
        base_id = args['base_id']
        base_data = args['data']
        map_time = args.get('map_time',None)

        if not self.in_sync:
            self.catchup(map_time)
        if self.verbose: print '---'
        self.apply_update(base_id, base_data, map_time)

        self.check()

        if 0: # test code
            time.sleep(1)
            msg['sender']['args']['server'] = msg['sender']['server'] = 'asdf'
            msg['sender']['args']['map_time'] = 6666666
            msg['sender']['args']['originator'] = -1
            print 'OUT', msg
            chat_client.chat_send({'channel':msg['channel'], 'sender':msg['sender'], 'text':msg['text']})

if __name__ == '__main__':
    import sys, getopt, SpinConfig
    verbose = True
    debug = False
    record = False
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'qdr', ['record'])
    if len(args) < 1:
        print 'usage: %s region_id' % sys.argv[0]
        sys.exit(1)

    for key, val in opts:
        if key == '-q': verbose = False
        elif key == '-d': debug = True
        elif key == '-r' or key == '--record': record = True

    region_id = args[0]

    chat_client = SpinChatClient.Client(SpinConfig.config['chatserver']['chat_host'],
                                        SpinConfig.config['chatserver']['chat_port'],
                                        SpinConfig.config['chatserver'].get('secret_full', SpinChatProtocol.default_secret_full),
                                        lambda x: sys.stdout.write(x+'\n'),
                                        subscribe = True,
                                        verbose = False)

    reactor.addSystemEventTrigger('before', 'shutdown', chat_client.disconnect)

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                         log_exception_func = lambda x: sys.stderr.write(x+'\n'))

    logger = MapLogger(region_id, record = record, debug = debug, verbose = verbose)
    chat_client.listener = logger.recv
    logger.get_snapshot()

    reactor.run()
