#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# query for player population of all map regions

import SpinConfig
import SpinNoSQL

def print_population(nosql_client, region_id):
    base_types = ['home','quarry','hive','raid','squad']
    pops_by_type = nosql_client.count_map_features_grouped_by_type(region_id, base_types)
    if pops_by_type.get('home', 0) < 1:
        return # skip regions with no players
    print '%-16s ' % region_id + ' '.join(['%s: %-4d' % (btype, pops_by_type.get(btype,0)) for btype in base_types])

gamedata = {
    'regions': SpinConfig.load(SpinConfig.gamedata_component_filename('regions.json'))
    }

client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

for region_id in sorted(gamedata['regions'].keys()):
    print_population(client, region_id)
