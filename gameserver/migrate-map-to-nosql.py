#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert dbserver map_cache to SpinNoSQL map table

import SpinConfig
import SpinJSON
import SpinNoSQL
import sys, time

time_now = int(time.time())

if __name__ == '__main__':
    region_id = sys.argv[1]
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    converted = 0

    old_map = SpinJSON.load(open('db/map_region_%s.txt' % region_id))
    total = len(old_map)

    for base_id, props in old_map.iteritems():
        if 'base_id' in props:
            assert props['base_id'] == base_id
            del props['base_id']
        props['_id'] = str(base_id)

        for k in props.keys():
            if k.startswith('LOCK_') or k == 'base_generation':
                del props[k]

        if 'base_map_loc' in props:
            props['base_map_loc_flat'] = nosql_client.flatten_map_loc(props['base_map_loc'])

        expired = (props.get('base_expire_time',-1) > 0 and props['base_expire_time'] < time_now)
        if not expired:
            nosql_client.region_table(region_id, 'map').save(props, w=0)

        converted += 1
        sys.stderr.write('%s: %4d/%4d... %s%s\n' % (region_id, converted, total, base_id, ' (expired)' if expired else ''))


    sys.stderr.write('converted %d features\n' % (converted))
