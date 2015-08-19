#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert dbserver message_table to SpinNoSQL

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

    old_map = SpinJSON.load(open('db/message_table.txt'))

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    nosql_client._table('message_table').drop()

    for srecipient, msg_list in old_map.iteritems():
        for msg in msg_list:
            msg['recipient'] = int(srecipient)
            if 'msg_id' in msg: del msg['msg_id']
            nosql_client._table('message_table').insert(msg)

    nosql_client.message_table() # create indexes
