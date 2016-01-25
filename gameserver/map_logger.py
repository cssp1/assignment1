#!/usr/bin/env python

import SpinChatClient
import SpinChatProtocol
import SpinNoSQL
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
    def __init__(self, region_id, debug = False, verbose = False):
        self.region_id = region_id
        self.state = None # map state
        self.in_sync = False
        self.debug = debug
        self.verbose = verbose

    def do_get_snapshot(self):
        return dict((x['base_id'], x) for x in nosql_client.get_map_features(self.region_id))
    def get_snapshot(self):
        self.state = self.do_get_snapshot()
        self.in_sync = False
        if self.verbose: print 'got snapshot of', len(self.state), 'features'

    def check(self):
        if not self.debug: return
        test = self.do_get_snapshot()
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
        snapshot_time = -1
        if self.state:
            snapshot_time = max(x.get('last_mtime',-1) for x in self.state.itervalues())
        if self.verbose: print 'catching up since', snapshot_time
        for update in nosql_client.get_map_features(self.region_id, updated_since = snapshot_time):
            if update.get('last_mtime') > map_time: continue # not received yet
            self.apply_update(update['base_id'], update)
        self.in_sync = True
        if self.verbose: print 'catchup done'

    def apply_update(self, base_id, base_data):
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
        self.apply_update(base_id, base_data)

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
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'qd', [])
    if len(args) < 1:
        print 'usage: %s region_id' % sys.argv[0]
        sys.exit(1)

    for key, val in opts:
        if key == '-q': verbose = False
        elif key == '-d': debug = True

    region_id = args[0]
    logger = MapLogger(region_id, debug = debug, verbose = verbose)

    chat_client = SpinChatClient.Client(SpinConfig.config['chatserver']['chat_host'],
                                        SpinConfig.config['chatserver']['chat_port'],
                                        SpinConfig.config['chatserver'].get('secret_full', SpinChatProtocol.default_secret_full),
                                        lambda x: sys.stdout.write(x+'\n'),
                                        subscribe = True,
                                        verbose = False)
    chat_client.listener = logger.recv
    reactor.addSystemEventTrigger('before', 'shutdown', chat_client.disconnect)

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                         log_exception_func = lambda x: sys.stderr.write(x+'\n'))

    # first retrieve a static snapshot of the current map
    logger.get_snapshot()

    reactor.run()
