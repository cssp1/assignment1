#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_unit_donation" from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinETL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())
def unit_donation_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('event_name', 'VARCHAR(128) NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [('alliance_id', 'INT4'),
               ('recipient_id', 'INT4'),
               ('spec', 'VARCHAR(32)'),
               ('level', 'INT2'),
               ('stack', 'INT2'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }
def unit_donation_summary_schema(sql_util, interval): return {
    'fields': [(interval, 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('event_name', 'VARCHAR(128) NOT NULL'),
               ('spec', 'VARCHAR(32)'),
               ('level', 'INT2'),
               ('total_stack', 'INT8'),
               ('unique_players', 'INT4')],
    'indices': {'by_'+interval: {'keys': [(interval,'ASC')]}}
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

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('unit_donation_to_sql-%s' % game_id):

        unit_donation_table = cfg['table_prefix']+game_id+'_unit_donation'
        unit_donation_daily_summary_table = cfg['table_prefix']+game_id+'_unit_donation_daily_summary'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, unit_donation_table, unit_donation_schema(sql_util))
        sql_util.ensure_table(cur, unit_donation_daily_summary_table, unit_donation_summary_schema(sql_util, 'day'))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(unit_donation_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        for source_table in ('log_unit_donation',):
            for row in SpinETL.iterate_from_mongodb(game_id, source_table, start_time, end_time):

                if ('sum' in row) and row['sum'].get('developer',False): continue # skip events by developers

                keyvals = [('time',row['time']),
                           ('user_id',row['user_id']),
                           ('event_name',row['event_name'])] + \
                           sql_util.parse_brief_summary(row['sum'])
                for FIELD in ('alliance_id','recipient_id',):
                    if FIELD in row:
                        keyvals.append((FIELD, row[FIELD]))

                if row['event_name'] == '4150_units_donated':
                    sql_util.do_insert_batch(cur, unit_donation_table,
                                             [keyvals + \
                                              [('spec', a['spec']),
                                               ('level', a.get('level',1)),
                                               ('stack', a.get('stack',1))] \
                                              for a in row['units']]
                                             )
                elif row['event_name'] == '4140_unit_donation_requested':
                    # re-purpose the columns: stash the space into the "stack" column, and the region_id in the spec column
                    if 'max_space' in row:
                        keyvals.append(('stack', row['max_space']))
                    if 'region_id' in row:
                        keyvals.append(('spec', row['region_id']))
                    sql_util.do_insert(cur, unit_donation_table, keyvals)
                else:
                    pass # unrecognized event

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
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(unit_donation_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            unit_donation_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            unit_donation_range = None

        def update_unit_donation_summary(cur, table, interval, day_start, dt):
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT %s AS "+interval+"," + \
                        "       frame_platform AS frame_platform," + \
                        "       country_tier AS country_tier," + \
                        "       townhall_level AS townhall_level, " + \
                        "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket, " + \
                        "       event_name AS event_name," + \
                        "       spec AS spec," + \
                        "       level AS level," + \
                        "       SUM(stack) AS total_stack," + \
                        "       COUNT(DISTINCT(user_id)) AS unique_players " + \
                        "FROM " + sql_util.sym(unit_donation_table) + " " + \
                        "WHERE time >= %s AND time < %s " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, event_name, spec, level " + \
                        "ORDER BY NULL",
                        [day_start, day_start, day_start+dt])

        SpinETL.update_summary(sql_util, con, cur, unit_donation_daily_summary_table, affected_days, unit_donation_range, 'day', 86400,
                               verbose = verbose, resummarize_tail = 86400, execute_func = update_unit_donation_summary)

        if do_prune:
            # drop old data
            KEEP_DAYS = 30
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', unit_donation_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(unit_donation_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', unit_donation_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(unit_donation_table))
            con.commit()
