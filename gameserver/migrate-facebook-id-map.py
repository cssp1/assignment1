#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert dbserver facebook_id_map to SpinNoSQL

import SpinConfig
import SpinJSON
import SpinNoSQL
import sys, time, getopt

time_now = int(time.time())

if __name__ == '__main__':
    yes_i_am_sure = False
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['yes-i-am-sure'])
    for key, val in opts:
        if key == '--yes-i-am-sure': yes_i_am_sure = True

    if not yes_i_am_sure:
        print 'DESTROYS data in SpinNoSQL, use --yes-i-am-sure flag to confirm.'
        print 'AND MAKE SURE DBSERVER IS NOT CURRENTLY RUNNING!'
        sys.exit(1)

    old_map = SpinJSON.load(open('db/facebook_id_map.txt'))

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    nosql_client._table('facebook_id_map').drop()

    for fbid, user_id in old_map.iteritems():
        nosql_client._table('facebook_id_map').replace_one({'_id':str(fbid)}, {'_id':str(fbid), 'user_id':user_id}, upsert=True)

    nosql_client.facebook_id_table() # create indexes
