#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_inventory" from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())
def inventory_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('event_name', 'VARCHAR(128) NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [('spec', 'VARCHAR(255) NOT NULL'),
               ('level', 'INT1'),
               ('stack', 'INT4 NOT NULL'),
               ('expire_time', 'INT8'),
               ('reason', 'VARCHAR(32)')],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }
def inventory_summary_schema(sql_util): return {
    'fields': [('day', 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('spec', 'VARCHAR(255) NOT NULL'),
               ('level', 'INT1'),
               ('event_name', 'VARCHAR(128) NOT NULL'),
               ('reason', 'VARCHAR(32)'),
               ('stack', 'INT8 NOT NULL')],
    'indices': {'by_day': {'keys': [('day','ASC')]}}
    }

def iterate_from_mongodb(game_id, table_name, start_time, end_time):
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))
    qs = {'time': {'$gt': start_time, '$lt': end_time}}

    for row in nosql_client.log_buffer_table(table_name).find(qs):
        row['_id'] = nosql_client.decode_object_id(row['_id'])
        yield row

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

    with SpinSingletonProcess.SingletonProcess('inventory_to_sql-%s' % game_id):

        inventory_table = cfg['table_prefix']+game_id+'_inventory'
        inventory_summary_table = cfg['table_prefix']+game_id+'_inventory_daily_summary'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, inventory_table, inventory_schema(sql_util))
        sql_util.ensure_table(cur, inventory_summary_table, inventory_summary_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(inventory_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        for source_table in ('log_inventory',):
            for row in iterate_from_mongodb(game_id, source_table, start_time, end_time):

                if row['sum'].get('developer',False): continue # skip events by developers

                keyvals = [('time',row['time']),
                           ('user_id',row['user_id']),
                           ('event_name',row['event_name'])] + \
                           sql_util.parse_brief_summary(row['sum']) + \
                          [('spec',row['spec']),
                           ('level',row.get('level',None)),
                           ('stack',row['stack']),
                           ('expire_time',row.get('expire_time',None)),
                           ('reason',row.get('reason',None))]

                sql_util.do_insert(cur, inventory_table, keyvals)

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

        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(inventory_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            event_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            event_range = None

        dt = 86400

        # check how much summary data we already have
        cur.execute("SELECT MIN(day) AS begin, MAX(day) AS end FROM "+sql_util.sym(inventory_summary_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['begin'] and rows[0]['end']:
            # we already have summary data - update it incrementally
            if event_range: # fill in any missing trailing summary data
                source_days = sorted(affected_days.union(set(xrange(dt*(rows[0]['end']//dt + 1), dt*(event_range[1]//dt + 1), dt))))
            else:
                source_days = sorted(list(affected_days))
        else:
            # recreate entire summary
            if event_range:
                source_days = range(dt*(event_range[0]//dt), dt*(event_range[1]//dt + 1), dt)
            else:
                source_days = None

        if source_days:
            for day_start in source_days:
                if verbose: print 'updating', inventory_summary_table, 'at', time.strftime('%Y%m%d', time.gmtime(day_start))

                # delete entries for the date range we're about to update
                cur.execute("DELETE FROM "+sql_util.sym(inventory_summary_table)+" WHERE day >= %s AND day < %s+86400", [day_start,]*2)
                cur.execute("INSERT INTO "+sql_util.sym(inventory_summary_table) + \
                            "SELECT 86400*FLOOR(time/86400.0) AS day ," + \
                            "       frame_platform AS frame_platform, " + \
                            "       country_tier AS country_tier ," + \
                            "       townhall_level AS townhall_level, " + \
                            "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket, " + \
                            "       spec AS spec, " + \
                            "       level AS level, " + \
                            "       event_name AS event_name, " + \
                            "       reason AS reason, " + \
                            "       SUM(stack) AS stack " + \
                            "FROM " + sql_util.sym(inventory_table) + " inv " + \
                            "WHERE time >= %s AND time < %s+86400 " + \
                            "GROUP BY day, frame_platform, country_tier, townhall_level, spend_bracket, spec, level, event_name, reason ORDER BY NULL", [day_start,]*2)

                con.commit() # one commit per day
        else:
            if verbose: print 'no change to', inventory_summary_table


        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', inventory_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(inventory_table)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', inventory_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(inventory_table))
            con.commit()
