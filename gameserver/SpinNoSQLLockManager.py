#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# layers on top of SpinNoSQL to help keep track of locks taken

class LockManager(object):
    SETUP_LOCK_OWNER = 667 # fake user_id we will use to take locks with
    BEING_ATTACKED = 2 # lock state constant

    def __init__(self, nosql_client, dry_run = False):
        self.nosql_client = nosql_client
        self.dry_run = dry_run
        self.locks = {}
        self.player_locks = {}
        self.verbose = 0
    def acquire(self, region_id, base_id):
        lock = (region_id, base_id)
        if self.dry_run: return True
        if self.nosql_client.map_feature_lock_acquire(region_id, base_id, self.SETUP_LOCK_OWNER, do_hook = False) != self.BEING_ATTACKED:
            if self.verbose: print 'ACQUIRE (fail) ', lock
            return False
        if self.verbose: print 'ACQUIRE', lock
        self.locks[lock] = 1
        return True
    def create(self, region_id, base_id):
        lock = (region_id, base_id)
        if self.dry_run: return
        if self.verbose: print 'CREATE', lock
        self.locks[lock] = 1
    def acquire_player(self, user_id):
        if self.dry_run: return True
        if self.nosql_client.player_lock_acquire_attack(user_id, -1, owner_id = self.SETUP_LOCK_OWNER) != self.BEING_ATTACKED:
            if self.verbose: print 'ACQUIRE PLAYER (fail)', user_id
            return False
        if self.verbose: print 'ACQUIRE PLAYER', user_id
        self.player_locks[user_id] = 1
        return True
    def forget(self, region_id, base_id):
        if self.dry_run: return
        lock = (region_id, base_id)
        del self.locks[lock]
    def release(self, region_id, base_id, base_generation = -1):
        if self.dry_run: return
        lock = (region_id, base_id)
        del self.locks[lock]
        if self.verbose: print 'RELEASE', lock
        self.nosql_client.map_feature_lock_release(region_id, base_id, self.SETUP_LOCK_OWNER, generation = base_generation, do_hook = False)
    def release_player(self, user_id, generation = -1):
        if self.dry_run: return
        del self.player_locks[user_id]
        if self.verbose: print 'RELEASE PLAYER', user_id
        self.nosql_client.player_lock_release(user_id, generation, self.BEING_ATTACKED, expected_owner_id = self.SETUP_LOCK_OWNER)
    def release_all(self):
        for lock in self.locks.keys():
            self.release(lock[0], lock[1])
        for user_id in self.player_locks.keys():
            self.release_player(user_id)

    # context pattern
    def __enter__(self): return self
    def __exit__(self, type, value, traceback):
        self.release_all()
