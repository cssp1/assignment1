#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert dbserver player_cache to SpinNoSQL
# OBSOLETE

import SpinConfig
import SpinJSON
import SpinNoSQL
import sys, time, getopt, re

time_now = int(time.time())
SCORE_RE = re.compile('(.+)_(wk|s)([0-9]+)$')

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
cur_season = -1
cur_week = -1

if __name__ == '__main__':
    yes_i_am_sure = False
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['yes-i-am-sure'])
    for key, val in opts:
        if key == '--yes-i-am-sure': yes_i_am_sure = True

    if not yes_i_am_sure:
        print 'DESTROYS data in SpinNoSQL, use --yes-i-am-sure flag to confirm.'
        print 'AND MAKE SURE DBSERVER IS NOT CURRENTLY RUNNING!'
        sys.exit(1)

    old_cache = SpinJSON.load(open('db/player_cache.txt'))

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    nosql_client._table('player_cache').drop()

    count = 0

    for suser_id, data in old_cache.iteritems():
        if (count%100) == 0:
            print 'migrating %6.2f%%... player %s' % (100.0*(float(count)/len(old_cache)), suser_id)
        count += 1
        props = {}
        score_updates = []

        for k, v in data.iteritems():
            if k.startswith('LOCK_'): continue # don't store bad LOCK fields

            # divert scores to player_scores table
            match = SCORE_RE.match(k)
            if match:
                gr = match.groups()
                field, freq, period =  (gr[0], {'wk':'week','s':'season'}[gr[1]], int(gr[2]))
                if freq == 'week' and (cur_week < 0 or period < cur_week-2): continue
                if freq == 'season' and (cur_season < 0 or period < cur_season): continue
                score_updates.append(((field,freq,period), v))
                continue
            if type(v) is bool: v = int(v) # don't store booleans
            props[k] = v

        nosql_client.player_cache_update(int(suser_id), props, overwrite = True)
        if score_updates:
            nosql_client.update_player_scores(int(suser_id), score_updates)
