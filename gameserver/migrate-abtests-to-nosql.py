#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# one-time migration script to convert dbserver abtest table to SpinNoSQL

import SpinConfig
import SpinJSON
import SpinNoSQL
import sys, time

time_now = int(time.time())

if __name__ == '__main__':
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    converted = 0

    old_table = SpinJSON.load(open('db/abtest_table.txt'))

    for testname, old_data in old_table.iteritems():
        for cohortname, cohortdata in old_data.iteritems():
            N = cohortdata.get('N',0)
            key = testname+':'+cohortname
            nosql_client.abtest_table().replace_one({'_id':key}, {'_id':key, 'name':testname, 'cohort':cohortname, 'N':N}, upsert=True)
            converted += 1
            sys.stderr.write('%4d... %s N=%d\n' % (converted, key, N))

    sys.stderr.write('converted %d cohorts\n' % (converted))
