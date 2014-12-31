#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# client side of SpinDB connection
# uses the synchronous ampy API
# OBSOLETE - replaced by SpinNoSQL

import ampy
import SpinDB
SpinDB.init_for_ampy()

import string
import time
import traceback
import socket
import SpinJSON

# compact JSON dump method
def json_dumps_compact(x):
    return SpinJSON.dumps(x, pretty = False, newline = False, double_precision = 5)

class Client:
    def __init__(self, host, port, secret, log_exception_func, identity = 'unknown', latency_func = None,
                 map_update_hook = None):
        self.log_exception_func = log_exception_func
        self.secret = secret
        self.identity = identity
        self.latency_func = latency_func
        self.map_update_hook = map_update_hook
        self.proxy = ampy.Proxy(host, int(port), socketTimeout=60)
        self._connect()

    def _connect(self):
        self.proxy.connect()
        self.callRemote_safe('authenticate', '_connect', secret = self.secret, identity = self.identity)['state']

    def callRemote_safe(self, cmd_name, reason, **kw):
        cmd = SpinDB.CMD[cmd_name]

        # sanitize string arguments from unicode so that AMP doesn't freak out :|
        for key, argtype in SpinDB.commands[cmd_name]['arguments']:
            if argtype == 'string' or argtype == 'unicode':
                kw[key] = str(kw[key])

        while True:
            try:
                if self.latency_func:
                    start_time = time.time()

                ret = self.proxy.callRemote(cmd, **kw)

                if self.latency_func:
                    end_time = time.time();
                    self.latency_func('DB:'+cmd_name + (('('+reason+')') if reason else ''), end_time-start_time)
                    self.latency_func('DB:ALL', end_time-start_time)

                #print 'callremote OK'
                return ret

            except (TypeError, ValueError):
                # something went wrong before request was transmitted
                raise

            except ampy.AMPError:
                # request got to DB server, but encountered an error in processing
                raise

            except socket.error:
                #print 'callremote FAIL'
                self.log_exception_func('SpinDBClient socket error: ' + traceback.format_exc() + '\nReconnecting to dbserver...')
                # don't spam errors
                time.sleep(1)
            self.reconnect()
    def reconnect(self):
        while True:
            print 'database connection error, attempting to reconnect!'
            self.proxy.close()
            try:
                self._connect()
                print 'database connection restored'
                return
            except socket.error:
                # don't spam the server
                time.sleep(10)

    def set_time(self, t): pass # for drop-in compatibility with SpinNoSQL

    # retreive an arbitrarily long string result with the minimum number of round-trips
    # assumes 'result' is a dictionary containing an in-line 'result' field and a 'long_len' field
    # if the 'long_len' value is > 0, then retrieve the result as a string using get_long_result(),
    # otherwise return the inline 'result'
    def _get_long_result(self, result):
        length = result['long_len']
        if length > 0:
            buf = ''
            for i in xrange(0, length, SpinDB.MSG_LIMIT):
                start = i
                end = min(i+SpinDB.MSG_LIMIT, length)
                finish = (end >= length)
                buf += self.callRemote_safe('get_long_result', None, start=start, end=end, finish=finish)['substr']
        else:
            buf = result['result']
        return buf

    def do_facebook_id_to_spinpunch_batch(self, fbid_list, intrusive, reason = None):
        fbid_list = string.join(fbid_list, ':')
        ret = self.callRemote_safe('facebook_id_lookup_batch', reason,
                                   facebook_ids = fbid_list,
                                   add_if_missing = intrusive)['user_ids']
        ret = map(int, ret.split(':'))
        return ret

    def facebook_id_to_spinpunch_batch(self, fbid_list, intrusive = False):
        # split list into chunks to avoid exceeding the AMP protocol's 65k character limit
        limit = int(SpinDB.MSG_LIMIT/ 20) # roughly 20 bytes per Facebook ID
        input = [fbid_list[i:i+limit] for i in xrange(0, len(fbid_list), limit)]
        output = [self.do_facebook_id_to_spinpunch_batch(sublist, intrusive) for sublist in input]
        # flatten output list
        return [r for sublist in output for r in sublist]

    def facebook_id_to_spinpunch_single(self, facebook_id, intrusive, reason = None):
        return self.callRemote_safe('facebook_id_lookup_single', reason,
                                   facebook_id = facebook_id,
                                   add_if_missing = intrusive)['user_id']

    def get_user_id_range(self, reason = None):
        result = self.callRemote_safe('get_user_id_range', reason)
        return [result['min'], result['max']]


    def lock_release(self, lock_id, generation, expected_state, expected_owner_id = -1):
        return self.callRemote_safe('lock_release', None, lock_id=lock_id, generation=generation, expected_state=expected_state, expected_owner_id=expected_owner_id)['state']
    def player_lock_release(self, user_id, generation, expected_state, expected_owner_id = -1):
        return self.lock_release(SpinDB.emulate_player_lock_id(user_id), generation, expected_state, expected_owner_id = expected_owner_id)

    def lock_keepalive_batch(self, lock_ids, generations, expected_states, check_messages = False):
        # split list into chunks to avoid exceeding the AMP protocol's 65k character limit
        if len(lock_ids) < 1:
            return []
        limit = int(SpinDB.MSG_LIMIT / 16) # roughly 16 bytes per ID/state
        idlist = [lock_ids[i:i+limit] for i in xrange(0, len(lock_ids), limit)]
        genlist = [generations[i:i+limit] for i in xrange(0, len(lock_ids), limit)]
        explist = [expected_states[i:i+limit] for i in xrange(0, len(lock_ids), limit)]
        output = [self.do_lock_keepalive_batch(idlist[k], genlist[k], explist[k], check_messages) for k in xrange(len(idlist))]
        return [r for sublist in output for r in sublist]
    def player_lock_keepalive_batch(self, user_ids, generations, expected_states, check_messages = False):
        return self.lock_keepalive_batch([SpinDB.emulate_player_lock_id(x) for x in user_ids], generations, expected_states, check_messages = check_messages)
    def do_lock_keepalive_batch(self, idlist, genlist, explist, check_messages):
        messages = self.callRemote_safe('lock_keepalive_batch', None,
                                        lock_ids=string.join(idlist, ':'),
                                        generations=string.join(map(str, genlist), ':'),
                                        expected_states=string.join(map(str, explist), ':'),
                                        check_messages=check_messages)['messages']
        if messages:
            return map(int, messages.split(':'))
        else:
            return []
    def player_lock_keepalive(self, user_id, generation, expected_state):
        return self.player_lock_keepalive_batch([user_id], [generation], [expected_state])

    def lock_get_state_batch(self, lock_ids, reason = None):
        # split list into chunks to avoid exceeding the AMP protocol's 65k character limit
        if len(lock_ids) < 1:
            return []
        limit = int(SpinDB.MSG_LIMIT / 10) # roughly 10 bytes per ID
        idlist = [lock_ids[i:i+limit] for i in xrange(0, len(lock_ids), limit)]
        output = [self.do_lock_get_state_batch(idlist[k], reason) for k in xrange(len(idlist))]
        return [r for sublist in output for r in sublist]
    def player_lock_get_state_batch(self, user_ids, reason = None):
        return self.lock_get_state_batch([SpinDB.emulate_player_lock_id(x) for x in user_ids], reason = reason)
    def do_lock_get_state_batch(self, idlist, reason):
        ret = self.callRemote_safe('lock_get_state_batch', reason,
                                   lock_ids=string.join(idlist, ':'))['states']
        flat = map(int, ret.split(':'))
        # convert from [0,0,1,1,...] to [(0,0), (1,1), ...]
        return zip(flat[::2], flat[1::2])
    def lock_acquire_login(self, lock_id, owner_id = -1):
        ret = self.callRemote_safe('lock_acquire_login', None, lock_id=lock_id, owner_id = owner_id)
        return ret['state'], ret['generation']
    def player_lock_acquire_login(self, user_id, owner_id = -1):
        return self.lock_acquire_login(SpinDB.emulate_player_lock_id(user_id), owner_id = owner_id)
    def lock_acquire_attack(self, lock_id, generation, owner_id = -1):
        return self.callRemote_safe('lock_acquire_attack', None, lock_id=lock_id, generation=generation, owner_id = owner_id)['state']
    def player_lock_acquire_attack(self, user_id, generation, owner_id = -1):
        return self.lock_acquire_attack(SpinDB.emulate_player_lock_id(user_id), generation, owner_id = owner_id)

    def msg_send(self, msglist, reason = None):
        if len(msglist) > 0:
            ret = self.callRemote_safe('msg_send', reason, msglist = json_dumps_compact(msglist))['success']
        else:
            ret = True
        return ret
    def msg_ack(self, to, idlist, reason = None):
        if len(idlist) > 0:
            ret = self.callRemote_safe('msg_ack', reason, to = to, idlist = string.join(idlist, ':'))['success']
        else:
            ret = True
        return ret
    def msg_recv(self, to, type_filter = None, reason = None):
        if type_filter:
            type_filter = string.join(type_filter, ':')
        else:
            type_filter = ''
        result = self.callRemote_safe('msg_recv', reason, to = to, type_filter = type_filter)
        result_json = self._get_long_result(result)
        ret = SpinJSON.loads(result_json)
        return ret

    def get_users_modified_since(self, mintime, maxtime = 1<<31):
        # get list of IDs of users/players who have been modified since 'mintime'
        result = self._player_cache_query([['last_mtime', mintime, maxtime]], -1)
        return result

    def _player_cache_query(self, query, max_ret, reason = None):
        fields = []
        minima = []
        maxima = []
        operators = []
        for elem in query:
            fields.append(str(elem[0]))
            minima.append(str(elem[1]))
            maxima.append(str(elem[2]))
            if len(elem) >= 4:
                op = str(elem[3])
            else:
                op = 'in'
            operators.append(op)
        fields = string.join(fields, ':')
        minima = string.join(minima, ':')
        maxima = string.join(maxima, ':')
        operators = string.join(operators, ':')
        result = self.callRemote_safe('player_cache_query', reason, fields=fields, minima=minima, maxima=maxima, operators=operators, max_ret=max_ret)
        buf = self._get_long_result(result)
        if buf:
            ret = map(int, buf.split(':'))
        else:
            ret = []
        return ret

    def player_cache_query_tutorial_complete_and_mtime_between(self, mintime, maxtime, reason = None):
        return self._player_cache_query([['last_mtime', mintime, maxtime],
                                         ['tutorial_complete',1,1]], -1)
    def player_cache_query_ladder_rival(self, query, max_ret, reason = None): return self._player_cache_query(query, max_ret, reason)

    def player_cache_update(self, user_id, props, reason = None, overwrite = False):
        return self.callRemote_safe('player_cache_update', reason, user_id = user_id, props = json_dumps_compact(props), overwrite = bool(overwrite))['success']

    def player_cache_lookup_batch(self, user_id_list, fields = None, reason = None):
        if not user_id_list:
            return []
        fields = string.join(fields, ':') if fields else ''
        result = self.callRemote_safe('player_cache_lookup_batch', reason, user_ids = string.join(map(str, user_id_list), ':'), fields = fields)
        result_json = self._get_long_result(result)
        if result_json:
            ret = SpinJSON.loads(result_json)
        else:
            ret = []
        return ret

    def player_cache_get_scores(self, user_ids, fields, reason = None):
        result = self.callRemote_safe('player_cache_get_scores', reason, user_ids=string.join(map(str,user_ids),':'), fields=string.join(fields,':'))
        result_json = self._get_long_result(result)
        if result_json:
            ret = SpinJSON.loads(result_json)
        else:
            ret = []
        return ret
    def player_cache_get_leaders(self, field, max_ret, reason = None):
        return SpinJSON.loads(self.callRemote_safe('player_cache_get_leaders', reason, field=field,max_ret=max_ret)['result'])

    def abtest_join_cohorts(self, ptests, pcohorts, plimits):
        tests = string.join(ptests, ':')
        cohorts = string.join(pcohorts, ':')
        limits = string.join(map(str, plimits), ':')
        ret = self.callRemote_safe('abtest_join_cohorts', None, tests=tests, cohorts=cohorts, limits=limits)['results']
        if ret:
            return map(int, ret.split(':'))
        else:
            return []

    def map_region_create(self, region_id):
        return self.callRemote_safe('map_region_create', None, region_id=region_id)['success']
    def map_region_drop(self, region_id):
        return self.callRemote_safe('map_region_drop', None, region_id=region_id)['success']

    def map_cache_lock_acquire(self, region_id, base_id, owner_id, generation = -1, do_hook = True, reason = None):
        state = self.callRemote_safe('map_cache_lock_acquire', reason, region_id=region_id, base_id=base_id, owner_id=owner_id, generation=generation)['state']
        if state > 0 and self.map_update_hook and do_hook:
            self.map_update_hook(region_id, base_id, {'LOCK_STATE':state,'LOCK_OWNER':owner_id}, owner_id)
        return state
    def map_cache_lock_keepalive_batch(self, region_id, pbase_ids, pgenerations, reason = None):
        base_ids = string.join(map(str, pbase_ids), ':')
        generations = string.join(map(str, pgenerations), ':')
        return self.callRemote_safe('map_cache_lock_keepalive_batch', reason, region_id=region_id, base_ids=base_ids, generations=generations)['success']
    def map_cache_lock_release(self, region_id, base_id, owner_id, generation = -1, do_hook = True, reason = None):
        self.callRemote_safe('map_cache_lock_release', reason, region_id=region_id, base_id=base_id, generation=generation, expected_owner_id=owner_id)['state']
        if self.map_update_hook and do_hook:
            self.map_update_hook(region_id, base_id, {'LOCK_STATE':0}, owner_id)
    def map_cache_update(self, region_id, base_id, props, exclusive = -1, originator = None, reason = None):
        ret = self.callRemote_safe('map_cache_update', reason, region_id=region_id, base_id = base_id, props = json_dumps_compact(props), exclusive=exclusive)['success']
        if ret and self.map_update_hook:
            self.map_update_hook(region_id, base_id, props, originator)
        return ret

    def map_cache_query(self, region_id, query, max_ret, updated_since = -1, reason = None):
        fields = string.join([elem[0] for elem in query], ':')
        minima = string.join(map(SpinDB.encode_query_field, [elem[1] for elem in query]), ':')
        maxima = string.join(map(SpinDB.encode_query_field, [elem[2] for elem in query]), ':')
        result = self.callRemote_safe('map_cache_query', reason, region_id=region_id,
                                      fields=fields, minima=minima, maxima=maxima, max_ret=max_ret, updated_since=int(updated_since))
        result_time = result['db_time']
        result_json = self._get_long_result(result)
        if result_json:
            ret = SpinJSON.loads(result_json)
        else:
            ret = []
        return result_time, ret
    def map_cache_population_query(self, query, reason = None):
        fields = string.join([elem[0] for elem in query], ':')
        minima = string.join(map(SpinDB.encode_query_field, [elem[1] for elem in query]), ':')
        maxima = string.join(map(SpinDB.encode_query_field, [elem[2] for elem in query]), ':')
        result = self.callRemote_safe('map_cache_population_query', reason, fields=fields, minima=minima, maxima=maxima)
        result_json = self._get_long_result(result)
        if result_json:
            return SpinJSON.loads(result_json)
        else:
            return {}
    def map_cache_occupancy_check(self, region_id, coordlist, reason = None):
        if not coordlist: return False
        return self.callRemote_safe('map_cache_occupancy_check', reason, region_id=region_id, coordlist=SpinJSON.dumps(coordlist))['blocked']


if __name__ == '__main__':
    import sys
    import SpinConfig
    client = Client('localhost', 7998,
                    SpinConfig.config['dbserver'].get('secret_full', SpinDB.default_secret_full),
                    lambda x: sys.stdout.write(x))
    print 'ID RANGE', client.get_user_id_range()
    print client.facebook_id_to_spinpunch_single('example1', False)
    client.player_cache_update(1112, {'player_level': 5, 'pvp_rating': 2.2, 'first_name': u'Dan\xdcfd'})
    client.player_cache_update(1112, {'facebook_id': 'example1', 'pvp_rating': 3.3})
    client.player_cache_update(1113, {'player_level': 6, 'pvp_rating': 4.4, 'first_name': u'\u9f13\u9f13'})
    print client.player_cache_query([['pvp_rating',3.0,5.2], ['player_level', 6, 10]], 10)
    print client.player_cache_lookup_batch([1112,1113,9999])
    for i in range(3):
        print client.abtest_join_cohorts(['test0', 'test1'], ['groupA', 'groupB'], [1, 2])

    print 'SCORES', client.player_cache_get_scores([1112], ['score_xp_s1', 'score_resources_looted_wk0'])
    print client.player_cache_get_leaders('score_xp_s1', 10)
    print 'LOGINS', client.get_users_modified_since(int(time.time())-100)
    print 'STATES', client.player_lock_get_state_batch([1112,1115])
    time_now = time.time()
    print client.lock_acquire_attack('q1001', -1)
    print client.map_region_create('test')
    print client.map_cache_update('test', 'q1001', {'base_type': 'quarry', 'base_map_loc':[0,0], 'base_landlord_id': 901})
    print client.map_cache_update('test', 'q1001', None)
    print client.map_cache_update('test', 'q1002', {'base_type': 'quarry','base_map_loc':[5,5], 'base_landlord_id': 901})
    print client.map_cache_update('test', 'q1003', {'base_type': 'quarry','base_map_loc':[12,12], 'base_landlord_id': 901})
    print 'RAW', client.map_cache_query('test', [], -1, updated_since = -1)
    print 'RAW2', client.map_cache_query('test', [['base_type','quarry','quarry'], ['base_map_loc[0]',10,15], ['base_map_loc[1]',10,15]], -1, updated_since = -1)
    print 'RAW3', client.map_cache_query('test', [['base_id','q1003','q1003']], -1, updated_since = -1)
    print 'RAW4', client.map_cache_query('test', [['base_landlord_id',901,901]], -1, updated_since = -1)
    print 'INCR', client.map_cache_query('test', [], -1, updated_since = time_now)
    print 'POP', client.map_cache_population_query([['base_type', 'quarry', 'quarry']])
    print client.map_region_drop('test')
    print client.lock_release('q1001', -1, 2)
    if '--clear-locks' in sys.argv:
        print client.player_lock_release(1111, -1, 2)
        print client.player_lock_release(1112, -1, 2)
        print client.player_lock_release(1113, -1, 2)
        print client.player_lock_release(1114, -1, 2)
        print client.player_lock_release(1115, -1, 2)
    for i in range(2):
        print client.msg_send([{'to': [1112,1115],
                                'type': 'resource_gift',
                                'from': 6666,
                                'from_fbid': u"Ersan K\u00f6rpe",
                                'unique_per_sender': 'resource_gift'}])
        client.msg_send([{'to':[1112],
                          'type':'donated_units',
                          'attachments':[{'spec':'blaster_droid'},{'spec':'blaster_droid'},{'spec':'elevation_droid'}],
                          'from':1115}])

    gotten = client.msg_recv(1112, type_filter=['resource_gift'])
    to_ack = []
    for msg in gotten:
        print 'GOT', msg
        to_ack.append(msg['msg_id'])
    print client.msg_ack(1112, to_ack)
