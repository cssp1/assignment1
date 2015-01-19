#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump DAU counts from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import MySQLdb
import SpinSQLUtil

gamedata = None
time_now = int(time.time())

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', [])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    sql_util = SpinSQLUtil.MySQLUtil()

    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    dau_table = cfg['table_prefix']+game_id+'_dau'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor()
    sql_util.ensure_table(cur, dau_table, {
        'fields': [('day_start', 'INT8 NOT NULL'),
                   ('country_tier', 'CHAR(1) NOT NULL'),
                   ('dau', 'INT8 NOT NULL'),
                   ('playtime', 'INT8 NOT NULL')],
        'indices': {'by_day_and_tier': {'unique':True, 'keys': [('day_start','ASC'),('country_tier','ASC')]}}
        })
    con.commit()

    cur = con.cursor()
    for tbl, timestamp in nosql_client.dau_tables():
        by_tier = tbl.aggregate([{'$group':{'_id':'$tier',
                                            'dau':{'$sum':1},
                                            'playtime':{'$sum':'$playtime'}}
                                  }])['result']

        for row in by_tier:
            cur.execute('INSERT INTO '+sql_util.sym(dau_table)+' (day_start, country_tier, dau, playtime) VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE dau = %s, playtime = %s',
                        [timestamp, str(row['_id']), row['dau'], row['playtime'], row['dau'], row['playtime']])

    con.commit()

