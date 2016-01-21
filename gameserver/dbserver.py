#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# OBSOLETE custom NoSQL server - replaced by SpinNoSQL

import os, sys, uuid
import re
import random
import string
import time
import signal
import traceback
import itertools
import collections
import bisect
import glob

from twisted.internet import reactor, task
from twisted.protocols import amp
from twisted.internet.protocol import Factory
from twisted.python import log

from SortedCollection import SortedCollection

import Daemonize
import SpinDB
import SpinDBStore
import SpinLog
import SpinConfig
import SpinJSON

SpinDB.init_for_twisted_amp()

db_daemonize = ('-n' not in sys.argv)
db_pidfile = 'dbserver.pid'
verbose = SpinConfig.config['dbserver'].get('verbose', True)
db_log_dir = SpinConfig.config.get('log_dir', 'logs')
db_db_dir = SpinConfig.config.get('db_dir', 'db')

# globals
db_time = int(time.time())
raw_log = None
exception_log = None
trace_log = None
bgtask = None

def reload_spin_config():
    # reload config file
    global verbose
    SpinConfig.reload()
    verbose = SpinConfig.config['dbserver'].get('verbose', True)


# mapping of Facebook user IDs to game player IDs
# note: map keys are strings, not ints!
# "missing" is represented by -1
class FacebookIDTable (SpinDBStore.AsyncJournaledMap):
    def __init__(self):
        SpinDBStore.AsyncJournaledMap.__init__(self,
                                               'facebook_id_map',
                                               os.path.join(db_db_dir, 'facebook_id_map.txt'),
                                               verbose = True)
        self.min_id = 1111 # hard-coded
        self.counter = self.min_id
        if len(self.map) > 0:
            self.counter = max(self.map.itervalues()) + 1

    def get_user_id_range(self):
        return [self.min_id, max(self.min_id, self.counter-1)]

    def facebook_id_to_spinpunch(self, facebook_id, intrusive):
        key = str(facebook_id)
        if self.map.has_key(key):
            return self.map[key]
        if not intrusive:
            return -1
        sp_id = self.counter
        self.counter += 1
        self.pre_change(key)
        self.map[key] = sp_id
        self.set_dirty(key, fsync = SpinConfig.config['dbserver'].get('facebook_id_table_journal_fsync', True))
        return sp_id

facebook_id_table = None # set from init_tables()

class MessageTable (SpinDBStore.AsyncJournaledMap):
    def __init__(self):
        SpinDBStore.AsyncJournaledMap.__init__(self,
                                               'message_table',
                                               os.path.join(db_db_dir, 'message_table.txt'),
                                               verbose = True, sort_numeric = True)
    def send(self, msg, recipient, sync = True):
        key = str(recipient)
        assert 'type' in msg
        if 'msg_id' not in msg: msg['msg_id'] = str(uuid.uuid1())
        if 'time' not in msg: msg['time'] = db_time

        self.pre_change(key)
        if key in self.map:
            val = self.map[key]
            uniq = msg.get('unique_per_sender', False)
            if uniq:
                sender = msg.get('from', None)
                to_remove = []
                for old_msg in val:
                    if (old_msg.get('from', None) == sender) and (old_msg.get('unique_per_sender', False) == uniq):
                        to_remove.append(old_msg)
                for old_msg in to_remove: val.remove(old_msg)
        else:
            val = []
        val.append(msg)
        self.map[key] = val
        self.set_dirty(key, fsync = (sync and SpinConfig.config['dbserver'].get('message_table_journal_fsync', True)))
        return True
    def recv(self, recipient, type_filter):
        key = str(recipient)
        msglist = self.map.get(key, [])
        if type_filter:
            return filter(lambda x: x['type'] in type_filter, msglist)
        else:
            return msglist
    def ack(self, recipient, msg_idlist):
        key = str(recipient)
        if key not in self.map: return
        self.pre_change(key)
        val = self.map[key]
        to_remove = []
        for msg in val:
            if msg['msg_id'] in msg_idlist:
                to_remove.append(msg)
        for msg in to_remove: val.remove(msg)
        if len(val) < 1: del self.map[key]
        self.set_dirty(key, fsync = SpinConfig.config['dbserver'].get('message_table_journal_fsync', True))
        return True

    def can_prune(self, key, val):
        to_remove = []
        for msg in val:
            expire_time = msg.get('expire_time', -1)
            if expire_time < 0:
                force_expire = SpinConfig.config['dbserver'].get('force_expire', {}).get(msg['type'], -1)
                if force_expire > 0:
                    expire_time = msg['time'] + force_expire
            if expire_time > 0 and db_time > expire_time:
                to_remove.append(msg)
        for msg in to_remove: val.remove(msg)
        return (len(val) < 1)

message_table = None # set from init_tables()

class ABTestTable (SpinDBStore.Map):
    def __init__(self):
        SpinDBStore.Map.__init__(self,
                                 'abtest_table',
                                 os.path.join(db_db_dir, 'abtest_table.txt'),
                                 verbose = True)

    def join_cohort(self, test, cohort, limit):
        if limit < 0:
            return True
        if test not in self.map:
            self.map[test] = {}
        if cohort not in self.map[test]:
            self.map[test][cohort] = {'N': 0}
        coh = self.map[test][cohort]
        if coh['N'] >= limit:
            return False
        self.pre_change(test)
        coh['N'] += 1
        self.set_dirty(test, fsync = SpinConfig.config['dbserver'].get('abtest_table_fsync', True))
        return True

abtest_table = None # set from init_tables()

# global cache of map territory info
# this is still being worked on
class MapCache (SpinDBStore.JournaledMap):
    array_re = re.compile('(.+)\[([0-9]+)\]')

    def __init__(self, region_id):
        SpinDBStore.JournaledMap.__init__(self,
                                          'map_region_'+region_id,
                                          os.path.join(db_db_dir, 'map_region_'+region_id+'.txt'),
                                          verbose = True)
        self.region_id = region_id

        # keep track of map cell occupancy for mutual exclusion
        self.occupancy = {}
        for entry in self.map.itervalues():
            self.add_occ(entry)

        # keep track of removed bases for incremental updates
        self.MAX_DELETION_AGE = 10800 # 3 hours - should be similar to the max session timeout
        self.deletion_times = collections.deque()
        self.deletion_ids = collections.deque()

    def prune_deletions(self):
        while len(self.deletion_times) > 0 and db_time > (self.deletion_times[0] + self.MAX_DELETION_AGE):
            self.deletion_times.popleft()
            self.deletion_ids.popleft()

    def add_occ(self, entry):
        if 'base_map_loc' in entry:
            k = tuple(entry['base_map_loc'])
            if k not in self.occupancy:
                self.occupancy[k] = []
            self.occupancy[k].append(entry)
    def remove_occ(self, entry):
        if 'base_map_loc' in entry:
            k = tuple(entry['base_map_loc'])
            if k in self.occupancy:
                if entry in self.occupancy[k]:
                    self.occupancy[k].remove(entry)
                if len(self.occupancy[k]) < 1:
                    del self.occupancy[k]
    def remove(self, key, entry):
        self.remove_occ(entry)
        del self.map[key]

    def occupancy_check(self, coordlist):
        for coord in coordlist:
            k = tuple(coord)
            if k in self.occupancy:
                for entry in self.occupancy[k]:
                    exptime = entry.get('base_expire_time',-1)
                    if exptime > 0 and exptime < db_time:
                        continue # expired base, continue
                    return True
        return False

    # only used because the LOCK_STATE is maintained externally
    # last_mtime updates are NOT journaled, because any "true" change to the entry will be reflected in a forthcoming update() after the lock is released
    def bump_mtime(self, base_id):
        if base_id in self.map:
            self.map[base_id]['last_mtime'] = db_time

    def update(self, base_id, props, exclusive):
        key = base_id
        self.pre_change(key)
        if props is None:
            if key in self.map:
                self.remove(key, self.map[key])
                self.deletion_times.append(db_time)
                self.deletion_ids.append(base_id)
                self.prune_deletions()
        else:
            if (exclusive >= 0) and ('base_map_loc' in props):
                for y in xrange(props['base_map_loc'][1]-exclusive, props['base_map_loc'][1]+exclusive+1):
                    for x in xrange(props['base_map_loc'][0]-exclusive, props['base_map_loc'][0]+exclusive+1):
                        if self.occupancy_check([(x,y)]):
                            return False

            if key in self.map:
                cache = self.map[key]
            else:
                cache = {}

                # if creating a new entry, be sure it has essential fields
                assert 'base_type' in props
                assert 'base_map_loc' in props

                # XXX inefficient
                for i in xrange(len(self.deletion_ids)):
                    if self.deletion_ids[i] == base_id:
                        del self.deletion_ids[i]
                        del self.deletion_times[i]
                        break

            for k, v in props.iteritems():
                if k == 'base_map_loc':
                    self.remove_occ(cache)
                cache[k] = v
                if k == 'base_map_loc':
                    self.add_occ(cache)

            cache['base_id'] = key # add backreference
            cache['last_mtime'] = db_time

            self.map[key] = cache

        self.set_dirty(key, fsync = SpinConfig.config['dbserver'].get('map_cache_journal_fsync', False))
        return True

    def get_query_value(self, props, field):
        # do a quick test for [ since array_re.search is slow
        match = ('[' in field) and self.array_re.search(field)
        if match:
            field_name = match.group(1)
            index = int(match.group(2))
            if field_name in props:
                return props[field_name][index]
            else:
                return -1
        else:
            return props.get(field, -1)

    def query(self, fields, minima, maxima, max_ret, updated_since):
        ret = []

        for key, props in self.map.iteritems():
            if props:
                if updated_since > 0 and props.get('last_mtime',-1) < updated_since: continue

                match = True
                for i in xrange(len(fields)):
                    val = self.get_query_value(props, fields[i])
                    # note: this comparison works for both strings and numbers!
                    if val < minima[i] or val > maxima[i]:
                        match = False
                        break
                if match:
                    # note: LOCK_STATE is a special property added in real-time by "joining" on the lock table
                    # this is a nasty hack. eventually base locks should just move into the MapCache, and the
                    # gameserver should mirror player lock acquire/release into the home base MapCache entry.
                    lock_id = None
                    base_type = props.get('base_type', None)
                    if base_type == 'home':
                        if 0:
                            player_id = int(props['base_id'][1:])
                            lock_id = SpinDB.emulate_player_lock_id(player_id)
                    else:
                        lock_id = SpinDB.base_lock_id(self.region_id, props['base_id'])
                    if lock_id:
                        lock = lock_table.get_lock(lock_id)
                        if lock and lock.state != Lock.OPEN:
                            props = props.copy() # do not alter in-memory version (?)
                            props['LOCK_STATE'] = lock.state
                            if lock.owner_id > 0:
                                props['LOCK_OWNER'] = lock.owner_id

                    ret.append(props)
                    if (max_ret > 0) and (len(ret) >= max_ret):
                        # already have enough results
                        break

        # special case for incremental updates - also return IDs of deleted bases
        if updated_since > 0:
            min_i = bisect.bisect_left(self.deletion_times, updated_since)
            for i in xrange(min_i, len(self.deletion_times)):
                ret.append({'base_id': self.deletion_ids[i], 'last_mtime': self.deletion_times[i], 'DELETED':1})

        return ret

map_regions = None # set from init_tables()


# mapping of game player IDs to cached player info
class PlayerCache (SpinDBStore.AsyncJournaledMap):
    def __init__(self):
        SpinDBStore.AsyncJournaledMap.__init__(self,
                                               'player_cache',
                                               os.path.join(db_db_dir, 'player_cache.txt'),
                                               verbose = True, sort_numeric = True)
        self.score_indices = {}
        self.level_index = None

        if len(self.map) > 0:
            self.key_range = [min(itertools.imap(int, self.map.iterkeys())),
                              max(itertools.imap(int, self.map.iterkeys()))]
        else:
            self.key_range = [-1,-1]
        self.init_level_index()

    def update(self, user_id, props, overwrite):
        key = str(user_id)
        self.pre_change(key)

        if self.key_range[0] == -1:
            self.key_range[0] = user_id
        else:
            self.key_range[0] = min(self.key_range[0], user_id)
        if self.key_range[1] == -1:
            self.key_range[1] = user_id
        else:
            self.key_range[1] = max(self.key_range[1], user_id)

        if overwrite and (key in self.map):
            # blow away all old properties. remove from score_indices to maintain consistency.
            old = self.map[key]
            for k, v in old.iteritems():
                if k in self.score_indices:
                    self.score_indices[k].unrank(old)
                    # get rid of obsolete score_indices
                    if len(self.score_indices[k]) < 1:
                        del self.score_indices[k]

                if (self.level_index is not None) and (k == 'player_level'):
                    self.level_index[v].remove(user_id)
                    if len(self.level_index[v]) < 1:
                        del self.level_index[v]

            del self.map[key]

        if key in self.map:
            cache = self.map[key]
        else:
            cache = {}
        cache['user_id'] = user_id # add backreference
        for k, v in props.iteritems():

            if (self.level_index is not None) and (k == 'player_level'):
                old = cache.get(k, None)
                if v != old:
                    if (old is not None):
                        self.level_index[old].remove(user_id)
                        if len(self.level_index[old]) < 1:
                            del self.level_index[old]
                    if (v is not None):
                        if (v not in self.level_index):
                            assert type(v) is int
                            self.level_index[v] = SortedCollection()
                        self.level_index[v].insert(user_id)

            if k in self.score_indices:
                # must do this first because rerank assumes the object hasn't changed since it was inserted
                self.score_indices[k].rerank(cache, v)
            else:
                cache[k] = v

        self.map[key] = cache
        self.set_dirty(key, fsync = SpinConfig.config['dbserver'].get('player_cache_journal_fsync', False))
        return True

    def lookup(self, user_id, fields):
        key = str(user_id)
        iid = int(user_id)
        if key in self.map:
            val = self.map[key]
            if not fields:
                props = val
            else:
                props = {}
                for field in fields:
                    if field in val:
                        props[field] = val[field]

            if (not fields) or ('LOCK_STATE' in fields):
                # note: LOCK_STATE is a special property added in real-time!
                lock = lock_table.get_lock(SpinDB.emulate_player_lock_id(iid))
                if lock and lock.state != Lock.OPEN:
                    if not fields:
                        props = props.copy() # do not alter in-memory version
                    props['LOCK_STATE'] = lock.state
                    if lock.owner_id > 0 and ((not fields) or ('LOCK_OWNER' in fields)):
                        props['LOCK_OWNER'] = lock.owner_id
        else:
            props = {}
        return props

    def random_map_iter(self):
        if self.key_range[0] < 0: return []
        return self._random_map_iter()

    def _random_map_iter(self):
        # choose random starting key value in the range self.key_range[0] to self.key_range[1], INCLUSIVE
        start_key = int(random.random()*(self.key_range[1]-self.key_range[0])+0.5) + self.key_range[0]
        keynum = start_key

        # iterate through map, cycling around after reaching max_key
        while True:
            yield keynum
            keynum += 1
            if keynum > self.key_range[1]:
                # wrap around key range
                keynum = self.key_range[0]
            if keynum == start_key:
                # got back to where we started - we've seen all players
                break

    def level_index_iter(self, indices):
        if not indices: return []

        # merge contents of each index and sort by user_id
        id_list = indices[0]._items.__class__()
        for index in indices:
            id_list += index._items

        id_list = sorted(id_list)

        # random rotation - same behavior as the wrap-around above
        if len(id_list) > 0:
            n = int(random.random()*len(id_list))
            id_list = id_list[-n:] + id_list[:-n]

        return id_list

    def query(self, fields, minima, maxima, operators, max_ret):
        # apply a set of numeric range criteria to the entire user base, and return up to max_ret matching users
        # this should return a RANDOM subset of matching users, different each time, since it is used for Rival matchmaking
        ret = []

        scanned = 0
        if verbose:
            print
            print 'query:', [(fields[i], minima[i], maxima[i]) for i in xrange(len(fields))]
            print 'users', len(self.map),
            start_time = time.time()

        myiter = None

        # if filtering on player_level, and the minimum level is high enough, then use the level indices rather than a global iteration
        use_level_index = SpinConfig.config['dbserver'].get('use_level_index', -1)
        if (use_level_index > 0) and ('player_level' in fields):
            i = fields.index('player_level')
            if (operators[i] == 'in') and (minima[i] >= use_level_index):
                self.init_level_index()
                indices = [idx for level, idx in self.level_index.iteritems() if (level >= minima[i] and level <= maxima[i])]
                if verbose: print 'USING LEVEL_INDEX', minima[i], maxima[i], '(%d indices)' % len(indices)
                myiter = self.level_index_iter(indices)

        if myiter is None:
            # fall back to standard random-start-point iterator
            myiter = self.random_map_iter()

        for keynum in myiter:
            key = str(keynum)
            scanned += 1
            props = self.map.get(key, None)
            if props:
                match = True
                for i in xrange(len(fields)):
                    if fields[i] == 'LOCK_STATE':
                        lock = lock_table.get_lock(SpinDB.emulate_player_lock_id(keynum))
                        val = lock.state if lock else Lock.OPEN
                    else:
                        val = props.get(fields[i], -1)
                    op = operators[i]
                    if op == 'in':
                        if val < minima[i] or val > maxima[i]:
                            match = False
                            break
                    elif op == '!in':
                        if val >= minima[i] and val <= maxima[i]:
                            match = False
                            break
                    else:
                        if verbose:
                            print 'BAD OPERATOR', op
                        match = False
                        break
                if match:
                    ret.append(keynum)
                    if (max_ret > 0) and (len(ret) >= max_ret):
                        # already have enough results
                        break

        if verbose:
            end_time = time.time()
            print 'matched', len(ret), 'users', 'scanned', scanned, 'users'
            print 'total', '%.1f ms' % (1000*(end_time-start_time))

        return ret

    def init_level_index(self):
        if self.level_index is None:
            print 'PlayerCache building level index...',
            sys.stdout.flush()
            ids_by_level = {}
            for key, entry in self.map.iteritems():
                level = entry.get('player_level', None)
                if level is not None:
                    assert type(level) is int
                    if level not in ids_by_level:
                        ids_by_level[level] = []
                    ids_by_level[level].append(int(key))

            self.level_index = {}
            for level, id_list in ids_by_level.iteritems():
                self.level_index[level] = SortedCollection(iterable = id_list)
            print 'level index complete'

    def dump_indices(self):
        print 'score_indices:', repr(self.score_indices.keys())
        print 'level_index:', repr(self.level_index)

    def init_score_index(self, field):
        if field not in self.score_indices:
            self.score_indices[field] = ScoreIndex(self.map.itervalues(), field)

    def get_score(self, user_id, field):
        self.init_score_index(field)
        key = str(user_id)
        if key not in self.map:
            return None
        return self.score_indices[field].get_score(self.map[str(user_id)])
    def get_leaders(self, field, max_ret):
        self.init_score_index(field)
        return [{'absolute':entry[field],
                 'user_id': entry['user_id'],
                 'player_level': entry.get('player_level',1),
                 'facebook_id': entry.get('facebook_id','-1'),
                 'facebook_first_name': entry.get('facebook_first_name','')} \
               for entry in self.score_indices[field].get_leaders(max_ret)]

class ScoreIndex (object):
    # maintain a list of PlayerCache entries sorted by a specific score field
    # this could be made more efficient using the Python blist C module (for O(log N) inserts/removes)

    def __init__(self, items, field):
        print 'PlayerCache building score index on', field, '...',
        sys.stdout.flush()
        self.field = field
        to_add = [item for item in items if (self.field in item)]
        self.byrank = SortedCollection(iterable = to_add, key = lambda item: -item[self.field])
        print 'done'

    def unrank(self, item):
        if item in self.byrank:
            self.byrank.remove(item)
    def rerank(self, item, newval):
        if self.field in item:
            if item[self.field] == newval:
                # no change to the value
                return
            # note: for this to work the state of item must be IDENTICAL to when it was inserted
            if item in self.byrank:
                self.byrank.remove(item)
        item[self.field] = newval
        self.byrank.insert(item)

    def get_score(self, item):
        if self.field not in item: return None
        if len(self.byrank) < 1: return None
        rank = self.byrank.index(item)
        return {'absolute': item[self.field],
                'rank': rank,
                'percentile': (float(rank)/float(len(self.byrank)))}
    def get_leaders(self, max_ret):
        return self.byrank[0:max_ret]
    def __len__(self):
        return len(self.byrank)

player_cache = None # set up in init_tables()

# track login/attack lock status of players and bases

class Lock (object):
    # mutually-exclusive states
    # NOTE: keep constants in sync with server.py: LockState
    OPEN = 0
    LOGGED_IN = 1
    BEING_ATTACKED = 2

    # number of seconds after which locks are presumed stale and invalid
    # IMPORTANT! must be greater than the longest possible attack time,
    # and also greater than the server's bg_task_interval

    TIMEOUT = 600

    def __init__(self):
        self.state = Lock.OPEN
        self.time = 0
        self.holder = None
        self.owner_id = -1
        self.generation = 0

    def state_str(self):
        return (['OPEN', 'LOGGED_IN', 'BEING_ATTACKED'])[self.state]

class LockTable (object):
    def __init__(self):
        self.map = {}
    def dump(self):
        print 'LockTable:'
        for lock_id, lock in self.map.iteritems():
            print lock_id, lock.time, lock.holder, lock.state_str(), lock.generation

    def get_lock(self, lock_id):
        if not self.map.has_key(lock_id):
            return None
        lock = self.map[lock_id]
        # check if the lock is stale
        if lock.state != Lock.OPEN:
            if (db_time - lock.time) > Lock.TIMEOUT:
                exception_log.event(db_time, 'db: busting expired lock on lock_id %s' % lock_id)
                lock.state = Lock.OPEN
                lock.generation = -1
        return lock

    def keepalive(self, holder, lock_id, new_generation, expected_state):
        if not self.map.has_key(lock_id):
            exception_log.event(db_time, 'db: keepalive on non-existent lock %s' % lock_id)
            return -1
        lock = self.map[lock_id]
        if not holder.same_peer_as(lock.holder):
            exception_log.event(db_time, 'db: keepalive %s old holder %s did not match new holder %s' % (lock_id, str(lock.holder), str(holder)))
        if lock.state != expected_state:
            exception_log.event(db_time, 'db: keepalive %s lock was not in expected state (was %d expected %d holder %s)' % (lock_id, lock.state, expected_state, str(lock.holder)))
        lock.time = db_time
        if new_generation != -1:
            lock.generation = new_generation
        return lock.state

    def release_lock(self, holder, lock_id, generation, expected_state, expected_owner_id):
        if not self.map.has_key(lock_id):
            exception_log.event(db_time, 'db: release_lock on non-existent lock %s' % lock_id)
            return 0
        lock = self.map[lock_id]
        if not holder.same_peer_as(lock.holder):
            exception_log.event(db_time, 'db: release_lock %s: old holder %s did not match new holder %s' % (lock_id, str(lock.holder),str(holder)))
        if lock.owner_id != expected_owner_id:
            exception_log.event(db_time, 'db: release_lock %s: owner %s did not match expected owner %s' % (lock_id, str(lock.owner_id),str(expected_owner_id)))
        if lock.state != expected_state:
            exception_log.event(db_time, 'db: release_lock %s: lock was not in expected state (was %d expected %d holder %s)' % (lock_id, lock.state, expected_state, str(lock.holder)))

        lock.state = Lock.OPEN
        lock.time = db_time
        lock.holder = None
        lock.owner_id = -1

        if generation != -1:
            lock.generation = generation

        # KEEP OLD LOCKS AROUND for the generation number
        #del self.map[user_id]

        # snoop lock updates into MapCache so that mtime gets bumped
        if SpinDB.is_base_lock_id(lock_id):
            region_id, base_id = SpinDB.parse_base_lock_id(lock_id)
            if region_id in map_regions:
                map_regions[region_id].bump_mtime(base_id)

        return 0

    def acquire_login(self, holder, lock_id, owner_id):
        #exception_log.event(db_time, 'db: HERE %s!' % (str(holder)))

        if not self.map.has_key(lock_id):
            self.map[lock_id] = Lock()

        lock = self.map[lock_id]
        if lock.state != Lock.OPEN:
            # check if the lock is stale
            if (db_time - lock.time) > Lock.TIMEOUT:
                exception_log.event(db_time, 'db: busting expired lock on %s' % lock_id)
                lock.state = Lock.OPEN
                lock.generation = -1

            if lock.state == Lock.BEING_ATTACKED:
                # can't log in while under attack
                return -lock.state, lock.generation
            if lock.state == Lock.LOGGED_IN:
                exception_log.event(db_time, 'db: acquire_login from %s but lock %s is logged in already by holder %s!' % (str(holder), lock_id, str(lock.holder)))
                return -lock.state, lock.generation

        lock.state = Lock.LOGGED_IN
        lock.time = db_time
        lock.holder = holder
        lock.owner_id = owner_id

        # reset generation number on old locks so that, if S3 really fails to update, the player is not locked out permanently
        if (db_time - lock.time) > Lock.TIMEOUT:
            lock.generation = -1

        return lock.state, lock.generation

    def acquire_attack(self, holder, lock_id, client_gen, owner_id):
        if not self.map.has_key(lock_id):
            self.map[lock_id] = Lock()

        lock = self.map[lock_id]
        if lock.state != Lock.OPEN:
            # check if the lock is stale
            if (db_time - lock.time) > Lock.TIMEOUT:
                exception_log.event(db_time, 'db: busting expired lock on %s' % lock_id)
                lock.state = Lock.OPEN
                lock.generation = -1

            if lock.state == Lock.BEING_ATTACKED:
                # can't attack while already under attack by someone else
                return -lock.state
            if lock.state == Lock.LOGGED_IN:
                # can't attack while logged in
                return -lock.state

        # reset generation number on old locks so that, if S3 really fails to update, the player is not locked out permanently
        if (db_time - lock.time) > Lock.TIMEOUT:
            lock.generation = -1

        # client tried to acquire a write lock based on stale data, tell him
        # to go away!
        if client_gen != -1 and client_gen < lock.generation:
            return -Lock.LOGGED_IN

        # lock attempt successful
        lock.state = Lock.BEING_ATTACKED
        lock.time = db_time
        lock.holder = holder
        lock.owner_id = owner_id

        # snoop lock updates into MapCache so that mtime gets bumped
        if SpinDB.is_base_lock_id(lock_id):
            region_id, base_id = SpinDB.parse_base_lock_id(lock_id)
            if region_id in map_regions:
                map_regions[region_id].bump_mtime(base_id)

        return lock.state


lock_table = None # setup from init_tables()

# compact JSON dump method
def json_dumps_compact(x):
    return SpinJSON.dumps(x, pretty = False, newline = False, double_precision = 5)

class DBProtocolHandlers (amp.AMP):
    AUTH_NONE = 0
    AUTH_READ = 1
    AUTH_WRITE = 2

    def __init__(self, *args):
        amp.AMP.__init__(self, *args)
        self.auth_state = self.AUTH_NONE
        self.peer_identity = None
        self.long_result = None
        self.last_command = 'unknown'

    def locateResponder(self, name):
        # use this entry point to update db_time
        global db_time
        db_time = int(time.time())
        self.last_command = name
        return super(DBProtocolHandlers,self).locateResponder(name)

    def makeConnection(self, transport):
        super(DBProtocolHandlers,self).makeConnection(transport)
        self.peer = self.transport.getPeer()
        if verbose: print self.peer, 'connection made'
    def connectionLost(self, reason):
        super(DBProtocolHandlers,self).connectionLost(reason)
        if verbose: print self.peer, 'connection lost'

    # catch protocol encoding errors here
    def _safeEmit(self, aBox):
        try:
            return amp.AMP._safeEmit(self, aBox)
        except amp.TooLong:
            exception_log.event(db_time, 'DBSERVER RESPONSE IS TOO LONG! Last command was %s, result was %s' % \
                                (self.last_command, repr(aBox)))
            raise


    def authenticate(self, secret, identity):
        if secret == SpinConfig.config['dbserver'].get('secret_read_only', SpinDB.default_secret_read_only):
            self.auth_state = self.AUTH_READ
        elif secret == SpinConfig.config['dbserver'].get('secret_full', SpinDB.default_secret_full):
            self.auth_state = self.AUTH_READ | self.AUTH_WRITE
        else:
            raise Exception('invalid authentication secret')
        identity = str(identity)
        assert identity
        self.peer_identity = identity
        return {'state': self.auth_state}
    def check_readable(self):
        if not (self.auth_state & self.AUTH_READ):
            raise Exception('no read privileges')
    def check_writable(self):
        if not (self.auth_state & self.AUTH_WRITE):
            raise Exception('no write privileges')

    def get_user_id_range(self):
        self.check_readable()
        range = facebook_id_table.get_user_id_range()
        return {'min': range[0], 'max': range[1]}

    def facebook_id_lookup_single(self, facebook_id, add_if_missing):
        self.check_readable()
        if add_if_missing: self.check_writable()
        #print self.peer, 'facebook_id_lookup_single('+facebook_id+', '+str(add_if_missing)+')',
        ret = facebook_id_table.facebook_id_to_spinpunch(facebook_id, add_if_missing)
        #print '=',ret
        return {'user_id':ret}
    def facebook_id_lookup_batch(self, facebook_ids, add_if_missing):
        self.check_readable()
        if add_if_missing: self.check_writable()
        #print self.peer, 'facebook_id_lookup_batch('+facebook_ids+', '+str(add_if_missing)+')',
        idlist = facebook_ids.split(':')
        ret = []
        for id in idlist:
            ret.append(facebook_id_table.facebook_id_to_spinpunch(id, add_if_missing))
        ret = string.join(map(str, ret), ':')
        #print '=',ret
        return {'user_ids': ret}
    def lock_release(self, lock_id, generation, expected_state, expected_owner_id):
        self.check_writable()
        if verbose:
            print self.peer, 'lock_release(',lock_id,',',generation,',',expected_state,',',expected_owner_id,')',
        ret = lock_table.release_lock(self, lock_id, generation, expected_state, expected_owner_id)
        if verbose:
            print '=',ret
        return {'state':ret}
    def lock_keepalive_batch(self, lock_ids, generations, expected_states, check_messages):
        self.check_writable()
        if verbose:
            print self.peer, 'lock_keepalive_batch(',lock_ids,',',generations,',',expected_states,',',check_messages,')',
        idlist = lock_ids.split(':')
        genlist = map(int, generations.split(':'))
        explist = map(int, expected_states.split(':'))
        ret = []
        for i in xrange(len(idlist)):
            lock_table.keepalive(self, idlist[i], genlist[i], explist[i])
            if check_messages:
                # XXX hack - decode player lock ID
                if idlist[i][0] == 'p':
                    has_messages = 1 if message_table.recv(int(idlist[i][1:]), None) else 0
                else:
                    has_messages = 0
                ret.append(has_messages)

        ret = string.join(map(str, ret), ':')
        if verbose:
            print '=',ret
        return {'messages':ret}
    def lock_get_state_batch(self, lock_ids):
        self.check_readable()
        if verbose:
            print self.peer, 'lock_get_state_batch(',lock_ids,')',
        idlist = lock_ids.split(':')
        ret = []
        for i in xrange(len(idlist)):
            lock = lock_table.get_lock(idlist[i])
            if lock:
                ret += [lock.state, lock.owner_id]
            else:
                ret += [Lock.OPEN, -1]
        ret = string.join(map(str, ret), ':')
        if verbose:
            print '=',ret
        return {'states':ret}
    def lock_acquire_login(self, lock_id, owner_id):
        self.check_writable()
        if verbose:
            print self.peer, 'lock_acquire_login(',lock_id,',',owner_id,')',
        state, generation = lock_table.acquire_login(self, lock_id, owner_id)
        if verbose:
            print '=',state,generation
        return {'state':state, 'generation': generation}
    def lock_acquire_attack(self, lock_id, generation, owner_id):
        self.check_writable()
        if verbose:
            print self.peer, 'lock_acquire_attack(',lock_id,',',generation,',',owner_id,')',
        ret = lock_table.acquire_attack(self, lock_id, generation, owner_id)
        if verbose:
            print '=',ret
        return {'state':ret}

    def msg_send(self, msglist):
        self.check_writable()
        msglist = SpinJSON.loads(msglist)
        for msg in msglist:
            for i in xrange(len(msg['to'])):
                recipient = msg['to'][i]
                message_table.send(msg, recipient, sync = (i == (len(msg['to'])-1)))
        return {'success':True}
    def msg_recv(self, to, type_filter):
        self.check_readable()
        if type_filter:
            type_filter = type_filter.split(':')
        else:
            type_filter = []
        ret = message_table.recv(to, type_filter)
        json_ret = json_dumps_compact(ret)
        if len(json_ret) > SpinDB.MSG_LIMIT:
            self.long_result = json_ret
            long_len = len(self.long_result)
            json_ret = ''
        else:
            long_len = 0
        return {'result': json_ret, 'long_len': long_len}
    def msg_ack(self, to, idlist):
        self.check_writable()
        idlist = idlist.split(':')
        message_table.ack(to, idlist)
        return {'success': True}

    def player_cache_query(self, fields, minima, maxima, operators, max_ret):
        self.check_readable()
        if verbose:
            print self.peer, 'player_cache_query(',fields,',',minima,',',maxima,',',operators,',',max_ret,')',
        fields = fields.split(':')
        minima = map(float, minima.split(':'))
        maxima = map(float, maxima.split(':'))
        operators = operators.split(':')
        ret = player_cache.query(fields, minima, maxima, operators, max_ret)
        if ret:
            ret = string.join(map(str, ret), ':')
        else:
            ret = ''
        if len(ret) > SpinDB.MSG_LIMIT:
            self.long_result = ret
            long_len = len(self.long_result)
            ret = ''
        else:
            long_len = 0
        return {'result': ret, 'long_len': long_len}

    def get_long_result(self, start, end, finish):
        assert self.long_result is not None
        ret = self.long_result[start:end]
        if finish:
            self.long_result = None
        if verbose:
            print 'get_long_result(%d,%d,%d) = "%s"' % (start, end, finish, ret)
        return {'substr': ret}

    def player_cache_update(self, user_id, props, overwrite):
        self.check_writable()
        #print self.peer, 'player_cache_update(',user_id,',',props,')',
        player_cache.update(user_id, SpinJSON.loads(props), overwrite)
        ret = True
        #print '=',ret
        return {'success':ret}
    def player_cache_lookup_batch(self, user_ids, fields):
        self.check_readable()
        #print self.peer, 'player_cache_lookup_batch('+user_ids+')',
        idlist = user_ids.split(':')
        fields = fields.split(':') if len(fields)>0 else None
        ret = [player_cache.lookup(user_id, fields) for user_id in idlist]
        json_ret = json_dumps_compact(ret)
        if len(json_ret) > SpinDB.MSG_LIMIT:
            self.long_result = json_ret
            long_len = len(self.long_result)
            json_ret = ''
        else:
            long_len = 0
        return {'result':json_ret, 'long_len': long_len}
    def player_cache_get_scores(self, user_ids, fields):
        self.check_readable()
        if verbose:
            print self.peer, 'player_cache_get_scores(',user_ids,',',fields,')',
        user_ids = user_ids.split(':')
        fields = fields.split(':')
        ret = [[player_cache.get_score(user_id, field) for field in fields] for user_id in user_ids]
        if verbose:
            print '=',ret
        json_ret = json_dumps_compact(ret)
        if len(json_ret) > SpinDB.MSG_LIMIT:
            self.long_result = json_ret
            long_len = len(self.long_result)
            json_ret = ''
        else:
            long_len = 0
        return {'result':json_ret, 'long_len': long_len}
    def player_cache_get_leaders(self, field, max_ret):
        self.check_readable()
        if verbose:
            print self.peer, 'player_cache_get_leaders(',field,',',max_ret,')',
        ret = player_cache.get_leaders(field, max_ret)
        ret = json_dumps_compact(ret)
        if verbose:
            print '=',ret
        return {'result':ret}
    def abtest_join_cohorts(self, tests, cohorts, limits):
        self.check_writable()
        if verbose:
            print self.peer, 'abtest_join_cohorts(',tests,',',cohorts,',',limits,')',
        tests = tests.split(':')
        cohorts = cohorts.split(':')
        limits = map(int, limits.split(':'))
        ret = []
        for i in xrange(len(tests)):
            ret.append(int(abtest_table.join_cohort(tests[i], cohorts[i], limits[i])))
        ret = string.join(map(str, ret), ':')
        if verbose:
            print '=',ret
        return {'results': ret}

    def map_region_create(self, region_id):
        if region_id not in map_regions:
            map_regions[region_id] = MapCache(region_id)
        return {'success':True}
    def map_region_drop(self, region_id):
        if region_id in map_regions:
            map_regions[region_id].destroy()
            del map_regions[region_id]
        return {'success':True}

    def map_cache_update(self, region_id, base_id, props, exclusive):
        self.check_writable()
        region = map_regions.get(region_id, None)
        if region:
            ret = region.update(base_id, SpinJSON.loads(props), exclusive)
        else:
            ret = False
        return {'success':ret}
    def map_cache_query(self, region_id, fields, minima, maxima, max_ret, updated_since):
        self.check_readable()
        fields = fields.split(':') if len(fields) > 0 else []
        minima = map(SpinDB.decode_query_field, minima.split(':')) if len(minima) > 0 else []
        maxima = map(SpinDB.decode_query_field, maxima.split(':')) if len(maxima) > 0 else []
        if verbose:
            print self.peer, 'map_cache_query(',fields,',',minima,',',maxima,')'
        region = map_regions.get(region_id, None)
        if region:
            ret = region.query(fields, minima, maxima, max_ret, updated_since)
        else:
            ret = []
        json_ret = json_dumps_compact(ret)
        if len(json_ret) > SpinDB.MSG_LIMIT:
            self.long_result = json_ret
            long_len = len(self.long_result)
            json_ret = ''
        else:
            long_len = 0
        return {'result':json_ret, 'db_time': db_time, 'long_len': long_len}
    def map_cache_population_query(self, fields, minima, maxima):
        self.check_readable()
        fields = fields.split(':') if len(fields) > 0 else []
        minima = map(SpinDB.decode_query_field, minima.split(':')) if len(minima) > 0 else []
        maxima = map(SpinDB.decode_query_field, maxima.split(':')) if len(maxima) > 0 else []
        ret = dict([(id, len(region.query(fields, minima, maxima, -1, -1))) for id, region in map_regions.iteritems()])
        json_ret = json_dumps_compact(ret)
        if len(json_ret) > SpinDB.MSG_LIMIT:
            self.long_result = json_ret
            long_len = len(self.long_result)
            json_ret = ''
        else:
            long_len = 0
        return {'result':json_ret, 'long_len': long_len}
    def map_cache_occupancy_check(self, region_id, coordlist):
        coordlist = SpinJSON.loads(coordlist)
        region = map_regions.get(region_id, None)
        if region:
            blocked = region.occupancy_check(coordlist)
        else:
            blocked = True
        return {'blocked':blocked}
    SpinDB.CMD['authenticate'].responder(authenticate)
    SpinDB.CMD['get_user_id_range'].responder(get_user_id_range)
    SpinDB.CMD['facebook_id_lookup_single'].responder(facebook_id_lookup_single)
    SpinDB.CMD['facebook_id_lookup_batch'].responder(facebook_id_lookup_batch)
    SpinDB.CMD['lock_release'].responder(lock_release)
    SpinDB.CMD['lock_get_state_batch'].responder(lock_get_state_batch)
    SpinDB.CMD['lock_keepalive_batch'].responder(lock_keepalive_batch)
    SpinDB.CMD['lock_acquire_login'].responder(lock_acquire_login)
    SpinDB.CMD['lock_acquire_attack'].responder(lock_acquire_attack)
    SpinDB.CMD['msg_send'].responder(msg_send)
    SpinDB.CMD['msg_recv'].responder(msg_recv)
    SpinDB.CMD['msg_ack'].responder(msg_ack)
    SpinDB.CMD['player_cache_query'].responder(player_cache_query)
    SpinDB.CMD['get_long_result'].responder(get_long_result)
    SpinDB.CMD['player_cache_update'].responder(player_cache_update)
    SpinDB.CMD['player_cache_lookup_batch'].responder(player_cache_lookup_batch)
    SpinDB.CMD['player_cache_get_scores'].responder(player_cache_get_scores)
    SpinDB.CMD['player_cache_get_leaders'].responder(player_cache_get_leaders)
    SpinDB.CMD['abtest_join_cohorts'].responder(abtest_join_cohorts)
    SpinDB.CMD['map_region_create'].responder(map_region_create)
    SpinDB.CMD['map_region_drop'].responder(map_region_drop)
    SpinDB.CMD['map_cache_update'].responder(map_cache_update)
    SpinDB.CMD['map_cache_query'].responder(map_cache_query)
    SpinDB.CMD['map_cache_population_query'].responder(map_cache_population_query)
    SpinDB.CMD['map_cache_occupancy_check'].responder(map_cache_occupancy_check)

    def same_peer_as(self, other):
        return (other and self.peer_identity and other.peer_identity and self.peer_identity == other.peer_identity)

    def __repr__(self):
        return str(self.peer_identity) + ' ' + str(self.peer)
    def __str__(self):
        return str(self.peer_identity) + ' ' + str(self.peer)

def init_tables():
    global facebook_id_table
    facebook_id_table = FacebookIDTable()
    global message_table
    message_table = MessageTable()
    global abtest_table
    abtest_table = ABTestTable()
    global map_regions
    map_regions = {}
    for filename in glob.glob(os.path.join(db_db_dir, 'map_region_*.txt')):
        basename = os.path.basename(filename)
        region_id = re.compile('map_region_(.+).txt').search(basename).group(1)
        map_regions[region_id] = MapCache(region_id)
    global player_cache
    player_cache = PlayerCache()
    global lock_table
    lock_table = LockTable()

def flush_all():
    facebook_id_table.flush()
    for region in map_regions.itervalues(): region.flush()
    player_cache.flush()
    message_table.flush()
    abtest_table.flush()

class AsyncFlusher (object):
    def __init__(self, kind, table):
        self.kind = kind
        self.table = table
        self.last_flush_time = db_time
        self.flush_task = None
    def check(self):
        if (db_time - self.last_flush_time) >= SpinConfig.config['dbserver'].get(self.kind+'_flush_interval', 3600):
            self.last_flush_time = db_time
            if self.flush_task is not None:
                exception_log.event(db_time, 'async %s flush fell behind with %d keys to go! flushing synchronously...' % \
                                    (self.kind, self.table.async_flush_keys_to_go()))
                self.flush_step(finish = True)
            self.flush_task = task.LoopingCall(self.flush_step)
            self.flush_task.start(SpinConfig.config['dbserver'].get(self.kind+'_flush_step_interval', 0.1), now = False)
    def flush_step(self, finish = False):
        # we can flush about 10,000 keys/sec at full speed, so 300 keys is about a 30ms delay every time this runs
        nkeys = -1 if finish else SpinConfig.config['dbserver'].get(self.kind+'_flush_keys_per_step', 300)
        done = self.table.async_flush_step(nkeys)
        if done:
            self.flush_task.stop()
            self.flush_task = None


class BGTask:
    def __init__(self):
        self.bg_task_interval = -1
        self.last_map_cache_flush = db_time
        self.last_facebook_id_table_flush = db_time
        self.last_abtest_table_flush = db_time
        self.player_cache_flusher = AsyncFlusher('player_cache', player_cache)
        self.message_table_flusher = AsyncFlusher('message_table', message_table)
        self.facebook_id_table_flusher = AsyncFlusher('facebook_id_table', facebook_id_table)
        self.bg_task = task.LoopingCall(self.func)
        self.reset_interval()

    def reset_interval(self):
        new_interval = SpinConfig.config['dbserver'].get('bg_task_interval', 30)
        if new_interval == self.bg_task_interval:
            return

        if self.bg_task_interval > 0:
            self.bg_task.stop()
        self.bg_task_interval = new_interval
        self.bg_task.start(self.bg_task_interval, now = False)

    def func(self):
        global db_time
        db_time = int(time.time())
        print 'BGTask running'
        try:
            # same for map_cache
            if (db_time - self.last_map_cache_flush) >= SpinConfig.config['dbserver'].get('map_cache_flush_interval', 3700):
                self.last_map_cache_flush = db_time
                for region in map_regions.itervalues(): region.flush()

            # abtest table flushes more frequently
            if (db_time - self.last_abtest_table_flush) >= SpinConfig.config['dbserver'].get('abtest_table_flush_interval', 600):
                self.last_abtest_table_flush = db_time
                abtest_table.flush()

            self.facebook_id_table_flusher.check()
            self.player_cache_flusher.check()
            self.message_table_flusher.check()

        except:
            exception_log.event(db_time, 'dbserver bgfunc Exception: '+ traceback.format_exc())

def do_main():
    for d in [db_log_dir, db_db_dir]:
        if not os.path.exists(d):
            os.mkdir(d)

    pf = Factory()
    pf.protocol = DBProtocolHandlers
    myhost = SpinConfig.config['dbserver'].get('db_listen_host','localhost')
    myport = SpinConfig.config['dbserver']['db_port']
    reactor.listenTCP(myport, pf, interface=myhost)

    global exception_log
    exception_log = SpinLog.DailyRawLog(db_log_dir+'/', '-exceptions.txt')
    global raw_log
    raw_log = SpinLog.DailyRawLog(db_log_dir+'/', '-dbserver.txt', buffer = (not verbose))
    global trace_log
    trace_log = SpinLog.DailyRawLog(db_log_dir+'/', '-traces.txt')

    init_tables()

    global bgtask
    bgtask = BGTask()

    # dump info to stdout on SIGUSR1
    def handle_SIGUSR1(signum, frm):
        global db_time
        db_time = int(time.time())
        trace_log.event(db_time, ''.join(traceback.format_stack(frm)))
#        lock_table.dump()
#        player_cache.dump_indices()
#        sys.stdout.flush()

    signal.signal(signal.SIGUSR1, handle_SIGUSR1)

    # SIGHUP forces a spin_config reload
    def handle_SIGHUP(signum, frm):
        global db_time, bgtask
        db_time = int(time.time())
        try:
            reload_spin_config()
            #flush_all()
            bgtask.reset_interval()
        except:
            exception_log.event(db_time, 'dbserver SIGHUP Exception: ' + traceback.format_exc())
    signal.signal(signal.SIGHUP, handle_SIGHUP)

    print 'DB server up and running on %s:%d' % (myhost, myport)

    if db_daemonize:
        Daemonize.daemonize()

        # update PID file with new PID
        open(db_pidfile, 'w').write('%d\n' % os.getpid())

        # turn on Twisted logging
        def log_exceptions(eventDict):
            if eventDict['isError']:
                if 'failure' in eventDict:
                    text = ((eventDict.get('why') or 'Unhandled Error')
                            + '\n' + eventDict['failure'].getTraceback())
                else:
                    text = ' '.join([str(m) for m in eventDict['message']])
                exception_log.event(db_time, text)
        def log_raw(eventDict):
            text = log.textFromEventDict(eventDict)
            if text is None:
                return
            raw_log.event(db_time, text)

        log.startLoggingWithObserver(log_raw)
        log.addObserver(log_exceptions)

    reactor.run()
    flush_all()

def main():
    if os.path.exists(db_pidfile):
        print 'DB is already running (%s).' % db_pidfile
        sys.exit(1)

    # create PID file
    open(db_pidfile, 'w').write('%d\n' % os.getpid())
    try:
        do_main()
    finally:
        # remove PID file
        os.unlink(db_pidfile)

if __name__ == '__main__':
    main()
