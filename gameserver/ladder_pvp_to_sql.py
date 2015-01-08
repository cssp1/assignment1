#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_ladder_pvp" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinETL
import SpinNoSQL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def ladder_pvp_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('event_name', 'VARCHAR(255) NOT NULL'),
                       ('defender_id', 'INT4'),
                       ('is_revenge', 'INT1'),
                       ('battle_streak_ladder', 'INT4'),
                       ('is_victory', 'INT1'),
                       ('duration', 'INT4'),
                       ('base_damage', 'FLOAT4'),
                       ('attacker_stars', 'INT1'),
                       ('attacker_res', 'INT8'),
                       ('defender_res', 'INT8'),
                       ('attacker_res_delta', 'INT8'),
                       ('defender_res_delta', 'INT8'),
                       ('attacker_pts', 'INT4'),
                       ('defender_pts', 'INT4'),
                       ('attacker_pts_delta', 'INT4'),
                       ('defender_pts_delta', 'INT4'),
                       ('attacker_pts_reward_win', 'INT4'),
                       ('attacker_pts_risk_loss', 'INT4'),
                       ('defender_pts_reward_win', 'INT4'),
                       ('defender_pts_risk_loss', 'INT4'),
                       ],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }

SUMFIELDS = ('duration', 'base_damage', 'attacker_stars',
             'attacker_res', 'defender_res',
             'attacker_res_delta', 'defender_res_delta',
             'attacker_pts', 'defender_pts',
             'attacker_pts_delta', 'defender_pts_delta',
             'attacker_pts_reward_win', 'attacker_pts_risk_loss',
             'defender_pts_reward_win', 'defender_pts_risk_loss')

def ladder_pvp_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('event_name', 'VARCHAR(255) NOT NULL'),
                       ('is_revenge', 'INT1'),
                       ('battle_streak_ladder', 'INT4'),
                       ('n_victories', 'INT8'),
                       ('victory_ratio', 'FLOAT4'),
                       ('n_events', 'INT8'),
                       ('most_active_n_events', 'INT8'),
                       ('most_active_total_duration', 'INT8'),
                       ('unique_players', 'INT8')] + \
                      sum([[(s+'_total', 'FLOAT4'),
                            (s+'_min', 'FLOAT4'),
                            (s+'_max', 'FLOAT4'),
                            (s+'_avg', 'FLOAT4')] for s in \
                           SUMFIELDS], []),
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
    ladder_pvp_table = cfg['table_prefix']+game_id+'_ladder_pvp'
    ladder_pvp_daily_summary_table = cfg['table_prefix']+game_id+'_ladder_pvp_daily_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, ladder_pvp_table, ladder_pvp_schema(sql_util))
    sql_util.ensure_table(cur, ladder_pvp_daily_summary_table, ladder_pvp_summary_schema(sql_util, 'day'))
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur.execute("SELECT time FROM "+sql_util.sym(ladder_pvp_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_days = set()

    qs = {'time':{'$gt':start_time, '$lt':end_time}}

    for row in nosql_client.log_buffer_table('log_ladder_pvp').find(qs):
        if row['sum'].get('developer',False): continue # skip events by developers

        if 'outcome' in row:
            row['is_victory'] = (row['outcome'] == 'victory')
        if 'ladder_state' in row:
            row['is_revenge'] = row['ladder_state'].get('is_revenge', False)
            row['attacker_pts_reward_win'] = row['ladder_state']['points']['victory'][str(row['user_id'])]
            row['attacker_pts_risk_loss'] = row['ladder_state']['points']['defeat'][str(row['user_id'])]
            if 'defender_id' in row:
                row['defender_pts_reward_win'] = row['ladder_state']['points']['victory'][str(row['defender_id'])]
                row['defender_pts_risk_loss'] = row['ladder_state']['points']['defeat'][str(row['defender_id'])]

        for RESFIELD in ('attacker_res', 'defender_res', 'attacker_res_delta', 'defender_res_delta'):
            # collapse all fungible resources into a single total (for now - will need separate treatment of res3!)
            if RESFIELD in row:
                if type(row[RESFIELD]) is dict:
                    row[RESFIELD] = sum(row[RESFIELD].itervalues(), 0)

        keyvals = [('time',row['time']),
                   ('user_id',row['user_id'])] + \
                  sql_util.parse_brief_summary(row['sum']) + \
                  [(FIELD, row.get(FIELD,None)) for FIELD in ('event_name','defender_id','is_revenge','battle_streak_ladder','is_victory') + SUMFIELDS]

        if not dry_run:
            sql_util.do_insert(cur, ladder_pvp_table, keyvals)
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
    cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(ladder_pvp_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        ladder_pvp_range = (rows[0]['min_time'], rows[0]['max_time'])
    else:
        ladder_pvp_range = None

    def update_ladder_pvp_summary(cur, table, interval, day_start, dt):
        temp_table = cfg['table_prefix']+game_id+'_ladder_pvp_extreme_users_temp'
        cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(temp_table))

        try:
            # note: this can't actually be a TEMPORARY table because we need to refer to it more than once in the following queries
            sql_util.ensure_table(cur, temp_table, {'fields':[('user_id', 'INT4 NOT NULL')] + \
                                                             sql_util.summary_out_dimensions() + \
                                                             [('event_name', 'VARCHAR(255) NOT NULL'),
                                                              ('is_revenge', 'INT1'),
                                                              ('battle_streak_ladder', 'INT4'),
                                                              ('n_events', 'INT8'),
                                                              ('total_duration', 'INT8')],
                                                    'indices':{'master':{'keys':[('frame_platform','ASC'),('country_tier','ASC'),('townhall_level','ASC'),('spend_bracket','ASC'),('event_name','ASC'),('is_revenge','ASC'),('battle_streak_ladder','ASC')]}}
                                                    }, temporary = False)

            # get the max number of events of each type per player (chiefly to determine the max number and duration of battles)
            # note: is_revenge not used
            cur.execute("INSERT INTO "+sql_util.sym(temp_table) + \
                        "SELECT a.user_id AS user_id," + \
                        "       a.frame_platform AS frame_platform," + \
                        "       a.country_tier AS country_tier," + \
                        "       MAX(a.townhall_level) AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("MAX(a.prev_receipts)")+" AS spend_bracket," + \
                        "       a.event_name AS event_name," + \
                        "       NULL AS is_revenge," + \
                        "       a.battle_streak_ladder AS battle_streak_ladder," + \
                        "       COUNT(1) AS n_events," + \
                        "       SUM(a.duration) AS total_duration " + \
                        "FROM " + sql_util.sym(ladder_pvp_table) + " a " + \
                        "WHERE a.time >= %s AND a.time < %s AND a.battle_streak_ladder IS NOT NULL " + \
                        "GROUP BY user_id, event_name, a.battle_streak_ladder ORDER BY NULL",
                        [day_start, day_start+dt])

            # second pass with battle_streak_ladder = NULL
            cur.execute("INSERT INTO "+sql_util.sym(temp_table) + \
                        "SELECT a.user_id AS user_id," + \
                        "       a.frame_platform AS frame_platform," + \
                        "       a.country_tier AS country_tier," + \
                        "       MAX(a.townhall_level) AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("MAX(a.prev_receipts)")+" AS spend_bracket," + \
                        "       a.event_name AS event_name," + \
                        "       NULL AS is_revenge," + \
                        "       NULL AS battle_streak_ladder," + \
                        "       COUNT(1) AS n_events," + \
                        "       SUM(a.duration) AS total_duration " + \
                        "FROM " + sql_util.sym(ladder_pvp_table) + " a " + \
                        "WHERE a.time >= %s AND a.time < %s " + \
                        "GROUP BY user_id, event_name ORDER BY NULL",
                        [day_start, day_start+dt])
            con.commit()

            # note: is_revenge not used for the per-streak rows
            cur.execute("INSERT INTO "+sql_util.sym(ladder_pvp_daily_summary_table) + \
                        "SELECT %s AS "+interval+"," + \
                        "       a.frame_platform AS frame_platform," + \
                        "       a.country_tier AS country_tier," + \
                        "       a.townhall_level AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("a.prev_receipts")+" AS spend_bracket," + \
                        "       a.event_name AS event_name," + \
                        "       NULL AS is_revenge," + \
                        "       a.battle_streak_ladder AS battle_streak_ladder," + \
                        "       SUM(IF(a.is_victory,1,0)) AS n_victories," + \
                        "       SUM(IF(a.is_victory,1,0))/SUM(1) AS victory_ratio," + \
                        "       COUNT(1) AS n_events," + \
                        "       (SELECT MAX(b.n_events) FROM "+sql_util.sym(temp_table)+" b WHERE b.frame_platform = a.frame_platform AND b.country_tier = a.country_tier AND b.townhall_level = a.townhall_level AND b.spend_bracket = "+sql_util.encode_spend_bracket("a.prev_receipts")+" AND b.event_name = event_name AND b.battle_streak_ladder = a.battle_streak_ladder) AS most_active_n_events, " + \
                        "       (SELECT MAX(b.total_duration) FROM "+sql_util.sym(temp_table)+" b WHERE b.frame_platform = a.frame_platform AND b.country_tier = a.country_tier AND b.townhall_level = a.townhall_level AND b.spend_bracket = "+sql_util.encode_spend_bracket("a.prev_receipts")+" AND b.event_name = event_name AND b.battle_streak_ladder = a.battle_streak_ladder) AS most_active_total_duration, " + \
                        "       COUNT(DISTINCT(a.user_id)) AS unique_players " + \
                        "".join((",       SUM(IFNULL(a."+s+",0)) AS "+s+"_total," + \
                                 "       MIN(a."+s+") AS "+s+"_min," + \
                                 "       MAX(a."+s+") AS "+s+"_max," + \
                                 "       AVG(a."+s+") AS "+s+"_avg ") for s in SUMFIELDS) + \
                        "FROM " + sql_util.sym(ladder_pvp_table) + " a " + \
                        "WHERE a.time >= %s AND a.time < %s AND a.battle_streak_ladder IS NOT NULL " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, event_name, battle_streak_ladder ORDER BY NULL",
                        [day_start, day_start, day_start+dt])

            # add extra rows with battle_streak_ladder = NULL meaning "any battle_streak_ladder" and is_revenge = NULL meaning "either revenge or non-revenge battle"
            # note: this means that summary reports have to explicitly include or exclude based on battle_streak_ladder being NULL or non-NULL
            cur.execute("INSERT INTO "+sql_util.sym(ladder_pvp_daily_summary_table) + \
                        "SELECT %s AS "+interval+"," + \
                        "       a.frame_platform AS frame_platform," + \
                        "       a.country_tier AS country_tier," + \
                        "       a.townhall_level AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("a.prev_receipts")+" AS spend_bracket," + \
                        "       a.event_name AS event_name," + \
                        "       NULL AS is_revenge," + \
                        "       NULL AS battle_streak_ladder," + \
                        "       SUM(IF(a.is_victory,1,0)) AS n_victories," + \
                        "       SUM(IF(a.is_victory,1,0))/SUM(1) AS victory_ratio," + \
                        "       COUNT(1) AS n_events," + \
                        "       (SELECT MAX(b.n_events) FROM "+sql_util.sym(temp_table)+" b WHERE b.frame_platform = a.frame_platform AND b.country_tier = a.country_tier AND b.townhall_level = a.townhall_level AND b.spend_bracket = "+sql_util.encode_spend_bracket("a.prev_receipts")+" AND b.event_name = a.event_name AND b.battle_streak_ladder IS NULL) AS most_active_n_events, " + \
                        "       (SELECT MAX(b.total_duration) FROM "+sql_util.sym(temp_table)+" b WHERE b.frame_platform = a.frame_platform AND b.country_tier = a.country_tier AND b.townhall_level = a.townhall_level AND b.spend_bracket = "+sql_util.encode_spend_bracket("a.prev_receipts")+" AND b.event_name = a.event_name AND b.battle_streak_ladder IS NULL) AS most_active_total_duration, " + \
                        "       COUNT(DISTINCT(a.user_id)) AS unique_players " + \
                        "".join((",       SUM(IFNULL(a."+s+",0)) AS "+s+"_total," + \
                                 "       MIN(a."+s+") AS "+s+"_min," + \
                                 "       MAX(a."+s+") AS "+s+"_max," + \
                                 "       AVG(a."+s+") AS "+s+"_avg ") for s in SUMFIELDS) + \
                        "FROM " + sql_util.sym(ladder_pvp_table) + " a " + \
                        "WHERE a.time >= %s AND a.time < %s " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, event_name ORDER BY NULL",
                        [day_start, day_start, day_start+dt])

        finally:
            cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(temp_table))

    SpinETL.update_summary(sql_util, con, cur, ladder_pvp_daily_summary_table, affected_days, ladder_pvp_range, 'day', 86400,
                           verbose = verbose, resummarize_tail = 86400, execute_func = update_ladder_pvp_summary)

    if (not dry_run) and do_prune:
        # drop old data
        KEEP_DAYS = 90
        old_limit = time_now - KEEP_DAYS * 86400

        for TABLE in (ladder_pvp_table,):
            if verbose: print 'pruning', TABLE
            cur.execute("DELETE FROM "+sql_util.sym(TABLE)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', TABLE
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(TABLE))
            con.commit()
