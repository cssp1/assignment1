#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AFTER updating per-game credits and sessions tables, incrementally create title_daily_summary table
# this is run once in the skynet database, and combines data from all titles.

import sys, time, getopt
import SpinConfig
import SpinETL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def title_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL'),
                       ('game', 'VARCHAR(4) NOT NULL'),
                       ('country_tier', 'CHAR(1) NOT NULL'),
                       ('dau', 'INT4'),
                       ('total_usd_receipts', 'FLOAT4'),
                       ('discount_usd_receipts', 'FLOAT4'),
                       ('unique_payers', 'INT4'),
                       ('first_time_payers', 'INT4'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }

# we need to query the upcache and metrics tables for each game
GAMES = ['mf','tr','mf2','bfm','sg','dv','fs']

if __name__ == '__main__':
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', [])

    for key, val in opts:
        if key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    title_daily_summary_table = cfg['table_prefix']+'title_daily_summary'

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    for table, schema in ((title_daily_summary_table, title_summary_schema(sql_util,'day')),):
        sql_util.ensure_table(cur, table, schema)
    con.commit()

    # find applicable time range
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    for gid in GAMES:
        cur.execute("SELECT MIN(day) AS start, MAX(day) AS end " + \
                    "FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_sessions_daily_summary'))
        row = cur.fetchone()
        if row and row['start'] and row['end']:
            if verbose: print gid, 'sessions', row['start'], row['end']
            start_time = min(start_time, row['start']) if start_time >= 0 else row['start']

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    def update_title_summary(cur, table, interval, day_start, dt):
        for gid in GAMES:
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT  %s AS "+sql_util.sym(interval)+"," + \
                        "        %s AS game," + \
                        "        sessions.country_tier AS country_tier," + \
                        "        SUM(sessions.dau) AS dau," + \
                        "        IFNULL((SELECT SUM(raw.usd_receipts_cents) FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_credits')+" raw WHERE raw.time >= %s AND raw.time < %s AND raw.country_tier = sessions.country_tier AND raw.usd_receipts_cents > 0),0)/100.0 AS total_usd_receipts," + \
                        "        IFNULL((SELECT SUM(raw.usd_receipts_cents) FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_credits')+" raw WHERE raw.time >= %s AND raw.time < %s AND raw.country_tier = sessions.country_tier AND raw.usd_receipts_cents > 0 AND raw.description LIKE '%%FLASH%%'),0)/100.0 AS discount_usd_receipts," + \
                        "        IFNULL((SELECT COUNT(DISTINCT(user_id)) FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_credits')+" raw WHERE raw.time >= %s AND raw.time < %s AND raw.country_tier = sessions.country_tier AND raw.usd_receipts_cents > 0),0) AS unique_payers," + \
                        "        IFNULL((SELECT COUNT(1) FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_credits')+" raw WHERE raw.time >= %s AND raw.time < %s AND raw.usd_receipts_cents > 0 AND raw.prev_receipts <= 0),0) AS first_time_payers " + \
                        "FROM " + sql_util.sym(gid+'_upcache') +"."+ sql_util.sym(gid+'_sessions_daily_summary') + " sessions " + \
                        "WHERE sessions."+interval+" >= %s AND sessions."+interval+" < %s " + \
                        "GROUP BY sessions."+sql_util.sym(interval)+", country_tier ORDER BY NULL",
                        [day_start, gid, day_start, day_start+dt, day_start, day_start+dt, day_start, day_start+dt, day_start, day_start+dt, day_start, day_start+dt])


    for table, affected, interval, dt in ((title_daily_summary_table, set(), 'day', 86400),):
        SpinETL.update_summary(sql_util, con, cur, table, affected, [start_time,end_time], interval, dt, verbose=verbose, dry_run=dry_run,
                               execute_func = update_title_summary, resummarize_tail = 2*86400)
