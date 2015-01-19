#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_damage_protection" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinETL
import SpinNoSQL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def damage_protection_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('event_name', 'VARCHAR(255) NOT NULL'),
                       ('reason', 'VARCHAR(255)'),
                       ('spellname', 'VARCHAR(255)'),
                       ('prev_end_time', 'INT8'),
                       ('new_end_time', 'INT8'),
                       ('delta', 'INT8'),
                       ('attacker_id', 'INT4'),
                       ('defender_id', 'INT4'),
                       ('base_damage', 'FLOAT4'),
                       ],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }

def damage_protection_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('event_name', 'VARCHAR(255) NOT NULL'),
                       ('reason', 'VARCHAR(255)'),
                       ('spellname', 'VARCHAR(255)'),
                       ('total_delta', 'INT8'),
                       ('min_delta', 'INT8'),
                       ('max_delta', 'INT8'),
                       ('avg_delta', 'INT8'),
                       ('n_events', 'INT8'),
                       ('unique_players', 'INT8'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    damage_protection_table = cfg['table_prefix']+game_id+'_damage_protection'
    damage_protection_daily_summary_table = cfg['table_prefix']+game_id+'_damage_protection_daily_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, damage_protection_table, damage_protection_schema(sql_util))
    sql_util.ensure_table(cur, damage_protection_daily_summary_table, damage_protection_summary_schema(sql_util, 'day'))
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur.execute("SELECT time FROM "+sql_util.sym(damage_protection_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_days = set()

    qs = {'time':{'$gt':start_time, '$lt':end_time}}

    for row in nosql_client.log_buffer_table('log_damage_protection').find(qs):
        if row['sum'].get('developer',False): continue # skip events by developers

        keyvals = [('time',row['time']),
                   ('user_id',row['user_id'])] + \
                  sql_util.parse_brief_summary(row['sum']) + \
                  [('event_name', row['event_name']),
                   ('reason', row.get('reason', None)),
                   ('spellname', row.get('spellname', None)),
                   ('prev_end_time', row.get('prev_end_time', None)),
                   ('new_end_time', row.get('new_end_time', None)),
                   ('delta', row.get('delta', None)),
                   ('attacker_id', row.get('attacker_id', None)),
                   ('defender_id', row.get('defender_id', None)),
                   ('base_damage', row.get('base_damage', None)),
                   ]

        if not dry_run:
            sql_util.do_insert(cur, damage_protection_table, keyvals)
        else:
            print keyvals

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
    cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(damage_protection_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        damage_protection_range = (rows[0]['min_time'], rows[0]['max_time'])
    else:
        damage_protection_range = None

    def update_damage_protection_summary(cur, table, interval, day_start, dt):
        cur.execute("INSERT INTO "+sql_util.sym(damage_protection_daily_summary_table) + \
                    "SELECT %s AS "+interval+"," + \
                    "       frame_platform AS frame_platform," + \
                    "       country_tier AS country_tier," + \
                    "       townhall_level AS townhall_level," + \
                    "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," + \
                    "       event_name AS event_name," + \
                    "       reason AS reason," + \
                    "       spellname AS spellname," + \
                    "       SUM(IFNULL(delta,0)) AS total_delta," + \
                    "       MIN(delta) AS min_delta," + \
                    "       MAX(delta) AS max_delta," + \
                    "       AVG(delta) AS avg_delta," + \
                    "       COUNT(1) AS n_events," + \
                    "       COUNT(DISTINCT(user_id)) AS unique_players " + \
                    "FROM " + sql_util.sym(damage_protection_table) + " dp " + \
                    "WHERE time >= %s AND time < %s " + \
                    "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, event_name, reason, spellname ORDER BY NULL",
                    [day_start, day_start, day_start+dt])

    SpinETL.update_summary(sql_util, con, cur, damage_protection_daily_summary_table, affected_days, damage_protection_range, 'day', 86400,
                           verbose = verbose, resummarize_tail = 86400, execute_func = update_damage_protection_summary)

    if (not dry_run) and do_prune:
        # drop old data
        KEEP_DAYS = 90
        old_limit = time_now - KEEP_DAYS * 86400

        for TABLE in (damage_protection_table,):
            if verbose: print 'pruning', TABLE
            cur.execute("DELETE FROM "+sql_util.sym(TABLE)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', TABLE
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(TABLE))
            con.commit()
