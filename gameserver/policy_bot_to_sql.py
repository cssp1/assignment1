#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump PolicyBot log to SQL for analytics use

import sys, getopt, time
import SpinConfig
import SpinNoSQL
import SpinETL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())

def policy_bot_schema(sql_util):
    return { 'fields': [('time', 'INT8 NOT NULL'),
                        ('user_id', 'INT4'),
                        ('event_name', 'VARCHAR(128) NOT NULL'),
                        ('reason', 'VARCHAR(64)'),
                        ('repeat_offender', 'INT4'),
                        ('master_user_id', 'INT4'),
                        ('old_region', 'VARCHAR(64)'),
                        ('new_region', 'VARCHAR(64)'),
                        ],
             'indices': {'by_time': {'keys': [('time','ASC')]}},
    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 100
    verbose = True
    dry_run = False
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True


    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('policy_bot_to_sql-%s' % game_id):

        policy_bot_table = cfg['table_prefix']+game_id+'_policy_bot'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, policy_bot_table, policy_bot_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(policy_bot_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        total = 0
        batch = 0

        for row in SpinETL.iterate_from_mongodb(game_id, 'log_policy_bot', start_time, end_time):
            if row['event_name'] in ('7300_policy_bot_run_started','7302_policy_bot_run_finished'): continue

            keyvals = []
            for fn in ('time', 'user_id', 'event_name', 'reason', 'repeat_offender', 'old_region', 'new_region'):
                if fn in row:
                    keyvals.append((fn, row[fn]))

            if 'master_id' in row:
                keyvals.append(('master_user_id', row['master_id']))

            sql_util.do_insert(cur, policy_bot_table, keyvals)

            batch += 1
            total += 1
            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted'

        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', policy_bot_table
            cur.execute("DELETE FROM "+sql_util.sym(policy_bot_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', policy_bot_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(policy_bot_table))
            con.commit()
