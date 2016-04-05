#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AFTER dumping "battles", "ai_bases/analytics_tags" and "store" table (for recent gamebucks spend), compute derived risk/reward analysis

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinSQLUtil
import SpinParallel
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())

def battles_risk_reward_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24)'), # NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [
               ('base_region', 'VARCHAR(16)'),
               ('base_type', 'VARCHAR(16) NOT NULL'),
               ('player_id', 'INT4 NOT NULL'),
               ('opponent_id', 'INT4 NOT NULL'),
               ('base_template', 'VARCHAR(32)'),
               ('battle_type', 'VARCHAR(9) NOT NULL'),
               ('battle_streak_ladder', 'INT4'),
               ('analytics_tag', 'VARCHAR(32)'),
#               ('player_townhall_level', 'INT1 NOT NULL'), # in summary dimensions
               ('loot_items_value', 'INT4 NOT NULL'),
               ('consumed_items_value', 'INT4 NOT NULL'),
               ('loot_iron_amount', 'INT4 NOT NULL'),
               ('loot_iron_value', 'INT4 NOT NULL'),
               ('loot_water_amount', 'INT4 NOT NULL'),
               ('loot_water_value', 'INT4 NOT NULL'),
               ('loot_res3_amount', 'INT4 NOT NULL'),
               ('loot_res3_value', 'INT4 NOT NULL'),
               ('damage_iron_amount', 'INT4 NOT NULL'),
               ('damage_iron_value', 'INT4 NOT NULL'),
               ('damage_water_amount', 'INT4 NOT NULL'),
               ('damage_water_value', 'INT4 NOT NULL'),
               ('damage_res3_amount', 'INT4 NOT NULL'),
               ('damage_res3_value', 'INT4 NOT NULL'),
               ('damage_time_sec', 'INT4 NOT NULL'),
               ('damage_time_value', 'INT4 NOT NULL'),
               ('is_victory', sql_util.bit_type()),
               ('auto_resolved', sql_util.bit_type()),
               ('duration', 'INT4 NOT NULL'),
               ('gamebucks_spent_5min', 'INT4 NOT NULL'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]},
                'by_battle_id': {'unique': True, 'keys': [('battle_id','ASC')]}}
    }

def battles_risk_reward_summary_schema(sql_util, interval_name): return {
    # we use fewer dimensions for the hourly summary to reduce DB load, and also restrict it to townhall_level 5+ only
    'fields': [(interval_name, 'INT8 NOT NULL')] + \
              (sql_util.summary_out_dimensions() if interval_name != 'hour' else [('townhall_level','INT4')]) + \
              [('opponent_id', 'INT4')] + \
              ([('base_region', 'VARCHAR(16)')] if interval_name != 'hour' else []) + \
              [('base_type', 'VARCHAR(8)'),
               ('base_template', 'VARCHAR(32)'),
               ('battle_type', 'VARCHAR(9)')] + \
              ([('battle_streak_ladder', 'INT4')] if interval_name != 'hour' else []) + \
              [('analytics_tag', 'VARCHAR(32)'),
               ('n_unique_players', 'INT4'),
               ('n_battles', 'INT4'),
               ('n_victories', 'INT4'),
               ('total_duration', 'INT8'),
               ('total_gamebucks_spent_5min', 'INT8'),
               ('loot_items_value', 'INT8'),
               ('consumed_items_value', 'INT8'),
               ('loot_res_value', 'INT8'), # iron + water + res3
               ('loot_res3_value', 'INT8'), # res3 only
               ('loot_iron_water_amount', 'INT8'), # iron + water only
               ('loot_iron_water_amount_10th', 'INT8'), # iron + water only, 10th percentile
               ('loot_iron_water_amount_90th', 'INT8'), # iron + water only, 90th percentile
               ('damage_res_value', 'INT8'),
               ('damage_iron_water_amount', 'INT8'), # iron + water only
               ('damage_iron_water_amount_10th', 'INT8'), # iron + water only, 10th percentile
               ('damage_iron_water_amount_90th', 'INT8'), # iron + water only, 90th percentile
               ('damage_time_value', 'INT8'),
               ('total_risk', 'INT8'),
               ('total_reward', 'INT8'),
               ('total_profit', 'INT8'),
               ],
    'indices': {'by_day': {'unique': False, 'keys': [(interval_name,'ASC')]}}
    }

# same as above, but do not group by opponent_id, base_region, base_template, battle_type, or battle_streaks
def battles_risk_reward_summary_combined_schema(sql_util, interval_name): return {
    'fields': [(interval_name, 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('base_type', 'VARCHAR(8)'),
               ('analytics_tag', 'VARCHAR(32)'),
               ('n_unique_players', 'INT4'),
               ('n_battles', 'INT4'),
               ('n_victories', 'INT4'),
               ('total_duration', 'INT8'),
               ('total_gamebucks_spent_5min', 'INT8'),
               ('loot_items_value', 'INT8'),
               ('consumed_items_value', 'INT8'),
               ('loot_res_value', 'INT8'), # iron + water + res3
               ('loot_res3_value', 'INT8'), # res3 only
               ('loot_iron_water_amount', 'INT8'), # iron + water only
               ('loot_iron_water_amount_10th', 'INT8'), # iron + water only, 10th percentile
               ('loot_iron_water_amount_90th', 'INT8'), # iron + water only, 90th percentile
               ('damage_res_value', 'INT8'),
               ('damage_iron_water_amount', 'INT8'), # iron + water only
               ('damage_iron_water_amount_10th', 'INT8'), # iron + water only, 10th percentile
               ('damage_iron_water_amount_90th', 'INT8'), # iron + water only, 90th percentile
               ('damage_time_value', 'INT8'),
               ('total_risk', 'INT8'),
               ('total_reward', 'INT8'),
               ('total_profit', 'INT8'),
               ],
    'indices': {'by_day': {'unique': False, 'keys': [(interval_name,'ASC')]}}
    }

def week_of(week_origin, unix_time):
    return week_origin + 7*86400*((unix_time - week_origin)//(7*86400))

def do_slave(input):
    sql_util = SpinSQLUtil.MySQLUtil()
    if not input['verbose']: sql_util.disable_warnings()
    cfg = SpinConfig.get_mysql_config(input['game_id']+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    cur = con.cursor(MySQLdb.cursors.DictCursor)

    # tell MySQL it's OK to be less careful about isolating batches.
    # we manually enforce non-overlapping time ranges, so we don't need the database to guarantee isolation.
    # (this prevents massive deadlock problems).
    cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")

    deadlocks = 0
    while True:
        try:
            ret = eval_batch(sql_util, con, cur, input['game_id'], input['week_origin'], input['battles_table'], input['battles_risk_reward_table'], input['start'], input['end'], input['verbose'])
            con.commit()
            return ret
        except MySQLdb.OperationalError as e:
            if e.args[0] == 1213: # deadlock
                deadlocks += 1
                con.rollback()
                if input['verbose']: print >>sys.stderr, 'DEADLOCK', deadlocks, '- restarting after a pause...'
                time.sleep(5) # don't busy-wait here
                continue
            else:
                raise

def eval_batch(sql_util, con, cur, game_id, week_origin, battles_table, battles_risk_reward_table, start, end, verbose):
    affected_hours = set()
    affected_days = set()
    affected_weeks = set()
    if verbose: print >>sys.stderr, 'evaluating risk/reward on battles for interval', start, end, \
       time.strftime('%Y%m%d %H:%M', time.gmtime(start)), \
       time.strftime('%Y%m%d %H:%M', time.gmtime(end))

    # some gymnastics are required to avoid MySQL InnoDB record lock deadlocks when running lots of deletes and inserts in parallel
    # this is just a fancy way of writing "DELETE FROM battles_risk_reward WHERE time >= start and time < end"
    # it avoids deadlocks by reducing the time window that the "by_time" index must by locked from the entire delete to just a quick scan
    del_query = "DELETE t1 FROM "+sql_util.sym(battles_risk_reward_table)+" t1 INNER JOIN (SELECT t3.battle_id AS bid FROM "+sql_util.sym(battles_risk_reward_table)+(" t3 WHERE t3.time >= %s AND t3.time < %s) t2 ON t1.battle_id = t2.bid" % (start,end))
    cur.execute(del_query)

    # get number of battles we're about to process
    cur.execute("SELECT COUNT(1) AS n FROM "+sql_util.sym(battles_table)+" WHERE time >= 1405859224 AND time >= %s AND time < %s", [start, end])
    rows = cur.fetchall()
    n = rows[0]['n']
    if verbose: print >>sys.stderr, n, 'battles to evaluate...'
    if n <= 0: return {'n': 0}

    query ="INSERT INTO "+sql_util.sym(battles_risk_reward_table)+""" SELECT
            battle_id,
            time,
            active_player_frame_platform, active_player_country_tier, active_player_townhall_level, active_player_prev_receipts,
            base_region,
            base_type,
            active_player_id,
            active_opponent_id,
            base_template,
            IF(base_type='quarry', 'pvp', IF(attacker_type = 'ai' OR defender_type = 'ai', IF(active_player_id = attacker_id, 'ai_base', 'ai_attack'), 'pvp')) AS battle_type,
            battle_streak_ladder,
            IFNULL(get_analytics_tag(base_type, base_template, active_opponent_id, time),
                   NULL -- (SELECT ai_bases.ui_name FROM $GAME_ID_ai_bases ai_bases WHERE ai_bases.user_id = active_opponent_id)
                   ) AS analytics_tag,
            IFNULL((SELECT SUM(item_value(loot.item, loot.stack, active_player_townhall_level, active_player_prev_receipts)) FROM $GAME_ID_battle_loot loot WHERE loot.battle_id = battles.battle_id),0) AS loot_items_value,
            IFNULL((SELECT SUM(-1*item_value(items.item, items.stack, active_player_townhall_level, active_player_prev_receipts)) FROM $GAME_ID_battle_items items WHERE items.battle_id = battles.battle_id AND items.user_id = active_player_id),0) AS consumed_items_value,

            IFNULL(IF(active_player_id = attacker_id, `loot:iron`, -1*`loot:iron_lost`),0) AS loot_iron_amount,
            iron_value(IFNULL(IF(active_player_id = attacker_id, `loot:iron`, -1*`loot:iron_lost`), 0), active_player_townhall_level, active_player_prev_receipts) AS loot_iron_value,
            IFNULL(IF(active_player_id = attacker_id, `loot:water`, -1*`loot:water_lost`),0) AS loot_water_amount,
            water_value(IFNULL(IF(active_player_id = attacker_id, `loot:water`, -1*`loot:water_lost`), 0), active_player_townhall_level, active_player_prev_receipts) AS loot_water_value,
            IFNULL(IF(active_player_id = attacker_id, `loot:res3`, -1*`loot:res3_lost`),0) AS loot_res3_amount,
            res3_value(IFNULL(IF(active_player_id = attacker_id, `loot:res3`, -1*`loot:res3_lost`),0), active_player_townhall_level, active_player_prev_receipts) AS loot_res3_value,

            IFNULL((SELECT SUM(-1*damage.iron) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0) AS damage_iron_amount,
            iron_value(IFNULL((SELECT SUM(-1*damage.iron) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0), active_player_townhall_level, active_player_prev_receipts) AS damage_iron_value,
            IFNULL((SELECT SUM(-1*damage.water) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0) AS damage_water_amount,
            water_value(IFNULL((SELECT SUM(-1*damage.water) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0), active_player_townhall_level, active_player_prev_receipts) AS damage_water_value,
            IFNULL((SELECT SUM(-1*damage.res3) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0) AS damage_res3_amount,
            res3_value(IFNULL((SELECT SUM(-1*damage.res3) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0), active_player_townhall_level, active_player_prev_receipts) AS damage_res3_value,

            -- note: value repair time for buildings 0.1x as much as repair time for units, because buildings can repair in parallel but units cannot.
            IFNULL((SELECT SUM(IF(damage.mobile,1,0.1)*damage.time) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0) + duration AS damage_time_sec, -- include battle duration as damage time!
            time_price(-1*(IFNULL((SELECT SUM(IF(damage.mobile,1,0.1)*damage.time) FROM $GAME_ID_battle_damage damage WHERE damage.battle_id = battles.battle_id AND damage.user_id = active_player_id),0) + duration)) AS damage_time_value,

            IF(active_player_outcome = 'victory', 1, 0) AS is_victory,
            auto_resolved AS auto_resolved,
            duration AS duration,

            -- count all gamebucks spent by this player within +/- 5 minutes of the attack
            IFNULL((SELECT SUM(price) FROM $GAME_ID_store store
                    WHERE store.time >= battles.time-300
                    AND store.time >= $START-300
                    AND store.time < battles.time+battles.duration+300
                    AND store.time < $END+600+300
                    AND store.currency='gamebucks' AND store.user_id = active_player_id),0) AS gamebucks_spent_5min
            FROM """.replace("$GAME_ID",game_id).replace("$START",'%d'%start).replace("$END",'%d'%end)+sql_util.sym(battles_table)+" battles "+\
    ("WHERE time >= 1405859224 AND time >= %d AND time < %d GROUP BY time, battle_id ORDER BY time ASC" % (start, end))
    #if verbose: print >>sys.stderr, query
    cur.execute(query)

    assert end-start <= 3600
    affected_hours.add(3600*(start//3600))
    affected_days.add(86400*(start//86400))
    affected_weeks.add(week_of(week_origin, start))

    if verbose: print >>sys.stderr, n, 'inserted'

    return {'n': n,
            'affected_hours': list(affected_hours),
            'affected_days': list(affected_days),
            'affected_weeks': list(affected_weeks)}

if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    game_id = SpinConfig.game()
    commit_interval = 100
    parallel = 1
    verbose = True
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','parallel='])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True
        elif key == '--parallel': parallel = int(val)

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('battle_risk_reward_to_sql-%s' % game_id):

        battles_table = cfg['table_prefix']+game_id+'_battles'
        battles_risk_reward_table = cfg['table_prefix']+game_id+'_battles_risk_reward'
        battles_risk_reward_hourly_summary_table = cfg['table_prefix']+game_id+'_battles_risk_reward_cc5plus_hourly_summary'
        battles_risk_reward_daily_summary_table = cfg['table_prefix']+game_id+'_battles_risk_reward_daily_summary'
        battles_risk_reward_weekly_summary_table = cfg['table_prefix']+game_id+'_battles_risk_reward_weekly_summary'
        battles_risk_reward_daily_summary_combined_table = cfg['table_prefix']+game_id+'_battles_risk_reward_daily_summary_combined'
        battles_risk_reward_weekly_summary_combined_table = cfg['table_prefix']+game_id+'_battles_risk_reward_weekly_summary_combined'

        cur = con.cursor(MySQLdb.cursors.DictCursor)

        # prepare for big GROUP_CONCAT() percentile queries (MySQL-specific)
        cur.execute("SET @@session.group_concat_max_len = @@global.max_allowed_packet")

        for table, schema in ((battles_risk_reward_table, battles_risk_reward_schema(sql_util)),
                              (battles_risk_reward_hourly_summary_table, battles_risk_reward_summary_schema(sql_util, 'hour')),
                              (battles_risk_reward_daily_summary_table, battles_risk_reward_summary_schema(sql_util, 'day')),
                              (battles_risk_reward_weekly_summary_table, battles_risk_reward_summary_schema(sql_util, 'week')),
                              (battles_risk_reward_daily_summary_combined_table, battles_risk_reward_summary_combined_schema(sql_util, 'day')),
                              (battles_risk_reward_weekly_summary_combined_table, battles_risk_reward_summary_combined_schema(sql_util, 'week')),
                               ):
            sql_util.ensure_table(cur, table, schema)
        con.commit()

        # find most recent already-evaluated battle
        # assume that if we have one battle from a given second, we have all from that second
        start_time = -1
        end_time = time_now - 30*60 # skip entries too close to "now" (max battle length) to ensure all battles that *started* in a given second have all arrived
        cur.execute("SELECT time FROM "+sql_util.sym(battles_risk_reward_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])

        if start_time < 0: # no battles converted yet, start with first battle in battles table
            cur.execute("SELECT MIN(time) AS time FROM "+sql_util.sym(battles_table))
            rows = cur.fetchall()
            if rows:
                start_time = rows[0]['time']

        if verbose:
            print 'start_time', start_time, 'end_time', end_time

        total = 0
        affected_hours = set()
        affected_days = set()
        affected_weeks = set()

        tasks = [{'game_id': game_id, 'week_origin': gamedata['matchmaking']['week_origin'],
                  'battles_table': battles_table, 'battles_risk_reward_table': battles_risk_reward_table,
                  'start': hour_start, 'end': hour_start+3600, 'verbose': verbose} \
                 for hour_start in xrange(3600*(start_time//3600), 3600*(end_time//3600+1), 3600)]
        if parallel <= 1:
            outputs = [do_slave(task) for task in tasks]
        else:
            outputs = SpinParallel.go(tasks, [sys.argv[0], '--slave'], on_error='break', nprocs=parallel, verbose=False)

        for output in outputs:
            total += output['n']
            if output['n'] > 0:
                for x in output['affected_hours']: affected_hours.add(x)
                for x in output['affected_days']: affected_days.add(x)
                for x in output['affected_weeks']: affected_weeks.add(x)

        con.commit()
        if verbose: print total, 'total inserted', 'affecting', len(affected_hours), 'hour(s)', len(affected_days), 'day(s)', len(affected_weeks), 'week(s)'

        # update summary tables
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(battles_risk_reward_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            battles_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            battles_range = None

        for summary_table, affected, interval, dt, origin in ((battles_risk_reward_hourly_summary_table, affected_hours, 'hour', 3600, 0),
                                                              (battles_risk_reward_daily_summary_table, affected_days, 'day', 86400, 0),
                                                              (battles_risk_reward_weekly_summary_table, affected_weeks, 'week', 7*86400, gamedata['matchmaking']['week_origin'])):

            cur.execute("SELECT MIN("+sql_util.sym(interval)+") AS begin, MAX("+sql_util.sym(interval)+") AS end FROM " + sql_util.sym(summary_table))
            rows = cur.fetchall()
            if rows and rows[0] and rows[0]['begin'] and rows[0]['end']:
                # we already have summary data - update it incrementally
                if battles_range: # fill in any missing trailing summary data
                    source_days = sorted(affected.union(set(xrange(dt*((rows[0]['end']-origin)//dt)+origin, dt*((battles_range[1]-origin)//dt + 1)+origin, dt))))
                else:
                    source_days = sorted(list(affected))
            else:
                # recreate entire summary
                if battles_range:
                    source_days = range(dt*((battles_range[0]-origin)//dt)+origin, dt*((battles_range[1]-origin)//dt + 1)+origin, dt)
                else:
                    source_days = None

            if source_days:
                for day_start in source_days:
                    if verbose: print 'updating', summary_table, 'at', day_start, time.strftime('%Y%m%d %H:%M', time.gmtime(day_start))

                    cur.execute("DELETE FROM "+sql_util.sym(summary_table)+" WHERE "+sql_util.sym(interval)+" >= %s AND "+sql_util.sym(interval)+" < %s+%s",
                                [day_start,day_start,dt])

                    cur.execute("INSERT INTO "+sql_util.sym(summary_table) + " " + \
                                "SELECT %s*FLOOR((time-%s)/(1.0*%s)) + %s AS "+sql_util.sym(interval)+"," + \
                                ("      frame_platform," if interval != 'hour' else "") + \
                                ("      country_tier," if interval != 'hour' else "") + \
                                "       townhall_level," + \
                                ("      "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," if interval != 'hour' else "") + \
                                "       IF(battle_type='pvp',-1,opponent_id) AS opponent_id," + \
                                ("       IF(SUBSTRING(base_region FROM 1 FOR 6) = 'ladder','ladder',base_region) AS base_region," if interval != 'hour' else "") + \
                                "       base_type," + \
                                "       base_template," + \
                                "       battle_type," + \
                                ("       battle_streak_ladder AS battle_streak_ladder," if interval != 'hour' else "") + \
                                "       analytics_tag," + \
                                "       COUNT(DISTINCT(player_id)) AS n_unique_players," + \
                                "       SUM(1) AS n_battles," + \
                                "       SUM(IF(is_victory,1,0)) AS n_victories," + \
                                "       SUM(rw.duration) AS total_duration," + \
                                "       SUM(gamebucks_spent_5min) AS total_gamebucks_spent_5min," + \
                                "       SUM(loot_items_value) AS loot_items_value," + \
                                "       SUM(consumed_items_value) AS consumed_items_value," + \
                                "       SUM(loot_iron_value + loot_water_value + loot_res3_value) AS loot_res_value," + \
                                "       SUM(loot_res3_value) AS loot_res3_value," + \
                                "       SUM(loot_iron_amount + loot_water_amount) AS loot_iron_water_amount," + \
                                sql_util.percentile('IFNULL(loot_iron_amount,0)+IFNULL(loot_water_amount,0)', 0.1)+" AS loot_iron_water_amount_10th," + \
                                sql_util.percentile('IFNULL(loot_iron_amount,0)+IFNULL(loot_water_amount,0)', 0.9)+" AS loot_iron_water_amount_90th," + \
                                "       SUM(damage_iron_value + damage_water_value + damage_res3_value) AS damage_res_value," + \
                                "       SUM(damage_iron_amount + damage_water_amount) AS damage_iron_water_amount," + \
                                sql_util.percentile('IFNULL(damage_iron_amount,0)+IFNULL(damage_water_amount,0)', 0.1)+" AS damage_iron_water_amount_10th," + \
                                sql_util.percentile('IFNULL(damage_iron_amount,0)+IFNULL(damage_water_amount,0)', 0.9)+" AS damage_iron_water_amount_90th," + \
                                "       SUM(damage_time_value) AS damage_time_value," + \
                                "       -1 * SUM(consumed_items_value + IF(loot_iron_value<0,loot_iron_value,0) + IF(loot_water_value<0,loot_water_value,0) + IF(loot_res3_value<0,loot_res3_value,0) + damage_iron_value + damage_water_value + damage_res3_value + damage_time_value) AS total_risk, -- negate to make it display positive\n" + \
                                "       SUM(loot_items_value + IF(loot_iron_value>0,loot_iron_value,0) + IF(loot_water_value>0,loot_water_value,0) + IF(loot_res3_value>0,loot_res3_value,0)) AS total_reward," + \
                                "       SUM(loot_items_value + IF(loot_iron_value>0,loot_iron_value,0) + IF(loot_water_value>0,loot_water_value,0) + IF(loot_res3_value>0,loot_res3_value,0)) + SUM(consumed_items_value + IF(loot_iron_value<0,loot_iron_value,0) + IF(loot_water_value<0,loot_water_value,0) + IF(loot_res3_value<0,loot_res3_value,0) + damage_iron_value + damage_water_value + damage_res3_value + damage_time_value) AS total_profit " + \
                                "FROM "+sql_util.sym(battles_risk_reward_table)+" rw " + \
                                "WHERE time >= %s AND time < %s+%s AND (base_type IN ('home','hive','quarry') OR SUBSTRING(base_type,1,4) = 'raid') " + \
                                ("" if interval != 'hour' else "AND townhall_level >= 5 ") + \
                                "GROUP BY "+sql_util.sym(interval)+"," + \
                                ("frame_platform, country_tier, townhall_level, spend_bracket, IF(SUBSTRING(base_region FROM 1 FOR 6) = 'ladder','ladder',base_region)," if interval != 'hour' else "townhall_level,") + \
                                "base_type, IF(battle_type='pvp',-1,opponent_id), base_template, battle_type, " + ("battle_streak_ladder, " if interval != 'hour' else "") + "analytics_tag ORDER BY NULL",
                                [dt,origin,dt,origin,
                                 day_start,day_start,dt])

                    con.commit() # one commit per day

            else:
                if verbose: print 'no change to summaries'

        for summary_table, affected, interval, dt, origin in ((battles_risk_reward_daily_summary_combined_table, affected_days, 'day', 86400, 0),
                                                              (battles_risk_reward_weekly_summary_combined_table, affected_weeks, 'week', 7*86400, gamedata['matchmaking']['week_origin'])):

            cur.execute("SELECT MIN("+sql_util.sym(interval)+") AS begin, MAX("+sql_util.sym(interval)+") AS end FROM " + sql_util.sym(summary_table))
            rows = cur.fetchall()
            if rows and rows[0] and rows[0]['begin'] and rows[0]['end']:
                # we already have summary data - update it incrementally
                if battles_range: # fill in any missing trailing summary data
                    source_days = sorted(affected.union(set(xrange(dt*((rows[0]['end']-origin)//dt)+origin, dt*((battles_range[1]-origin)//dt + 1)+origin, dt))))
                else:
                    source_days = sorted(list(affected))
            else:
                # recreate entire summary
                if battles_range:
                    source_days = range(dt*((battles_range[0]-origin)//dt)+origin, dt*((battles_range[1]-origin)//dt + 1)+origin, dt)
                else:
                    source_days = None

            if source_days:
                for day_start in source_days:
                    if verbose: print 'updating', summary_table, 'at', day_start, time.strftime('%Y%m%d %H:%M', time.gmtime(day_start))

                    cur.execute("DELETE FROM "+sql_util.sym(summary_table)+" WHERE "+sql_util.sym(interval)+" >= %s AND "+sql_util.sym(interval)+" < %s+%s",
                                [day_start,day_start,dt])

                    cur.execute("INSERT INTO "+sql_util.sym(summary_table) + " " + \
                                "SELECT %s*FLOOR((time-%s)/(1.0*%s)) + %s AS "+sql_util.sym(interval)+"," + \
                                "       frame_platform," + \
                                "       country_tier," + \
                                "       townhall_level," + \
                                "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," + \
                                "       base_type," + \
                                "       analytics_tag," + \
                                "       COUNT(DISTINCT(player_id)) AS n_unique_players," + \
                                "       SUM(1) AS n_battles," + \
                                "       SUM(IF(is_victory,1,0)) AS n_victories," + \
                                "       SUM(rw.duration) AS total_duration," + \
                                "       SUM(gamebucks_spent_5min) AS total_gamebucks_spent_5min," + \
                                "       SUM(loot_items_value) AS loot_items_value," + \
                                "       SUM(consumed_items_value) AS consumed_items_value," + \
                                "       SUM(loot_iron_value + loot_water_value + loot_res3_value) AS loot_res_value," + \
                                "       SUM(loot_res3_value) AS loot_res3_value," + \
                                "       SUM(loot_iron_amount + loot_water_amount) AS loot_iron_water_amount," + \
                                sql_util.percentile('IFNULL(loot_iron_amount,0)+IFNULL(loot_water_amount,0)', 0.1)+" AS loot_iron_water_amount_10th," + \
                                sql_util.percentile('IFNULL(loot_iron_amount,0)+IFNULL(loot_water_amount,0)', 0.9)+" AS loot_iron_water_amount_90th," + \
                                "       SUM(damage_iron_value + damage_water_value + damage_res3_value) AS damage_res_value," + \
                                "       SUM(damage_iron_amount + damage_water_amount) AS damage_iron_water_amount," + \
                                sql_util.percentile('IFNULL(damage_iron_amount,0)+IFNULL(damage_water_amount,0)', 0.1)+" AS damage_iron_water_amount_10th," + \
                                sql_util.percentile('IFNULL(damage_iron_amount,0)+IFNULL(damage_water_amount,0)', 0.9)+" AS damage_iron_water_amount_90th," + \
                                "       SUM(damage_time_value) AS damage_time_value," + \
                                "       -1 * SUM(consumed_items_value + IF(loot_iron_value<0,loot_iron_value,0) + IF(loot_water_value<0,loot_water_value,0) + IF(loot_res3_value<0,loot_res3_value,0) + damage_iron_value + damage_water_value + damage_res3_value + damage_time_value) AS total_risk, -- negate to make it display positive\n" + \
                                "       SUM(loot_items_value + IF(loot_iron_value>0,loot_iron_value,0) + IF(loot_water_value>0,loot_water_value,0) + IF(loot_res3_value>0,loot_res3_value,0)) AS total_reward," + \
                                "       SUM(loot_items_value + IF(loot_iron_value>0,loot_iron_value,0) + IF(loot_water_value>0,loot_water_value,0) + IF(loot_res3_value>0,loot_res3_value,0)) + SUM(consumed_items_value + IF(loot_iron_value<0,loot_iron_value,0) + IF(loot_water_value<0,loot_water_value,0) + IF(loot_res3_value<0,loot_res3_value,0) + damage_iron_value + damage_water_value + damage_res3_value + damage_time_value) AS total_profit " + \
                                "FROM "+sql_util.sym(battles_risk_reward_table)+" rw " + \
                                "WHERE time >= %s AND time < %s+%s AND (base_type IN ('home','hive','quarry') OR SUBSTRING(base_type,1,4) = 'raid') " + \
                                "GROUP BY "+sql_util.sym(interval)+"," + \
                                "frame_platform, country_tier, townhall_level, spend_bracket, base_type, analytics_tag ORDER BY NULL",
                                [dt,origin,dt,origin,
                                 day_start,day_start,dt])

                    con.commit() # one commit per day

            else:
                if verbose: print 'no change to summaries'

        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', battles_risk_reward_table
            cur.execute("DELETE FROM "+sql_util.sym(battles_risk_reward_table)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', battles_risk_reward_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(battles_risk_reward_table))

            con.commit()
