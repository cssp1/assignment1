#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert dbserver abtest table to SpinNoSQL

import SpinConfig
import SpinJSON
import SpinNoSQL
import base64, lz4, SpinLZJB
import sys, time, getopt

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:b:', [])
    game_id = SpinConfig.game()
    batch_size = None
    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-b': batch_size = int(val)

    gamedata = {} # SpinJSON.load(open(SpinConfig.gamedata_filename()))
    gamedata['regions'] = SpinConfig.load(SpinConfig.gamedata_component_filename("regions.json", override_game_id = game_id), override_game_id = game_id)

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    TRIALS = 10
    region = None

    region_list = [name for name, data in sorted(gamedata['regions'].items()) if \
                   data.get('enable_map',1)]

    total_time = 0.0
    for region in region_list:
        start_time = time.time()

        db_time = -1
        result = list(nosql_client.get_map_features(region, updated_since = -1, batch_size = batch_size))
        for x in result:
            db_time = max(db_time, x.get('last_mtime',-1))

        if 1:
            z_result = base64.b64encode(bytes(lz4.compress(SpinJSON.dumps(result))))
        else:
            z_result = base64.b64encode(bytes(SpinLZJB.compress(SpinLZJB.string_to_bytes(SpinJSON.dumps(result)))))

        temp = (db_time, 'lz4', z_result)

        print region, len(result), db_time, len(z_result),

        end_time = time.time()
        total_time += end_time-start_time
        print '%.1f ms' % (1000*(end_time-start_time))
    print 'avg %.1f ms' % (1000*total_time/len(region_list))
