#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_sessions" table from MongoDB to a SQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinETL
import MySQLdb

time_now = int(time.time())

# keep schema in sync with upcache_to_mysql.py!
def sessions_schema(sql_util):
    return {'fields': [('user_id', 'INT4 NOT NULL'),
                       ('start', 'INT8 NOT NULL'),
                       ('end', 'INT8 NOT NULL')] + \
                      sql_util.summary_in_dimensions(),
            'indices': {'by_start': {'keys': [('start','ASC')]},
                        'by_user_start': {'keys': [('user_id','ASC'),('start','ASC')]}}
    }

# intermediate table used only while building the summary
def sessions_temp_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('num_logins', 'INT4 NOT NULL'),
                       ('playtime', 'INT4 NOT NULL')],
            'indices': {'master': {'unique':True, 'keys': [(interval,'ASC'),('user_id','ASC')]}},
            }
def sessions_summary_schema(sql_util, interval, dau_name):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [(dau_name, 'INT4 NOT NULL'),
                       ('num_logins', 'INT4 NOT NULL'),
                       ('playtime', 'INT8 NOT NULL'),
                       ('most_active_playtime', 'INT8 NOT NULL'),
                       ],
            'indices': {'master': {'unique':True, 'keys': [(interval,'ASC')] + [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions()]}},
            }

# return pairs of uniform (t0,t0+dt) intervals within the UNIX time range start->end, inclusive
def uniform_iterator(start, end, dt):
    return ((x,x+dt) for x in xrange(dt*(start//dt), dt*(end//dt + 1), dt))

# return pairs of (t0,t1) intervals for entire calendar months in the UNIX time range start->end, inclusive
def month_iterator(start, end, unused_dt):
    sy,sm,sd = SpinConfig.unix_to_cal(start) # starting year,month,day
    ey,em,ed = SpinConfig.unix_to_cal(end) # ending year,month,day
    while sy <= ey and ((sy < ey) or (sm <= em)):
        lasty = sy
        lastm = sm
        # compute next month
        sm += 1
        if sm > 12:
            sm = 1
            sy += 1

        yield (SpinConfig.cal_to_unix((lasty,lastm,1)), SpinConfig.cal_to_unix((sy,sm,1)))


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

    # INPUTS
    sessions_table = cfg['table_prefix']+game_id+'_sessions'

    # OUTPUTS
    sessions_daily_temp_table = cfg['table_prefix']+game_id+'_sessions_daily_temp'
    sessions_daily_summary_table = cfg['table_prefix']+game_id+'_sessions_daily_summary'
    sessions_hourly_temp_table = cfg['table_prefix']+game_id+'_sessions_hourly_temp'
    sessions_hourly_summary_table = cfg['table_prefix']+game_id+'_sessions_hourly_summary'
    sessions_monthly_temp_table = cfg['table_prefix']+game_id+'_sessions_monthly_temp'
    sessions_monthly_summary_table = cfg['table_prefix']+game_id+'_sessions_monthly_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, sessions_table, sessions_schema(sql_util))
    sql_util.ensure_table(cur, sessions_daily_summary_table, sessions_summary_schema(sql_util, 'day', 'dau'))
    sql_util.ensure_table(cur, sessions_hourly_summary_table, sessions_summary_schema(sql_util, 'hour', 'hau'))
    sql_util.ensure_table(cur, sessions_monthly_summary_table, sessions_summary_schema(sql_util, 'month', 'mau'))
    con.commit()

    # set time range for MongoDB query
    start_time = -1
    end_time = time_now - SpinETL.MAX_SESSION_LENGTH # skip entries too close to "now" to ensure all sessions have been closed by max(end_time)

    # find most recent already-converted event in SQL
    cur.execute("SELECT start FROM "+sql_util.sym(sessions_table)+" ORDER BY start DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['start'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_hours = set()
    affected_days = set()
    affected_months = set()

    qs = {'time':{'$gt':start_time, '$lt': end_time}}

    for row in nosql_client.log_buffer_table('log_sessions').find(qs):
        if row.get('developer',False): continue # skip events by developers
        sql_util.do_insert(cur, sessions_table,
                           [('user_id',row['user_id']),
                            ('start',row['in']),
                            ('end',row['out'])] + \
                           sql_util.parse_brief_summary(row))
        batch += 1
        total += 1
        for affected, dt in ((affected_days, 86400), (affected_hours, 3600)):
            for t in xrange(dt*(row['in']//dt), dt*(row['out']//dt+1), dt):
                affected.add(t)

        # updated affected_months
        # this assumes a session at most touches two months. Not likely you'd log in for more than a whole month!
        for field in ('in','out'):
            y,m,d = SpinConfig.unix_to_cal(row[field])
            affected_months.add(SpinConfig.cal_to_unix((y,m,1))) # first of the month

        if commit_interval > 0 and batch >= commit_interval:
            batch = 0
            con.commit()
            if verbose: print total, 'inserted'

    con.commit()
    if verbose: print 'total', total, 'inserted', 'affecting', len(affected_months), 'month(s)', len(affected_days), 'day(s)', len(affected_hours), 'hour(s)'

    # update summaries

    # find range of sessions data available
    cur.execute("SELECT MIN(start) AS min_time, MAX(start) AS max_time FROM "+sql_util.sym(sessions_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        session_range = (rows[0]['min_time'], rows[0]['max_time'])
    else:
        session_range = None

    for sum_table, temp_table, affected, interval, dau_name, iter_func, dt in \
        ((sessions_monthly_summary_table, sessions_monthly_temp_table, affected_months, 'month', 'mau', month_iterator, -1),
         (sessions_daily_summary_table, sessions_daily_temp_table, affected_days, 'day', 'dau', uniform_iterator, 86400),
         (sessions_hourly_summary_table, sessions_hourly_temp_table, affected_hours, 'hour', 'hau', uniform_iterator, 3600)):

        # find range that we should summarize
        cur.execute("SELECT MIN("+interval+") AS min, MAX("+interval+") AS max FROM "+sql_util.sym(sum_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min'] and rows[0]['max']:
            # if summary table already exists, update it incrementally

            all_starts = affected

            if session_range: # fill in any missing trailing data beyond the end of the existing summary
                trailing_starts = set(x[0] for x in iter_func(rows[0]['max'], session_range[1], dt))
                all_starts = all_starts.union(trailing_starts)

            sum_intervals = [list(iter_func(x,x,dt))[0] for x in sorted(list(all_starts))]

        else:
            if session_range: # otherwise just convert entire sesion data range
                sum_intervals = iter_func(session_range[0], session_range[1], dt)
            else:
                sum_intervals = None

        con.commit()

        if sum_intervals:
            for int_start, int_end in sum_intervals:
                if verbose: print 'summarizing', interval, int_start, ' - '.join(map(lambda x: time.strftime('%Y%m%d %H:%M:%S', time.gmtime(x)), [int_start,int_end]))

                # sessions summary tables are created in two steps:
                # first, we group together all logins by each individual player within the time interval. This goes into a temporary table with one row per player.
                # second, we accumulate and group this temporary table into the final summary.
                # (doing the summary in a single pass would probably require some exotic PARTITION BY stuff that MySQL is not capable of).

                # Step 1: create a temporary table with one row per player, grouping together all logins within the time interval
                sql_util.ensure_table(cur, temp_table, sessions_temp_schema(sql_util, interval), temporary = True)
                cur.execute("INSERT INTO "+sql_util.sym(temp_table) + " " + \
                            "SELECT %s AS "+interval+"," + \
                            "       sessions.user_id AS user_id," + \
                            "       sessions.frame_platform AS frame_platform," + \
                            "       sessions.country_tier AS country_tier," + \
                            "       MAX(sessions.townhall_level) AS townhall_level," + \
                            "       MIN(IFNULL(sessions.prev_receipts,0)) AS prev_receipts," + \
                            "       COUNT(*) AS num_logins," + \
                            "       SUM(IF(end < %s, end, %s) - IF(start > %s, start, %s)) AS playtime " + \
                            "FROM " + sql_util.sym(sessions_table) + " sessions " + \
                            "WHERE start < %s AND start >= %s AND end >= %s " + \
                            "GROUP BY "+interval+", user_id ORDER BY NULL",
                            [int_start,
                             int_end, int_end, int_start, int_start,
                             int_end, int_start - SpinETL.MAX_SESSION_LENGTH, int_start])

                # Step 2: update final summay

                # delete entries for the summary range we're about to update
                cur.execute("DELETE FROM "+sql_util.sym(sum_table)+" WHERE "+interval+" >= %s AND "+interval+" < %s", [int_start, int_end])

                # fill summary with global login data
                cur.execute("INSERT INTO "+sql_util.sym(sum_table) +" " + \
                            "SELECT "+interval+"," + \
                            "       frame_platform," + \
                            "       country_tier," + \
                            "       townhall_level," + \
                            "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," + \
                            "       COUNT(*) AS "+dau_name+"," + \
                            "       SUM(num_logins) AS num_logins," + \
                            "       SUM(playtime) AS playtime, " + \
                            "       MAX(playtime) AS most_active_playtime " + \
                            "FROM "+sql_util.sym(temp_table)+ " temp " + \
                            "GROUP BY "+interval+", frame_platform, country_tier, townhall_level, spend_bracket ORDER BY NULL")

                # get rid of temp table
                cur.execute("DROP TABLE "+sql_util.sym(temp_table))

                con.commit()

    if do_prune:
        # drop old data
        KEEP_DAYS = {'sg': 180}.get(game_id, 30)
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', sessions_table
        cur = con.cursor()
        cur.execute("DELETE FROM "+sql_util.sym(sessions_table)+" WHERE start < %s", old_limit)
        if do_optimize:
            if verbose: print 'optimizing', sessions_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(sessions_table))
        con.commit()
