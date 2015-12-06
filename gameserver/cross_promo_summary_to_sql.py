#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AFTER updating per-game metrics and upcache tables, incrementally create v_cross_promo_daily_summary table
# this replaces the now-obsolete cross_promo_views.sql script.

import sys, time, getopt
import SpinConfig
import SpinETL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def cross_promo_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL'),
                       ('from_game', 'VARCHAR(4) NOT NULL'),
                       ('to_game', 'VARCHAR(4) NOT NULL'),
                       ('combo', 'VARCHAR(10) NOT NULL'),
                       ('image', 'VARCHAR(64) NOT NULL'),
                       ('impressions', 'INT8 NOT NULL'),
                       ('clicks', 'INT8 NOT NULL'),
                       ('installs', 'INT8 NOT NULL'),
                       ('ctr', 'FLOAT4')],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }

# we need to query the upcache and metrics tables for each game
GAMES = ['mf','tr','mf2','bfm','sg','dv']

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', [])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    cross_promo_daily_summary_table = cfg['table_prefix']+'v_cross_promo_daily_summary'

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    for table, schema in ((cross_promo_daily_summary_table, cross_promo_summary_schema(sql_util,'day')),):
        sql_util.ensure_table(cur, table, schema)
    con.commit()

    # find applicable time range
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    for gid in GAMES:
        cur.execute("SELECT MIN(time) AS start, MAX(time) AS end " + \
                    "FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_acquisitions') + " " + \
                    "WHERE event_name = %s AND acquisition_campaign LIKE %s",
                    ['0110_created_new_account','5145_xp_A%'])
        row = cur.fetchone()
        if row and row['start'] and row['end']:
            if verbose: print gid, 'acquisitions', row['start'], row['end']
            start_time = min(start_time, row['start']) if start_time >= 0 else row['start']

        cur.execute("SELECT MIN(time) AS start, MAX(time) AS end " + \
                    "FROM "+sql_util.sym(gid+'_upcache')+"."+sql_util.sym(gid+'_metrics') + " " + \
                    "WHERE code IN (7530,7531)")
        row = cur.fetchone()
        if row and row['start'] and row['end']:
            if verbose: print gid, 'metrics', row['start'], row['end']
            start_time = min(start_time, row['start']) if start_time >= 0 else row['start']

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    def update_cross_promo_summary(cur, table, interval, day_start, dt):
        for gid in GAMES:
            if verbose: print gid, 'acquisitions...'
            # acquisitions from upcache
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT  %s AS "+sql_util.sym(interval)+"," + \
                        "        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',3),'_',-1) FROM 2) AS from_game," + \
                        "        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',4),'_',-1) FROM 2) AS to_game," + \
                        "        CONCAT(SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',3),'_',-1) FROM 2), '->', SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',4),'_',-1) FROM 2)) AS combo," + \
                        "        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(acquisition_campaign,'_',6),'_',-1) FROM 2) AS image," + \
                        "        0 AS impressions," + \
                        "        0 AS clicks," + \
                        "        SUM(1) AS installs," + \
                        "        NULL AS ctr " + \
                        "FROM " + sql_util.sym(gid+'_upcache') +"."+ sql_util.sym(gid+'_acquisitions') + " " + \
                        "WHERE time >= %s AND time < %s AND event_name = %s AND acquisition_campaign LIKE %s" + \
                        "GROUP BY "+sql_util.sym(interval)+", from_game, to_game, image ORDER BY NULL",
                        [day_start, day_start, day_start+dt, '0110_created_new_account', '5145_xp_A%'])

            if verbose: print gid, 'metrics...'
            # impressions/clicks from metrics
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT  %s AS "+sql_util.sym(interval)+"," + \
                        "        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',3),'_',-1) FROM 2) AS from_game," + \
                        "        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',4),'_',-1) FROM 2) AS to_game," + \
                        "        CONCAT(SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',3),'_',-1) FROM 2), '->', SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',4),'_',-1) FROM 2)) AS combo," + \
                        "        SUBSTRING(SUBSTRING_INDEX(SUBSTRING_INDEX(spec,'_',6),'_',-1) FROM 2) AS image," + \
                        "        SUM(IF(event_name='7530_cross_promo_banner_seen',1,0)) AS impressions," + \
                        "        SUM(IF(event_name='7531_cross_promo_banner_clicked',1,0)) AS clicks," + \
                        "        0 AS installs," + \
                        "        IF(SUM(IF(event_name='7530_cross_promo_banner_seen',1,0))>0, SUM(IF(event_name='7531_cross_promo_banner_clicked',1,0))/SUM(IF(event_name='7530_cross_promo_banner_seen',1,0)), NULL) AS ctr " + \
                        "FROM " + sql_util.sym(gid+'_upcache') +"."+ sql_util.sym(gid+'_metrics') + " " + \
                        "WHERE time >= %s AND time < %s AND code IN (7530,7531) " + \
                        "GROUP BY "+sql_util.sym(interval)+", from_game, to_game, image ORDER BY NULL",
                        [day_start, day_start, day_start + dt])

    for table, affected, interval, dt in ((cross_promo_daily_summary_table, set(), 'day', 86400),):
        SpinETL.update_summary(sql_util, con, cur, table, affected, [start_time,end_time], interval, dt, verbose=verbose, dry_run=dry_run,
                               execute_func = update_cross_promo_summary, resummarize_tail = 2*86400)
