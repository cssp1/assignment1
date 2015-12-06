#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# *** OBSOLETE ** due to bit-rot, no longer matches server code

# This tool queries the dbserver player cache using the same algorithm
# as the game server uses for ladder PvP matchmaking.

import SpinJSON
import SpinNoSQL
import SpinConfig
import sys
import time

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
client = None

def get_min_attackable_level(my_level):
    if type(gamedata['max_pvp_level_gap']) is list:
        ind = min(max(my_level-1, 0), len(gamedata['max_pvp_level_gap'])-1)
        max_gap = gamedata['max_pvp_level_gap'][ind]
    else:
        max_gap = gamedata['max_pvp_level_gap']

    return max(my_level - max_gap, 0)

def do_query(query, max_num):
    start_time = time.time()
    rivals = client.player_cache_query(query, max_num)
    end_time = time.time()
    print 'query time: %4.0fms   %7d matches' % ((end_time-start_time)*1000.0, len(rivals))
    return rivals

def check_user(user_id):
    me = client.player_cache_lookup_batch([user_id])[0]

    print 'ME:', me

    #trophy_field = 'trophies_pvp_wk47'

    trophy_range = [1,100] # [me.get(trophy_field,0) - 25, me.get(trophy_field,0) + 100]

    query =  [
              ['ladder_player', 1,1], # eventually move to end of query once it goes on globally
              ['player_level',
               get_min_attackable_level(me['player_level']),
               9999 if trophy_range else me['player_level'] + gamedata['matchmaking']['ladder_match_up_levels']
               ],
              ['base_damage', 0, 0.499], # note: missing (-1) data is treated as unsuitable
              ['lootable_buildings', 1, 9999],
              ['tutorial_complete', 1,1],
              ['protection_end_time', -100, server_time],

              ['trophies_pvp_wk47', trophy_range[0], trophy_range[1]],

              ['LOCK_STATE', -1, 0], # not locked
              ['isolate_pvp', -999, 0.1],
              ['user_id', user_id, user_id, '!in'] # don't fight yourself
              ]

    print 'QUERY', query
    max_num = gamedata['matchmaking']['ladder_match_pool_size']

    rivals = do_query(query, max_num)
    print 'RIVALS', rivals

    if 1:
        print 'BREAKDOWN:'
        for filter in query:
            if filter[0] in ('LOCK_STATE', 'isolate_pvp', 'user_id', 'tutorial_complete', 'protection_end_time'): continue # these are always "accept almost all"
            new_query = [filter]
            print 'FILTER: %-50s' % repr(filter),
            do_query(new_query, -1)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print 'usage: %s user_id user_id ...' % sys.argv[0]
        sys.exit(1)

    user_ids = map(int, sys.argv[1:])
    server_time = int(time.time())

    client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    client.set_time(server_time)

    for uid in user_ids:
        check_user(uid)
