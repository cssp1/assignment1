#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AFTER running skynet_conversion_pixels_to_sql.py, skynet_adstats_to_sql.py, and skynet_views.sql
# incrementally update skynet v_daily_summary table

import sys, time, getopt
import SpinConfig
import SpinETL
import SpinSQLUtil
import SpinMySQLdb

time_now = int(time.time())

def skynet_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL'),
                       ('tgt_game', 'VARCHAR(4) NOT NULL'),
                       ('tgt_version', 'VARCHAR(16)'),
                       ('tgt_bid_type', 'VARCHAR(16)'),
                       ('tgt_ad_type', 'VARCHAR(16)'),
                       ('tgt_country', 'VARCHAR(16)'),
                       ('tgt_age_range', 'VARCHAR(16)'),
                       ('ad_purpose', 'VARCHAR(16)'),
                       ('impressions', 'INT8 NOT NULL'),
                       ('clicks', 'INT8 NOT NULL'),
                       ('spent_cents', 'INT8 NOT NULL'),
                       ('cohort_receipts_cents', 'INT8 NOT NULL'),
                       ('cohort_receipts_d90_cents', 'INT8 NOT NULL'),
                       ('cohort_installs', 'INT8 NOT NULL'),
                       ('cohort_cc2_by_day_1', 'INT8 NOT NULL'),
                       ('cohort_returned_24_48h', 'INT8 NOT NULL'),
                       ('daily_receipts_cents', 'INT8 NOT NULL'),
                       ('daily_installs', 'INT8 NOT NULL'),
                       ('daily_cc2_by_day_1', 'INT8 NOT NULL'),
                       ('daily_returned_24_48h', 'INT8 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }

if __name__ == '__main__':
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'c:q', [])

    for key, val in opts:
        if key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet')
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    adstats_daily_table = cfg['table_prefix']+'adstats_daily'
    conversions_table = cfg['table_prefix']+'conversions'
    skynet_daily_summary_table = cfg['table_prefix']+'v_daily_summary'

    cur = con.cursor(SpinMySQLdb.cursors.DictCursor)
    for table, schema in ((skynet_daily_summary_table, skynet_summary_schema(sql_util,'day')),):
        sql_util.ensure_table(cur, table, schema)
    con.commit()

    # find applicable time range
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived
    cur.execute("SELECT MIN(time) AS start, MAX(time) AS end " + \
                "FROM "+sql_util.sym(conversions_table))
    row = cur.fetchone()
    if row and row['start'] and row['end']:
        if verbose: print 'conversions', row['start'], row['end']
        start_time = min(start_time, row['start']) if start_time >= 0 else row['start']

    cur.execute("SELECT MIN(time) AS start, MAX(time) AS end " + \
                "FROM "+sql_util.sym(adstats_daily_table))
    row = cur.fetchone()
    if row and row['start'] and row['end']:
        if verbose: print 'adstats', row['start'], row['end']
        start_time = min(start_time, row['start']) if start_time >= 0 else row['start']

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    def update_skynet_summary(cur, table, interval, day_start, dt):
        # ad stats
        cur.execute("INSERT INTO "+sql_util.sym(table) + \
                    "SELECT  %s AS "+sql_util.sym(interval)+"," + \
                    "    tgt_game AS tgt_game," + \
                    "    tgt_version AS tgt_version," + \
                    "    tgt_bid_type AS tgt_bid_type," + \
                    "    tgt_ad_type AS tgt_ad_type," + \
                    "    tgt_country AS tgt_country," + \
                    "    tgt_age_range AS tgt_age_range," + \
                    "    get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences) AS ad_purpose," + \
                    "    SUM(IFNULL(impressions,0)) AS impressions," + \
                    "    SUM(IFNULL(clicks,0)) AS clicks," + \
                    "    SUM(IFNULL(spent,0)) AS spent_cents," + \
                    "    0 AS cohort_receipts_cents," + \
                    "    0 AS cohort_receipts_d90_cents," + \
                    "    0 AS cohort_installs," + \
                    "    0 AS cohort_cc2_by_day_1," + \
                    "    0 AS cohort_returned_24_48h," + \
                    "    0 AS daily_receipts_cents," + \
                    "    0 AS daily_installs, " + \
                    "    0 AS daily_cc2_by_day_1," + \
                    "    0 AS daily_returned_24_48h " + \
                    "FROM " + sql_util.sym(adstats_daily_table) + " " + \
                    "WHERE time >= %s AND time < %s " + \
                    "GROUP BY "+sql_util.sym(interval)+",tgt_game,tgt_version,tgt_bid_type,tgt_ad_type,tgt_country,tgt_age_range,ad_purpose ORDER BY NULL",
                    [day_start, day_start, day_start+dt])
        # conversions by cohort
        cur.execute("INSERT INTO "+sql_util.sym(table) + \
                    "SELECT  %s AS "+sql_util.sym(interval)+"," + \
                    "    tgt_game AS tgt_game," + \
                    "    tgt_version AS tgt_version," + \
                    "    tgt_bid_type AS tgt_bid_type," + \
                    "    tgt_ad_type AS tgt_ad_type," + \
                    "    tgt_country AS tgt_country," + \
                    "    tgt_age_range AS tgt_age_range," + \
                    "    get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences) AS ad_purpose," + \
                    "    0 AS impressions," + \
                    "    0 AS clicks," + \
                    "    0 AS spent_cents," + \
                    "    SUM(IFNULL(usd_receipts_cents,0)) AS cohort_receipts_cents," + \
                    "    SUM(IF(time - account_creation_time < 90*86400, IFNULL(usd_receipts_cents,0), 0)) AS cohort_receipts_d90_cents," + \
                    "    SUM(IF(kpi='acquisition_event',1,0)) AS cohort_installs," + \
                    "    SUM(IF(kpi='cc2_by_day_1',1,0)) AS cohort_cc2_by_day_1," + \
                    "    SUM(IF(kpi='returned_24_48h',1,0)) AS cohort_returned_24_48h," + \
                    "    0 AS daily_receipts_cents," + \
                    "    0 AS daily_installs, " + \
                    "    0 AS daily_cc2_by_day_1," + \
                    "    0 AS daily_returned_24_48h " + \
                    "FROM " + sql_util.sym(conversions_table) + " " + \
                    "WHERE account_creation_time >= %s AND account_creation_time < %s " + \
                    "GROUP BY "+sql_util.sym(interval)+",tgt_game,tgt_version,tgt_bid_type,tgt_ad_type,tgt_country,tgt_age_range,ad_purpose ORDER BY NULL",
                    [day_start, day_start, day_start+dt])

        # conversions by time
        cur.execute("INSERT INTO "+sql_util.sym(table) + \
                    "SELECT  %s AS "+sql_util.sym(interval)+"," + \
                    "    tgt_game AS tgt_game," + \
                    "    tgt_version AS tgt_version," + \
                    "    tgt_bid_type AS tgt_bid_type," + \
                    "    tgt_ad_type AS tgt_ad_type," + \
                    "    tgt_country AS tgt_country," + \
                    "    tgt_age_range AS tgt_age_range," + \
                    "    get_ad_purpose(tgt_game, tgt_version, tgt_purpose, tgt_keyword, tgt_custom_audiences) AS ad_purpose," + \
                    "    0 AS impressions," + \
                    "    0 AS clicks," + \
                    "    0 AS spent_cents," + \
                    "    0 AS cohort_receipts_cents," + \
                    "    0 AS cohort_receipts_d90_cents," + \
                    "    0 AS cohort_installs," + \
                    "    0 AS cohort_cc2_by_day_1," + \
                    "    0 AS cohort_returned_24_48h," + \
                    "    SUM(IFNULL(usd_receipts_cents,0)) AS daily_receipts_cents," + \
                    "    SUM(IF(kpi='acquisition_event',1,0)) AS daily_installs, " + \
                    "    SUM(IF(kpi='cc2_by_day_1',1,0)) AS daily_cc2_by_day_1," + \
                    "    SUM(IF(kpi='returned_24_48h',1,0)) AS daily_returned_24_48h " + \
                    "FROM " + sql_util.sym(conversions_table) + " " + \
                    "WHERE time >= %s AND time < %s " + \
                    "GROUP BY "+sql_util.sym(interval)+",tgt_game,tgt_version,tgt_bid_type,tgt_ad_type,tgt_country,tgt_age_range,ad_purpose ORDER BY NULL",

                    [day_start, day_start, day_start+dt])

    for table, affected, interval, dt in ((skynet_daily_summary_table, set(), 'day', 86400),):
        SpinETL.update_summary(sql_util, con, cur, table, affected, [start_time,end_time], interval, dt, verbose=verbose, dry_run=dry_run,
                               execute_func = update_skynet_summary, resummarize_tail = 2*86400)
