#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_client_trouble" and abbreviated "log_client_exceptions" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinETL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())
DETAIL_LEN = 64 # truncate long "method" and "reason" args
client_trouble_schema = {
    'fields': [('time', 'INT8 NOT NULL'),
               ('event_name', 'VARCHAR(128) NOT NULL'),
               ('user_id', 'INT4'),
               ('frame_platform', 'CHAR(2)'),
               ('country', 'VARCHAR(2)'),
               ('country_tier', 'CHAR(1)'),
               ('ip', 'VARCHAR(16)'),
               ('browser_name', 'VARCHAR(16)'),
               ('browser_os', 'VARCHAR(16)'),
               ('browser_version', 'FLOAT4'),
               ('connection', 'VARCHAR(16)'),
               ('serial','INT4'),
               ('len','INT4'),
               ('elapsed','FLOAT4'),
               ('since_connect','FLOAT4'),
               ('since_pageload','FLOAT4'),
               ('method', 'VARCHAR(%d)' % DETAIL_LEN),
               ('reason', 'VARCHAR(%d)' % DETAIL_LEN),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }

def client_trouble_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL'),
                       ('frame_platform', 'CHAR(2)'),
                       ('country_tier', 'CHAR(1)'),
                       ('event_name', 'VARCHAR(128) NOT NULL'),
                       ('browser_name', 'VARCHAR(16)'),
                       ('browser_os', 'VARCHAR(16)'),
                       ('browser_version', 'FLOAT4'),
                       ('connection', 'VARCHAR(16)'),
                       ('n_events', 'INT8'),
                       ('unique_players', 'INT8'),
                       ('unique_ips', 'INT8'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }


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

    with SpinSingletonProcess.SingletonProcess('client_trouble_to_sql-%s' % game_id):

        sql_util = SpinSQLUtil.MySQLUtil()
        if not verbose: sql_util.disable_warnings()

        cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
        con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        client_trouble_table = cfg['table_prefix']+game_id+'_client_trouble'
        client_trouble_daily_summary_table = cfg['table_prefix']+game_id+'_client_trouble_daily_summary'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, client_trouble_table, client_trouble_schema)
        sql_util.ensure_table(cur, client_trouble_daily_summary_table, client_trouble_summary_schema(sql_util, 'day'))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 600  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(client_trouble_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        for source_table in ('log_client_trouble', 'log_client_exceptions'):
            for row in SpinETL.iterate_from_mongodb(game_id, source_table, start_time, end_time):

                # determine country and country_tier
                country = '??'
                country_tier = None
                if row.get('country',None) and row['country'] != 'unknown':
                    country = row['country']
                if 'country_tier' in row:
                    country_tier = str(row['country_tier'])
                elif country:
                    country_tier = str(SpinConfig.country_tier_map.get(country,4))

                keyvals = [('time',row['time']),
                           ('event_name',row['event_name']),
                           ('country',country),
                           ('country_tier',country_tier)]

                # shorten method/reason
                for DETAIL in ('method','reason'):
                    v = row.get(DETAIL, None)
                    if v:
                        if len(v) > DETAIL_LEN-3:
                            v = v[0:DETAIL_LEN-3]+'...'
                        keyvals.append((DETAIL,v))

                for FIELD in ('user_id', 'frame_platform', 'ip', 'browser_name', 'browser_OS', 'browser_version', 'connection',
                              'serial', 'len', 'elapsed', 'since_connect', 'since_pageload'):
                    if FIELD in row:
                        keyvals.append((FIELD.lower(), row[FIELD])) # NOTE: browser_OS->browser_os

                sql_util.do_insert(cur, client_trouble_table, keyvals)

                batch += 1
                total += 1
                affected_days.add(86400*(row['time']//86400))
                if commit_interval > 0 and batch >= commit_interval:
                    batch = 0
                    con.commit()
                    if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted'

        # update summary
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(client_trouble_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            client_trouble_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            client_trouble_range = None

        def update_client_trouble_summary(cur, table, interval, day_start, dt):
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT %s AS "+interval+"," + \
                        "       frame_platform AS frame_platform," + \
                        "       country_tier AS country_tier," + \
                        "       event_name AS event_name," + \
                        "       browser_name AS browser_name," + \
                        "       browser_os AS browser_os," + \
                        "       browser_version AS browser_version," + \
                        "       connection AS connection," + \
                        "       COUNT(1) AS n_events," + \
                        "       COUNT(DISTINCT(user_id)) AS unique_players, " + \
                        "       COUNT(DISTINCT(ip)) AS unique_ips " + \
                        "FROM " + sql_util.sym(client_trouble_table) + " " + \
                        "WHERE time >= %s AND time < %s " + \
                        "GROUP BY frame_platform, country_tier, event_name, browser_name, browser_os, browser_version, connection " + \
                        "ORDER BY NULL",
                        [day_start, day_start, day_start+dt])

        SpinETL.update_summary(sql_util, con, cur, client_trouble_daily_summary_table, affected_days, client_trouble_range, 'day', 86400,
                               verbose = verbose, resummarize_tail = 86400, execute_func = update_client_trouble_summary)

        if do_prune:
            # drop old data
            KEEP_DAYS = 30
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', client_trouble_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(client_trouble_table)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', client_trouble_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(client_trouble_table))
            con.commit()
