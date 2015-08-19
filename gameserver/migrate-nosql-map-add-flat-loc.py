#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to add base_map_loc_flat field to existing map features

import SpinConfig
import SpinNoSQL
import sys, time

time_now = int(time.time())

if __name__ == '__main__':
    region_id = sys.argv[1]
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    converted = 0

    for raw in nosql_client.region_table(region_id, 'map').find({}, {'_id':1,'base_map_loc':1,'base_map_loc_flat':1}):
        if ('base_map_loc' in raw) and ('base_map_loc_flat' not in raw):
            nosql_client.region_table(region_id, 'map').update({'_id':raw['_id']}, {'$set':{'base_map_loc_flat':nosql_client.flatten_map_loc(raw['base_map_loc'])}}, w=1)
            converted += 1
            sys.stderr.write('%s: %4d... %s\n' % (region_id, converted, raw['_id']))

    sys.stderr.write('added base_map_loc_flat to %d features\n' % (converted))
