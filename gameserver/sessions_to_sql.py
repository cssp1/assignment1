#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_sessions" table from MongoDB to a SQL database for analytics

import sys, time, getopt, functools
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinETL
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())
commit_interval = 1000
verbose = True
do_prune = False
do_optimize = False
game_id = SpinConfig.game()

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

def do_main():
    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    # INPUTS
    sessions_table = cfg['table_prefix']+game_id+'_sessions'

    # OUTPUTS
    sessions_daily_summary_table = cfg['table_prefix']+game_id+'_sessions_daily_summary'
    sessions_hourly_summary_table = cfg['table_prefix']+game_id+'_sessions_hourly_summary'
    sessions_monthly_summary_table = cfg['table_prefix']+game_id+'_sessions_monthly_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, sessions_table, sessions_schema(sql_util))
    sql_util.ensure_table(cur, sessions_daily_summary_table, sessions_summary_schema(sql_util, 'day', 'dau'))
    sql_util.ensure_table(cur, sessions_hourly_summary_table, sessions_summary_schema(sql_util, 'hour', 'hau'))
    sql_util.ensure_table(cur, sessions_monthly_summary_table, sessions_summary_schema(sql_util, 'month', 'mau'))
    con.commit()

    # set time range for MongoDB query
    TIME_BUFFER = 60 # ignore data too close to "now" for all events to be recorded
    start_time = -1
    end_time = time_now - TIME_BUFFER
    earliest_incomplete = -1
    latest_complete = -1

    # if there were still-open sessions in SQL from a previous run, dump them (and everything after) since we want to replace them
    cur.execute("SELECT MIN(start) AS earliest_incomplete FROM "+sql_util.sym(sessions_table)+" WHERE end < 0")
    rows = cur.fetchall()
    con.commit()
    if rows and rows[0]['earliest_incomplete']:
        earliest_incomplete = rows[0]['earliest_incomplete']

    # find the tail end of fully-complete sessions in SQL
    cur.execute("SELECT MAX(start) AS latest_complete FROM "+sql_util.sym(sessions_table)+" WHERE end > 0")
    rows = cur.fetchall()
    con.commit()
    if rows and rows[0]['latest_complete']:
        latest_complete = rows[0]['latest_complete']

    if earliest_incomplete > 0 and latest_complete > 0:
        start_time = min(earliest_incomplete, latest_complete)
    elif earliest_incomplete > 0:
        start_time = earliest_incomplete
    elif latest_complete > 0:
        start_time = latest_complete

    # rewrite all events since MAX_SESSION_LENGTH ago - this is overly conservative, but ensures we won't skip any logins
    start_time -= SpinETL.MAX_SESSION_LENGTH

    start_time -= TIME_BUFFER
    start_time_compare = '$gte'

    if verbose: print 'earliest_incomplete', earliest_incomplete, 'latest_complete', latest_complete, '-> start_time', start_time

    # dump the tail end of old SQL data, since new logins may have appeared between then and now
    cur.execute("DELETE FROM "+sql_util.sym(sessions_table)+" WHERE start >= %s", [start_time])
    if verbose: print 'dumped', cur.rowcount, 'sessions starting', start_time
    con.commit()

    batch = 0
    total = 0
    total_in_progress = 0
    affected_hours = set()
    affected_days = set()
    affected_months = set()

    # note: query on "in" (login time) instead of "time" (update time of the MongoDB entry)
    qs = {'in':{start_time_compare:start_time, '$lt': end_time}}
    qs['time'] = {start_time_compare:start_time - SpinETL.MAX_SESSION_LENGTH} # for index optimization only

    for row in nosql_client.log_buffer_table('log_sessions').find(qs):
        if row.get('developer',False): continue # skip events by developers

        if row['out'] < 0: # player still logged in
            if time_now - row['in'] >= SpinETL.MAX_SESSION_LENGTH:
                print 'probably bad entry in MongoDB - user_id', row['user_id'], 'logged in at', row['in'], 'and "out" is still', row['out']
                continue
            total_in_progress += 1

        sql_util.do_insert(cur, sessions_table,
                           [('user_id',row['user_id']),
                            ('start',row['in']),
                            ('end',row['out'])] + \
                           sql_util.parse_brief_summary(row))
        batch += 1
        total += 1

        # time range for "affected" days/hours/months. If session is still in progress,
        # the end of the "affected" interval should be "now".
        in_time = row['in']
        out_time = row['out'] if row['out'] > 0 else end_time

        for affected, dt in ((affected_days, 86400), (affected_hours, 3600)):
            for t in xrange(dt*(in_time//dt), dt*(out_time//dt+1), dt):
                affected.add(t)

        # updated affected_months
        # this assumes a session at most touches two months. Not likely you'd log in for more than a whole month!
        for point in (in_time, out_time):
            y,m,d = SpinConfig.unix_to_cal(point)
            affected_months.add(SpinConfig.cal_to_unix((y,m,1))) # first of the month

        if commit_interval > 0 and batch >= commit_interval:
            batch = 0
            con.commit()
            if verbose: print total, 'inserted'

    con.commit()
    if verbose: print 'total', total, '(in progress: %d)' % total_in_progress, 'inserted', \
       'affecting', len(affected_months), 'month(s)', len(affected_days), 'day(s)', len(affected_hours), 'hour(s)'

    # update summaries

    def update_summary(dau_name, cur, table, interval, day_start, dt):
        # sessions summary tables are created in two steps:
        # first, we group together all logins by each individual player within the time interval. This goes into a temporary table with one row per player.
        # second, we accumulate and group this temporary table into the final summary.
        # (doing the summary in a single pass would probably require some exotic PARTITION BY stuff that MySQL is not capable of).

        # Step 1: create a temporary table with one row per player, grouping together all logins within the time interval
        temp_table = table + '_temp'
        sql_util.ensure_table(cur, temp_table, sessions_temp_schema(sql_util, interval), temporary = True)

        day_end = day_start + dt

        # if session is ongoing, use "now" as the end of the session
        session_end = 'IF(end < 0, %d, end)' % (end_time,)

        # playtime = earlier of (logout time, day end) minus later of (login time, day begin)
        playtime = 'LEAST('+session_end+', %d) - GREATEST(start, %d)' % (day_end, day_start)

        # login before day end, login after (a long time before day, for index optimization), logout after day begin OR still logged in
        where_clause = "WHERE start < %d AND start >= %d AND (end >= %d OR end < 0)" % \
                       (day_end, day_start - SpinETL.MAX_SESSION_LENGTH, day_start)

        cur.execute("INSERT INTO "+sql_util.sym(temp_table) + " " + \
                    "SELECT %s AS "+interval+"," + \
                    "       sessions.user_id AS user_id," + \
                    "       sessions.frame_platform AS frame_platform," + \
                    "       sessions.country_tier AS country_tier," + \
                    "       MAX(sessions.townhall_level) AS townhall_level," + \
                    "       MIN(IFNULL(sessions.prev_receipts,0)) AS prev_receipts," + \
                    "       COUNT(*) AS num_logins," + \
                    "       SUM("+playtime+") AS playtime " + \
                    "FROM " + sql_util.sym(sessions_table) + " sessions " + \
                    where_clause + " " + \
                    "GROUP BY "+interval+", user_id ORDER BY NULL",
                    [day_start,])

        # Step 2: update final summay

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

        if verbose:
            cur.execute("SELECT SUM("+dau_name+") AS total FROM "+sql_util.sym(sum_table)+" WHERE "+interval+" = %s", [day_start,])
            rows = cur.fetchall()
            if rows and rows[0]:
                print dau_name.upper(), '=', rows[0]['total']

        con.commit()


    # find range of sessions data available
    cur.execute("SELECT MIN(start) AS min_time, MAX(start) AS max_time FROM "+sql_util.sym(sessions_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        session_range = (rows[0]['min_time'], rows[0]['max_time'])
    else:
        session_range = None

    for sum_table, affected, interval, dau_name, iter_func, dt, iterator in \
        ((sessions_monthly_summary_table, affected_months, 'month', 'mau', SpinETL.month_iterator, 0, SpinETL.month_iterator),
         (sessions_daily_summary_table, affected_days, 'day', 'dau', SpinETL.uniform_iterator, 86400, SpinETL.uniform_iterator),
         (sessions_hourly_summary_table, affected_hours, 'hour', 'hau', SpinETL.uniform_iterator, 3600, SpinETL.uniform_iterator)):

        SpinETL.update_summary(sql_util, con, cur, sum_table, affected, session_range, interval, dt,
                               execute_func = functools.partial(update_summary, dau_name),
                               iterator = iterator,
                               resummarize_tail = dt, verbose = verbose)

    if do_prune:
        # drop old data
        KEEP_DAYS = {'sg': 180}.get(game_id, 30)
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', sessions_table
        cur = con.cursor()
        cur.execute("DELETE FROM "+sql_util.sym(sessions_table)+" WHERE start < %s", [old_limit])
        if do_optimize:
            if verbose: print 'optimizing', sessions_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(sessions_table))
        con.commit()

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    with SpinSingletonProcess.SingletonProcess('sessions-to-sql-%s' % (game_id)):
        do_main()
