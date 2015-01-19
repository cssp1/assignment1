#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to fix SpinNoSQL message_table "recipient" from string to int

import SpinConfig
import SpinNoSQL
import sys, time, getopt

time_now = int(time.time())

if __name__ == '__main__':
    yes_i_am_sure = False
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['yes-i-am-sure'])
    for key, val in opts:
        if key == '--yes-i-am-sure': yes_i_am_sure = True

    if not yes_i_am_sure:
        print '--yes-i-am-sure flag to confirm.'
        sys.exit(1)

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    tbl = nosql_client.db[nosql_client.dbconfig['table_prefix']+'message_table']

    for msg in tbl.find({'recipient':{'$type':2}}, {'type':1, 'recipient':1}):
        if msg['type'] in ('mail', 'i_attacked_you', 'FBRTAPI_payment'):
            print 'KEEPING', msg['_id'], msg['type']
            tbl.update({'_id':msg['_id']}, {'$set':{'recipient':int(msg['recipient'])}})
        else:
            print 'REMOVING', msg['_id'], msg['type']
            tbl.remove({'_id':msg['_id']})

    print 'DONE'
