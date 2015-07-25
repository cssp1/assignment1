#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_login_flow" from MongoDB to a MySQL database for analytics

import sys, os, time, getopt
import SpinConfig
import SpinSQLUtil
import SpinETL
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())
def login_flow_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4'),
               ('social_id', 'VARCHAR(128)'),
               ('event_name', 'VARCHAR(128) NOT NULL'),
               ('country', 'VARCHAR(2)'),
               ('country_tier', 'CHAR(1)'),
               ('ip', 'VARCHAR(16)'),
               ('browser_name', 'VARCHAR(16)'),
               ('browser_os', 'VARCHAR(16)'),
               ('browser_version', 'FLOAT4'),
               ('method', 'VARCHAR(128)'),
               ('splash_image', 'VARCHAR(128)'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }
#def login_flow_summary_schema(sql_util): return {
#    'fields': [('day', 'INT8 NOT NULL'),
#               ('event_name', 'VARCHAR(128) NOT NULL'),
#               ('count', 'INT4'),
#               ('unique_players', 'INT4')],
#    'indices': {'by_day': {'keys': [('day','ASC')]}}
#    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('login_flow_to_sql-%s' % game_id):

        login_flow_table = cfg['table_prefix']+game_id+'_login_flow'
        login_flow_summary_table = cfg['table_prefix']+game_id+'_login_flow_daily_summary'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, login_flow_table, login_flow_schema(sql_util))
    #    sql_util.ensure_table(cur, login_flow_summary_table, login_flow_summary_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(login_flow_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        for row in SpinETL.iterate_from_mongodb(game_id, 'log_login_flow', start_time, end_time):
            keyvals = [('time',row['time']),
                       ('event_name',row['event_name'])]

            if ('country' in row) and row['country'] == 'unknown':
                del row['country'] # do not record "unknown" countries

            if ('country_tier' not in row) and ('country' in row):
                row['country_tier'] = SpinConfig.country_tier_map.get(row['country'], 4)

            if ('splash_image' in row) and (not (row['splash_image'].startswith('#'))):
                row['splash_image'] = os.path.basename(row['splash_image'])

            for FIELD in ('user_id','social_id','country','country_tier','ip',
                          'browser_name','browser_os','browser_version','method',
                          'splash_image'):
                if FIELD in row:
                    keyvals.append((FIELD, row[FIELD]))

            sql_util.do_insert(cur, login_flow_table, keyvals)

            batch += 1
            total += 1
            affected_days.add(86400*(row['time']//86400))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

        # XXX no summary yet

        if do_prune:
            # drop old data
            KEEP_DAYS = 60
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', login_flow_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(login_flow_table)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', login_flow_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(login_flow_table))
            con.commit()
