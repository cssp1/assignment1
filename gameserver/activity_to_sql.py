#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "activity" table from MongoDB to a SQL database for analytics
# note: for now, this runs *after* upcache_to_mysql.py and uses the activity table that it creates to make summaries.
# later, this should be switched to a regular MongoDB event stream.

import sys, time, getopt
import SpinConfig
import SpinUpcache
import SpinJSON
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

gamedata = None
time_now = int(time.time())

# keep schema in sync with upcache_to_mysql.py!
def activity_schema(sql_util):
    return {'fields': [('user_id','INT4 NOT NULL'),
                       ('time','INT8 NOT NULL'),
                       ('gamebucks_spent','INT4'),
                       ('receipts','FLOAT4')] + \
                      sql_util.summary_in_dimensions() + \
                      [('state','VARCHAR(32) NOT NULL'),
                       ('ai_ui_name','VARCHAR(32)')],
            'indices': {'time': {'keys': [('time','ASC')]}}
            }

def activity_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('state', 'VARCHAR(32) NOT NULL'),
                       ('ai_ui_name','VARCHAR(32)'),
                       ('active_time','INT8 NOT NULL'),
                       ('gamebucks_spent','INT8 NOT NULL'),
                       ('receipts','FLOAT4 NOT NULL')],
            'indices': {'master': {'unique':True, 'keys': [(interval,'ASC')] + [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions()] + [('state','ASC'),('ai_ui_name','ASC')]}},
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

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    gamedata['ai_bases_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('ai_bases_server.json', override_game_id = game_id)))
    gamedata['hives_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('hives_server.json', override_game_id = game_id)))
    gamedata['raids_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('raids_server.json', override_game_id = game_id)))
    gamedata['quarries_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('quarries_server.json', override_game_id = game_id)))
    gamedata['loot_tables'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('loot_tables.json', override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('activity_to_sql-%s' % game_id):

        activity_table = cfg['table_prefix']+game_id+'_activity_5min'
        activity_daily_summary_table = cfg['table_prefix']+game_id+'_activity_daily_summary'
        activity_hourly_summary_table = cfg['table_prefix']+game_id+'_activity_hourly_summary'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, activity_table, activity_schema(sql_util))
        sql_util.ensure_table(cur, activity_daily_summary_table, activity_summary_schema(sql_util, 'day'))
        sql_util.ensure_table(cur, activity_hourly_summary_table, activity_summary_schema(sql_util, 'hour'))
        con.commit()

        # set time range for MongoDB query
        start_time = -1
        end_time = time_now - 15*60  # skip entries too close to "now" to ensure all activity for a given hour has been seen (5 min activity-collection lag plus some fudge room)

        # find most recent already-converted event in SQL
        cur.execute("SELECT time FROM "+sql_util.sym(activity_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()
        affected_hours = set()

        qs = {'time':{'$gt':start_time, '$lt':end_time }}

        for row in nosql_client.log_buffer_table('activity').find(qs):
            act = SpinUpcache.classify_activity(gamedata, row)
            if not act: continue

            if row.get('developer',False): continue # skip events by developers

            sql_util.do_insert(cur, activity_table,
                               [('user_id',row['user_id']),
                                ('time',row['time']),
                                ('gamebucks_spent',row.get('gamebucks_spent',None)),
                                ('receipts',row.get('money_spent',None))] +
                               sql_util.parse_brief_summary(row) + \
                               [('state',act['state']),
                                ('ai_ui_name',act.get('ai_tag',None) or act.get('ai_ui_name',None))]
                               )

            batch += 1
            total += 1
            affected_days.add(86400*(row['time']//86400))
            affected_hours.add(3600*(row['time']//3600))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)', len(affected_hours), 'hour(s)'

        # update summaries

        # find range of activity data available
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(activity_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            activity_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            activity_range = None

        for sum_table, affected, interval, dt in ((activity_daily_summary_table, affected_days, 'day', 86400),
                                                  (activity_hourly_summary_table, affected_hours, 'hour', 3600)):

            # find range that we should summarize
            cur.execute("SELECT MIN("+interval+") AS min, MAX("+interval+") AS max FROM "+sql_util.sym(sum_table))
            rows = cur.fetchall()
            if rows and rows[0] and rows[0]['min'] and rows[0]['max']:
                # if summary table already exists, update incrementally
                if activity_range: # fill in any missing trailing summary data
                    source_days = sorted(affected.union(set(xrange(dt*(rows[0]['max']//dt + 1), dt*(activity_range[1]//dt + 1), dt))))
                else:
                    source_days = sorted(list(affected))
            else:
                # otherwise start from the beginning of the activity data
                if activity_range:
                    source_days = range(dt*(activity_range[0]//dt), dt*(activity_range[1]//dt + 1), dt)
                else:
                    source_days = None

            con.commit()

            if source_days:
                for day_start in source_days:
                    # if day_start + dt >= time_now - 15*60: continue # skip incomplete hours/days

                    if verbose: print interval, day_start, time.strftime('%Y%m%d %H:%M:%S', time.gmtime(day_start))

                    # delete entries for the summary range we're about to update
                    cur.execute("DELETE FROM "+sql_util.sym(sum_table)+" WHERE "+interval+" >= %s AND "+interval+" < %s + "+str(dt), [day_start, day_start])

                    # fill summary with global login data
                    snapped_time = str(dt)+"*FLOOR(time/"+str(dt)+".0)"
                    cur.execute("INSERT INTO "+sql_util.sym(sum_table) +" " + \
                                "SELECT "+snapped_time+" AS "+interval+"," + \
                                "       frame_platform," + \
                                "       country_tier," + \
                                "       townhall_level," + \
                                "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," + \
                                "       state," + \
                                "       ai_ui_name," + \
                                "       300*SUM(1) AS active_time," + \
                                "       SUM(IFNULL(gamebucks_spent,0)) AS gamebucks_spent," + \
                                "       SUM(IFNULL(receipts,0)) AS receipts " + \
                                "FROM "+sql_util.sym(activity_table)+ " activity WHERE time >= %s AND time < %s + "+str(dt)+" " + \
                                "GROUP BY "+interval+", frame_platform, country_tier, townhall_level, "+sql_util.encode_spend_bracket("prev_receipts")+", state, ai_ui_name ORDER BY NULL", [day_start,]*2)

                    con.commit()

        if do_prune:
            # drop old data
            KEEP_DAYS = 30
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', activity_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(activity_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', activity_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(activity_table))
            con.commit()
