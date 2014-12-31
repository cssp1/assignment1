#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# use "upcache" table in SQL to create acquisition summary tables
# works best with an index on account_creation_time in upcache.
# * this requires the helper functions in analytics_views.sql to be loaded already!

import sys, time, getopt, urlparse
import SpinConfig
import SpinETL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def acquisitions_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4'),
               ('anon_id', 'VARCHAR(128)'),
               ('social_id', 'VARCHAR(128)'),
               ('event_name', 'VARCHAR(128) NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [('ip', 'VARCHAR(16)'),
               ('query_string', 'VARCHAR(1024)'),
               ('acquisition_campaign', 'VARCHAR(128)'),
               ('ad_skynet', 'VARCHAR(256)'),
               ('fb_source', 'VARCHAR(128)'),
               ('lapse_time', 'INT8'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]},
                'by_user_id': {'keys': [('user_id','ASC')]},
                'by_event_name_and_time': {'keys': [('event_name','ASC'),('time','ASC')]}}
    }

def acquisitions_summary_schema(sql_util, interval, dau_name):
    return {'fields': [(interval, 'INT8 NOT NULL'),
                       ('event_name', 'VARCHAR(128) NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('acq_class', 'VARCHAR(128)'),
                       ('acq_source', 'VARCHAR(128)'),
                       ('acq_detail', 'VARCHAR(128)'),
                       ('n_users', 'INT4 NOT NULL'),
                       ],
            'indices': {'master': {'unique':False, 'keys': [(interval,'ASC')]}},
            }

def get_ad_skynet_from_query_string(qs):
    if qs:
        q = urlparse.parse_qs(qs)
        if 'spin_atgt' in q:
            return q['spin_atgt'][0]
        elif 'spin_rtgt' in q:
            return q['spin_rtgt'][0]
    return None

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
    cur = con.cursor(MySQLdb.cursors.DictCursor)

    # INPUTS
    upcache_table = cfg['table_prefix']+game_id+{'mf':'_upcache_lite'}.get(game_id, '_upcache')
    sessions_table = cfg['table_prefix']+game_id+'_sessions'

    # OUTPUTS
    acquisitions_table = cfg['table_prefix']+game_id+'_acquisitions'
    acquisitions_daily_summary_table = cfg['table_prefix']+game_id+'_acquisitions_daily_summary'

    sql_util.ensure_table(cur, acquisitions_table, acquisitions_schema(sql_util))
    sql_util.ensure_table(cur, acquisitions_daily_summary_table, acquisitions_summary_schema(sql_util, 'day', 'dau'))
    con.commit()

    affected_days = set()

    # the acquisitions table is built from several data sources:
    # 0110_created_new_account events: MongoDB log_acquisitions events, plus upcache for historical data
    # 0111_account_lapsed events: SQL sessions table, plus upcache to look up player data
    # 0112_account_reacquired events: MongoDB log_acquisitions events, plus sessions/upcache for historical data

    # time at which valid MongoDB event data takes over from sessions/upcache for acquisition and reacquisition events
    NEW_DATA_START = 1411344000 # 2014 Sept 22 0000GMT

    # query range of session times in SQL sessions table
    sessions_range = None
    cur.execute("SELECT MIN(start) AS min_time, MAX(start) AS max_time FROM "+sql_util.sym(sessions_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        sessions_range = [rows[0]['min_time'], rows[0]['max_time']]
        # skip entries too close to "now" to ensure all events for a given time period have arrived (sessions are written on logout, so wait about the max session time)
        sessions_range[1] = min(sessions_range[1], time_now - 43200)

    if verbose: print 'SQL sessions range', sessions_range

    # query range of account_creation_time in SQL upcache table
    upcache_acq_range = None
    cur.execute("SELECT MIN(account_creation_time) AS min_time, MAX(account_creation_time) AS max_time FROM "+sql_util.sym(upcache_table) +
                " WHERE account_creation_time IS NOT NULL AND account_creation_time > 0")
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        upcache_acq_range = [rows[0]['min_time'], rows[0]['max_time'] + 1] # add 1 sec so that "<" query does include the final users
        # skip entries too close to "now" to ensure all events for a given time period have arrived (users are written on logout, so wait about the max session time, and add one-hour delay for upcache)
        upcache_acq_range[1] = min(upcache_acq_range[1], time_now - 86400)

    if verbose: print 'SQL upcache account_creation_time range', upcache_acq_range

    # query range of existing imported event data in SQL acquisitions table (by event_name)
    import_range = {}
    cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time, event_name FROM "+sql_util.sym(acquisitions_table) +
                " GROUP BY event_name")
    rows = cur.fetchall()
    for row in rows:
        import_range[row['event_name']] = [row['min_time'], row['max_time']]
    if verbose: print 'SQL acquisitions existing imported data range', import_range

    # 0110_created_new_account STEP 1: pull historical data from upcache, if the existing imported data does not extend past NEW_DATA_START
    if upcache_acq_range and \
       ((NEW_DATA_START < 0) or ('0110_created_new_account' not in import_range) or (import_range['0110_created_new_account'][1] < NEW_DATA_START)):

        if '0110_created_new_account' in import_range: # add incrementally to existing data
            upcache_acq_range[0] = max(upcache_acq_range[0], import_range['0110_created_new_account'][1]+1) # add +1 her since account_creation_time query uses ">="

        if NEW_DATA_START > 0: # switch over to MongoDB events at this time
            upcache_acq_range[1] = min(upcache_acq_range[1], NEW_DATA_START)

        if verbose: print 'populating acquisitions table with 0110_created_new_account events (from SQL upcache)...', upcache_acq_range

        cur.execute("DELETE FROM "+sql_util.sym(acquisitions_table)+" WHERE event_name = %s AND time >= %s AND time < %s" , ['0110_created_new_account', upcache_acq_range[0], upcache_acq_range[1]])
        cur.execute("INSERT INTO "+sql_util.sym(acquisitions_table) + " " + \
                    "SELECT account_creation_time AS time, " + \
                    "       user_id AS user_id, " + \
                    "       NULL AS anon_id, " + \
                    "       IFNULL(social_id, IF(frame_platform = 'fb', CONCAT('fb',facebook_id), NULL)) AS social_id, " + \
                    "       '0110_created_new_account' AS event_name, " + \
                    "       IFNULL(frame_platform, 'fb') AS frame_platform, " + \
                    "       IFNULL(country_tier, '4') AS country_tier, " + \
                    "       NULL AS townhall_level, " + \
                    "       NULL AS prev_receipts, " + \
                    "       NULL AS ip, " + \
                    "       NULL AS query_string, " + \
                    "       acquisition_campaign AS acquisition_campaign, " + \
                    "       acquisition_ad_skynet AS ad_skynet, " + \
                    "       NULL AS fb_source, " + \
                    "       NULL AS lapse_time " + \
                    "FROM "+sql_util.sym(upcache_table)+ " upcache " + \
                    "WHERE account_creation_time IS NOT NULL AND account_creation_time >= %s AND account_creation_time < %s",
                    [upcache_acq_range[0], upcache_acq_range[1]])
        con.commit()

        for day_range in SpinETL.uniform_iterator(upcache_acq_range[0], upcache_acq_range[1], 86400):
            affected_days.add(day_range[0])

        if verbose: print 'inserted', cur.rowcount, '0110_created_new_account events (from SQL upcache) affecting', len(affected_days), 'day(s)'

    # 0110_created_new_account STEP 2: pull MongoDB acquisition events
    if NEW_DATA_START > 0:
        keyval_list = []
        mongo_affected_days = set()

        # set time range to add incrementally to imported data
        mongo_acq_range = [max(NEW_DATA_START, import_range['0110_created_new_account'][1] if '0110_created_new_account' in import_range else -1), time_now - 60]
        # note: do NOT add +1 to start time since iterate_from_mongodb() uses ">" not ">="

        if verbose: print 'populating acquisitions table with 0110_created_new_account events (from MongoDB log_acquisitions)...', mongo_acq_range
        for row in SpinETL.iterate_from_mongodb(game_id, 'log_acquisitions', mongo_acq_range[0], mongo_acq_range[1],
                                                query = {'event_name': '0110_created_new_account'}):
            keyvals = [('time', row['time']),
                       ('event_name', row['event_name']),
                       ('user_id', row['user_id'])] + \
                       [(k, row.get(k,None)) for k in ('frame_platform', 'country_tier', 'anon_id', 'social_id', 'ip', 'query_string', 'acquisition_campaign', 'fb_source', 'lapse_time')] + \
                       [('ad_skynet', get_ad_skynet_from_query_string(row['query_string']) if 'query_string' in row else None)]

            keyval_list.append(keyvals)
            mongo_affected_days.add(86400*(row['time']//86400))

        if keyval_list:
            sql_util.do_insert_batch(cur, acquisitions_table, keyval_list)
            con.commit()
            if verbose: print 'inserted', len(keyval_list), '0110_created_new_account events (from MongoDB log_acquisitions) affecting', len(mongo_affected_days), 'day(s)'
            affected_days = affected_days.union(mongo_affected_days)

    # 0112_account_reacquired STEP 1: pull historical data from sessions table/upcache, if the existing imported data does not extend past NEW_DATA_START
    if sessions_range and \
       ((NEW_DATA_START < 0) or ('0112_account_reacquired' not in import_range) or (import_range['0112_account_reacquired'][1] < NEW_DATA_START)):

        query_range = [sessions_range[0], sessions_range[1]]
        if '0112_account_reacquired' in import_range:
            query_range[0] = max(query_range[0], import_range['0112_account_reacquired'][1]) # add incrementally to existing data (+1 fencepost does not matter since we rebuild an entire day at a time)

        for int_start, int_end in SpinETL.uniform_iterator(query_range[0], query_range[1], 86400):
            if verbose:
                print 'populating acquisitions table with 0112_account_reacquired events (from SQL sessions/upcache)...', ' - '.join(map(lambda x: time.strftime('%Y%m%d %H:%M:%S', time.gmtime(x)), [int_start,int_end])),
                sys.stdout.flush()

            cur.execute("DELETE FROM "+sql_util.sym(acquisitions_table)+" WHERE event_name = %s AND time >= %s AND time < %s" , ['0112_account_reacquired', int_start, int_end])
            cur.execute("INSERT INTO "+sql_util.sym(acquisitions_table) + " " + \
                        "SELECT s.start AS time, " + \
                        "       s.user_id AS user_id, " + \
                        "       NULL AS anon_id, " + \
                        "       IFNULL(u.social_id, IF(u.frame_platform = 'fb', CONCAT('fb',u.facebook_id), NULL)) AS social_id, " + \
                        "       '0112_account_reacquired' AS event_name, " + \
                        "       s.frame_platform AS frame_platform, " + \
                        "       s.country_tier AS country_tier, " + \
                        "       s.townhall_level AS townhall_level, " + \
                        "       s.prev_receipts AS prev_receipts, " + \
                        "       NULL AS ip, " + \
                        "       NULL AS query_string, " + \
                        "       NULL AS acquisition_campaign, " + \
                        "       NULL AS ad_skynet, " + \
                        "       NULL AS fb_source, " + \
                        "       s.start - (SELECT MAX(s3.start) FROM "+sql_util.sym(sessions_table)+" s3 WHERE s3.user_id = s.user_id AND s3.start < s.start) AS lapse_time " + \
                        "FROM "+sql_util.sym(sessions_table)+ " s " + \
                        "LEFT JOIN "+sql_util.sym(upcache_table)+" u ON u.user_id = s.user_id " + \
                        "WHERE s.start >= %s AND s.start < %s AND " + \
                        "u.account_creation_time IS NOT NULL AND s.start > u.account_creation_time AND " + \
                        "(NOT EXISTS(SELECT s2.start FROM "+sql_util.sym(sessions_table)+" s2 WHERE s2.user_id = s.user_id AND s2.start >= s.start - %s AND s2.start < s.start))",
                        [int_start, int_end,
                         SpinConfig.ACCOUNT_LAPSE_TIME])
            con.commit()
            affected_days.add(int_start)
            if verbose:
                print cur.rowcount, 'reacquired'

    # 0112_account_reacquired STEP 2: pull MongoDB reacquisition events
    if NEW_DATA_START > 0:
        keyval_list = []
        mongo_affected_days = set()

        # set time range to add incrementally to imported data
        mongo_acq_range = [max(NEW_DATA_START, import_range['0112_account_reacquired'][1] if '0112_account_reacquired' in import_range else -1), time_now - 60]
        # note: do NOT add +1 to start time since iterate_from_mongodb() uses ">" not ">="

        if verbose: print 'populating acquisitions table with 0112_account_reacquired events (from MongoDB log_acquisitions)...', mongo_acq_range
        for row in SpinETL.iterate_from_mongodb(game_id, 'log_acquisitions', mongo_acq_range[0], mongo_acq_range[1],
                                                query = {'event_name': '0112_account_reacquired'}):
            keyvals = [('time', row['time']),
                       ('event_name', row['event_name']),
                       ('user_id', row['user_id']),
                       ('ad_skynet', get_ad_skynet_from_query_string(row['query_string']) if 'query_string' in row else None),
                       ] + \
                       [(k, row.get(k,None)) for k in ('anon_id', 'social_id', 'ip', 'query_string', 'acquisition_campaign', 'fb_source', 'lapse_time')]

            # note: adds frame_platform and country_tier
            keyvals += sql_util.parse_brief_summary(row.get('sum',None))

            keyval_list.append(keyvals)
            mongo_affected_days.add(86400*(row['time']//86400))

        if keyval_list:
            sql_util.do_insert_batch(cur, acquisitions_table, keyval_list)
            con.commit()
            if verbose: print 'inserted', cur.rowcount, '0112_account_reacquired events (from MongoDB log_acquisitions) affecting', len(mongo_affected_days), 'day(s)'
            affected_days = affected_days.union(mongo_affected_days)

    # 0111_account_lapsed STEP 1: pull all data from sessions table (join to upcache to fill in user properties)
    if sessions_range:
        query_start = sessions_range[0] + SpinConfig.ACCOUNT_LAPSE_TIME
        if '0111_account_lapsed' in import_range:
            query_start = max(query_start, import_range['0111_account_lapsed'][1]) # add incrementally to existing data (+1 fencepost does not matter since we rebuild an entire day at a time)

        for int_start, int_end in SpinETL.uniform_iterator(query_start, sessions_range[1], 86400):

            if verbose:
                print 'populating acquisitions table with 0111_account_lapsed events...    ', ' - '.join(map(lambda x: time.strftime('%Y%m%d %H:%M:%S', time.gmtime(x)), [int_start,int_end])),
                sys.stdout.flush()

            cur.execute("DELETE FROM "+sql_util.sym(acquisitions_table)+" WHERE event_name = %s AND time >= %s AND time < %s" , ['0111_account_lapsed', int_start, int_end])
            cur.execute("INSERT INTO "+sql_util.sym(acquisitions_table) + " " + \
                        "SELECT s.start + %s AS time, " + \
                        "       s.user_id AS user_id, " + \
                        "       NULL AS anon_id, " + \
                        "       IFNULL(u.social_id, IF(u.frame_platform = 'fb', CONCAT('fb',u.facebook_id), NULL)) AS social_id, " + \
                        "       '0111_account_lapsed' AS event_name, " + \
                        "       s.frame_platform AS frame_platform, " + \
                        "       s.country_tier AS country_tier, " + \
                        "       s.townhall_level AS townhall_level, " + \
                        "       s.prev_receipts AS prev_receipts, " + \
                        "       NULL AS ip, " + \
                        "       NULL AS query_string, " + \
                        "       u.acquisition_campaign AS acquisition_campaign, " + \
                        "       u.acquisition_ad_skynet AS ad_skynet, " + \
                        "       NULL AS fb_source, " + \
                        "       %s AS lapse_time " + \
                        "FROM "+sql_util.sym(sessions_table)+ " s " + \
                        "LEFT JOIN "+sql_util.sym(upcache_table)+" u ON u.user_id = s.user_id " + \
                        "WHERE s.start > %s AND s.start < %s AND " + \
                        "(NOT EXISTS(SELECT s2.start FROM "+sql_util.sym(sessions_table)+" s2 WHERE s2.user_id = s.user_id AND s2.start > s.start AND s2.start < s.start + %s))",
                        [SpinConfig.ACCOUNT_LAPSE_TIME,
                         SpinConfig.ACCOUNT_LAPSE_TIME,
                         int_start - SpinConfig.ACCOUNT_LAPSE_TIME, int_end - SpinConfig.ACCOUNT_LAPSE_TIME,
                         SpinConfig.ACCOUNT_LAPSE_TIME])
            con.commit()
            affected_days.add(int_start)
            if verbose:
                print cur.rowcount, 'lapsed'

    # SUMMARIZE

    # find range of event data available
    cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(acquisitions_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        acq_range = (rows[0]['min_time'], rows[0]['max_time'])
    else:
        acq_range = None

    for sum_table, affected, interval, dau_name, iter_func, dt in \
        ((acquisitions_daily_summary_table, affected_days, 'day', 'dau', SpinETL.uniform_iterator, 86400),):

        # find range that we should summarize
        cur.execute("SELECT MIN("+interval+") AS min, MAX("+interval+") AS max FROM "+sql_util.sym(sum_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min'] and rows[0]['max']:
            # if summary table already exists, update it incrementally
            all_starts = affected
            if acq_range: # fill in any missing trailing data beyond the end of the existing summary
                trailing_starts = set(x[0] for x in iter_func(rows[0]['max'], acq_range[1], dt))
                all_starts = all_starts.union(trailing_starts)

            sum_intervals = [list(iter_func(x,x,dt))[0] for x in sorted(list(all_starts))]

        else:
            if acq_range: # otherwise just convert entire data range
                sum_intervals = iter_func(acq_range[0], acq_range[1], dt)
            else:
                sum_intervals = None

        con.commit()

        if sum_intervals:
            for int_start, int_end in sum_intervals:
                if verbose: print 'summarizing', interval, int_start, ' - '.join(map(lambda x: time.strftime('%Y%m%d %H:%M:%S', time.gmtime(x)), [int_start,int_end]))

                # delete entries for the summary range we're about to update
                cur.execute("DELETE FROM "+sql_util.sym(sum_table)+" WHERE "+interval+" >= %s AND "+interval+" < %s", [int_start, int_end])

                # fill summary with global login data
                cur.execute("INSERT INTO "+sql_util.sym(sum_table) +" " + \
                            "SELECT %s AS "+interval+", " + \
                            "       event_name AS event_name, " + \
                            "       frame_platform AS frame_platform," + \
                            "       country_tier AS country_tier," + \
                            "       townhall_level AS townhall_level," + \
                            "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket, " + \
                            "       classify_acquisition_campaign(IFNULL(frame_platform, 'fb'), acquisition_campaign) AS acq_class," + \
                            "       IF(frame_platform IS NULL OR frame_platform = 'fb', remap_facebook_campaigns(acquisition_campaign), acquisition_campaign) AS acq_source," + \
                            "       acquisition_campaign AS acq_detail," + \
                            "       IF(event_name = '0111_account_lapsed',-1,1)*COUNT(1) AS n_users " + \
                            "FROM "+sql_util.sym(acquisitions_table)+ " acq " + \
                            "WHERE time >= %s AND time < %s " + \
                            "GROUP BY "+interval+", event_name, IFNULL(frame_platform, 'fb'), IFNULL(country_tier, '4'), townhall_level, spend_bracket, acq_class, acq_source, acq_detail " + \
                            "ORDER BY NULL", [int_start, int_start, int_end])
                con.commit()

    # no pruning
