#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# *** OBSOLETE ** due to bit-rot, no longer matches server code

# This tool queries the dbserver player cache using the same algorithm
# as the game server uses for matchmaking. Useful for testing the
# matchmaking system.

try:
    import simplejson as json
except:
    import json
import SpinNoSQL
import SpinConfig
import sys, string
import time

gamedata = json.load(open(SpinConfig.gamedata_filename()))
client = None

def get_min_attackable_level(my_level):
    if type(gamedata['max_pvp_level_gap']) is list:
        ind = min(max(my_level-1, 0), len(gamedata['max_pvp_level_gap'])-1)
        max_gap = gamedata['max_pvp_level_gap'][ind]
    else:
        max_gap = gamedata['max_pvp_level_gap']

    return max(my_level - max_gap, 0)

def check_user(user_id):
    me = client.player_cache_lookup_batch([user_id])[0]

    print 'ME:', me

    pvp_rating = me.get('pvp_rating', 0)

    max_num = gamedata['matchmaking']['max_stranger_rivals']
    min_rating = pvp_rating + gamedata['matchmaking']['stranger_range'][0]
    max_rating = pvp_rating + gamedata['matchmaking']['stranger_range'][1]

    min_rating = max(min_rating, 0.01)
    max_rating = max(max_rating, gamedata['matchmaking']['new_user_rating'] + gamedata['matchmaking']['stranger_range'][1])

    min_level = get_min_attackable_level(me.get('player_level',1))
    max_level = 9999
    if min_level < 0:
        min_level = 0

    rivals = client.player_cache_query([['pvp_rating', min_rating, max_rating],
                                        ['player_level', min_level, max_level],
                                        ['lootable_buildings', 1, 9999],
                                        ['tutorial_complete', 0.1, 9999],
                                        ['protection_end_time', -100, server_time],
                                        ], max_num+1) # +1 for self
    rivals = filter(lambda x: x != user_id, rivals)

    add_props = client.player_cache_lookup_batch(rivals)
    temp = []
    for i in range(len(rivals)):
        props = add_props[i]
        props['user_id'] = rivals[i]
        temp.append(props)
    rivals = temp
    print 'query returned', len(rivals)

    rivals = filter(lambda props: props.get('tutorial_complete', False), rivals)
    print 'tutorial filter', len(rivals)

    rivals = filter(lambda props: props.get('protection_end_time',-1) <= server_time, rivals)
    print 'protection timer filter', len(rivals)

    rivals = filter(lambda props: props.get('lootable_buildings',-1) > 0, rivals)
    print 'lootable filter', len(rivals)

    rivals = filter(lambda props: props.get('player_level', -1) >= min_level, rivals)
    print 'level filter', len(rivals)

    print 'FINAL', string.join(map(lambda x: repr(x), rivals), '\n')

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
