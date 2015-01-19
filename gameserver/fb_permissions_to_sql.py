#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_fb_permissions" from MongoDB to a MySQL database for analytics

import os, sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())
def fb_permissions_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4'),
               ('anon_id', 'VARCHAR(128)'),
               ('social_id', 'VARCHAR(128)'),
               ('event_name', 'VARCHAR(128) NOT NULL'),
               ('country', 'VARCHAR(2)'),
               ('country_tier', 'CHAR(1)'),
               ('ip', 'VARCHAR(16)'),
               ('browser_name', 'VARCHAR(16)'),
               ('browser_os', 'VARCHAR(16)'),
               ('browser_version', 'FLOAT4'),
               ('scope', 'VARCHAR(128)'),
               ('method', 'VARCHAR(128)'),
               ('splash_image', 'VARCHAR(128)'),
               ('query_string', 'VARCHAR(1024)'),
               ('attempts', 'INT4'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }
def fb_permissions_summary_schema(sql_util): return {
    'fields': [('day', 'INT8 NOT NULL'),
               ('event_name', 'VARCHAR(128) NOT NULL'),
               ('count', 'INT4'),
               ('unique_players', 'INT4')],
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
    fb_permissions_table = cfg['table_prefix']+game_id+'_fb_permissions'
    fb_permissions_summary_table = cfg['table_prefix']+game_id+'_fb_permissions_daily_summary'

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, fb_permissions_table, fb_permissions_schema(sql_util))
    sql_util.ensure_table(cur, fb_permissions_summary_table, fb_permissions_summary_schema(sql_util))
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur.execute("SELECT time FROM "+sql_util.sym(fb_permissions_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_days = set()

    for source_table in ('log_fb_permissions',):
        for row in iterate_from_mongodb(game_id, source_table, start_time, end_time):

            if ('frame_platform' in row) and (row['frame_platform'] != 'fb'):
                continue # skip non-FB events

            if row['event_name'] == '0110_created_new_account':
                # get rid of irrelevant "method" from gameserver and replace with fb_source
                if 'method' in row: del row['method']
                if 'fb_source' in row: row['method'] = row['fb_source']

            keyvals = [('time',row['time']),
                       ('event_name',row['event_name'])]

            if ('country' in row) and row['country'] == 'unknown':
                del row['country'] # do not record "unknown" countries

            if ('country_tier' not in row) and ('country' in row):
                row['country_tier'] = SpinConfig.country_tier_map.get(row['country'], 4)

            if ('splash_image' in row) and (not (row['splash_image'].startswith('#'))):
                row['splash_image'] = os.path.basename(row['splash_image'])

            for FIELD in ('user_id','anon_id','social_id','country','country_tier','ip',
                          'browser_name','browser_os','browser_version','scope','method',
                          'splash_image','query_string','attempts'):
                if FIELD in row:
                    keyvals.append((FIELD, row[FIELD]))

            sql_util.do_insert(cur, fb_permissions_table, keyvals)

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
    if 0: # XXXXXX no summary yet. Should probably group events by anon_id to connect new account creation to original hit.
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(fb_permissions_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            event_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            event_range = None

        dt = 86400

        # check how much summary data we already have
        cur.execute("SELECT MIN(day) AS begin, MAX(day) AS end FROM "+sql_util.sym(fb_permissions_summary_table))
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
                if verbose: print 'updating', fb_permissions_summary_table, 'at', time.strftime('%Y%m%d', time.gmtime(day_start))

                # delete entries for the date range we're about to update
                cur.execute("DELETE FROM "+sql_util.sym(fb_permissions_summary_table)+" WHERE day >= %s AND day < %s+86400", [day_start,]*2)
                cur.execute("INSERT INTO "+sql_util.sym(fb_permissions_summary_table) + \
                            "SELECT 86400*FLOOR(time/86400.0) AS day ," + \
                            "       frame_platform AS frame_platform, " + \
                            "       country_tier AS country_tier ," + \
                            "       townhall_level AS townhall_level, " + \
                            "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket, " + \
                            "       event_name AS event_name, " + \
                            "       ref AS ref, " + \
                            "       fb_ref AS fb_ref, " + \
                            "       COUNT(1) AS count, " + \
                            "       COUNT(DISTINCT(user_id)) AS unique_players " + \
                            "FROM " + sql_util.sym(fb_permissions_table) + " inv " + \
                            "WHERE time >= %s AND time < %s+86400 " + \
                            "GROUP BY day, frame_platform, country_tier, townhall_level, spend_bracket, event_name, ref, fb_ref ORDER BY NULL", [day_start,]*2)

                con.commit() # one commit per day
        else:
            if verbose: print 'no change to', fb_permissions_summary_table


    if do_prune:
        # drop old data
        KEEP_DAYS = 90
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', fb_permissions_table
        cur = con.cursor()
        cur.execute("DELETE FROM "+sql_util.sym(fb_permissions_table)+" WHERE time < %s", old_limit)
        if do_optimize:
            if verbose: print 'optimizing', fb_permissions_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(fb_permissions_table))
        con.commit()
