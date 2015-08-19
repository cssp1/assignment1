#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_achievements" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinETL
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())

def achievements_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('event_name', 'VARCHAR(128) NOT NULL'),
                       ('name', 'VARCHAR(64) NOT NULL'),
                       ],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }
def achievements_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                       sql_util.summary_out_dimensions() + \
                      [('event_name', 'VARCHAR(128) NOT NULL'),
                       ('name', 'VARCHAR(64) NOT NULL'),
                       ('n_events', 'INT4'),
                       ('unique_players', 'INT4')
                       ],
            'indices': {'by_'+interval: {'keys': [(interval,'ASC')]}}
            }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
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

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('achievements_to_sql-%s' % game_id):

        achievements_table = cfg['table_prefix']+game_id+'_achievements'
        achievements_daily_summary_table = cfg['table_prefix']+game_id+'_achievements_daily_summary'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, achievements_table, achievements_schema(sql_util))
        sql_util.ensure_table(cur, achievements_daily_summary_table, achievements_summary_schema(sql_util, 'day'))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(achievements_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        qs = {'time':{'$gt':start_time, '$lt':end_time}}

        for row in nosql_client.log_buffer_table('log_achievements').find(qs):
            if ('sum' in row) and row['sum'].get('developer',False): continue # skip events by developers

            keyvals = [('time',row['time']),
                       ('user_id',row['user_id']),
                       ('event_name', row['event_name']),
                       ('name', row.get('name', None))]
            if 'sum' in row:
                keyvals += sql_util.parse_brief_summary(row['sum'])

            if not dry_run:
                sql_util.do_insert(cur, achievements_table, keyvals)
            else:
                print keyvals

            batch += 1
            total += 1
            affected_days.add(86400*(row['time']//86400))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

        # update summary
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(achievements_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            achievements_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            achievements_range = None

        def update_achievements_summary(cur, table, interval, day_start, dt):
            cur.execute("INSERT INTO "+sql_util.sym(achievements_daily_summary_table) + \
                        "SELECT %s AS "+interval+"," + \
                        "       frame_platform AS frame_platform," + \
                        "       country_tier AS country_tier," + \
                        "       townhall_level AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," + \
                        "       event_name AS event_name," + \
                        "       name AS name," + \
                        "       COUNT(1) AS n_events," + \
                        "       COUNT(DISTINCT(user_id)) AS unique_players " + \
                        "FROM " + sql_util.sym(achievements_table) + " dp " + \
                        "WHERE time >= %s AND time < %s " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, event_name, name ORDER BY NULL",
                        [day_start, day_start, day_start+dt])

        SpinETL.update_summary(sql_util, con, cur, achievements_daily_summary_table, affected_days, achievements_range, 'day', 86400,
                               verbose = verbose, resummarize_tail = 86400, execute_func = update_achievements_summary)

        if (not dry_run) and do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            for TABLE in (achievements_table,):
                if verbose: print 'pruning', TABLE
                cur.execute("DELETE FROM "+sql_util.sym(TABLE)+" WHERE time < %s", old_limit)
                if do_optimize:
                    if verbose: print 'optimizing', TABLE
                    cur.execute("OPTIMIZE TABLE "+sql_util.sym(TABLE))
                con.commit()
