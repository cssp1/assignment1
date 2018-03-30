#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# low-latency SQL table just for holding user/test relationship state
# updated from metrics log events.
# (this is redundant with the main upcache table - which is to be considered authoritave -
# but this special-purpose table is smaller and updated more frequently)

import sys, getopt, time
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinETL
import SpinSingletonProcess
import SpinMySQLdb

abtests_schema = {
    'fields': [('join_time', 'INT8 NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('test_name', 'VARCHAR(64) NOT NULL'),
               ('group_name', 'VARCHAR(64) NOT NULL')],
    # note: indexed fields need to be NOT NULL or else ON DUPLICATE KEY UPDATE will not work
    'indices': {'master': {'keys': [('test_name','ASC'),('user_id','ASC')], 'unique': True},
                'by_join_time': {'keys': [('join_time','ASC')]}}
    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    cur = con.cursor(SpinMySQLdb.cursors.DictCursor)

    time_now = int(time.time())

    with SpinSingletonProcess.SingletonProcess('abtests_to_sql-%s' % game_id):

        abtests_table = cfg['table_prefix']+game_id+'_abtests'
        if not dry_run:
            sql_util.ensure_table(cur, abtests_table, abtests_schema)
            con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT join_time FROM "+sql_util.sym(abtests_table)+" ORDER BY join_time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows and rows[0]['join_time'] > 0:
            start_time = max(start_time, rows[0]['join_time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0

        for row in SpinETL.iterate_from_mongodb(game_id, 'log_metrics', start_time, end_time,
                                                query = {'event_name': '0800_abtest_joined'}):
            cur.execute("INSERT INTO "+sql_util.sym(abtests_table)+" (join_time,user_id,test_name,group_name) "+\
                        "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE join_time=%s, group_name=%s;",
                        (row['time'], row['user_id'], row['test_name'], row['group_name'], row['time'], row['group_name']))
            batch += 1
            total += 1
            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted'


