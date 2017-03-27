#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "battles" table from MongoDB to a MySQL database for analytics

# creates tables:
# battles (grows incrementally)
# battle_units (grows incrementally)
# battle_loot (grows incrementally)

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb
import pymongo

gamedata = None
time_now = int(time.time())

def battles_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'),
               ('duration', 'INT4'),
               ('framerate', 'FLOAT4'),
               ('active_player_ping', 'FLOAT4'),
               ('battle_type', 'VARCHAR(8)'), # 'attack', 'defense', or 'raid'
               ('raid_mode', 'VARCHAR(8)'), # 'attack', 'scout', 'guard', etc
               ('active_player_id', 'INT4'),
               ('active_player_apm', 'FLOAT4'),
               #('active_player_townhall_level', 'INT4'), # obsolete - now included in summary dimensions
               ('active_player_outcome', 'VARCHAR(10)')] + \
              sql_util.summary_in_dimensions(prefix='active_player_') + \
              [
               ('active_opponent_id', 'INT4'),
               ('attacker_id', 'INT4'),
               ('attacker_type', 'VARCHAR(5)'), # 'ai' or 'human'
               ('attacker_level', 'INT4'),
               ('attacker_townhall_level', 'INT4'),
               ('attacker_home_base_loc', 'POINT'),
               ('attacker_home_base_loc_x', 'INT4'), # derived from attacker_home_base_loc
               ('attacker_home_base_loc_y', 'INT4'), # derived from attacker_home_base_loc
               ('attacker_outcome', 'VARCHAR(10)'),
               ('attacker_apm', 'FLOAT4'),
               ('attack_type', 'VARCHAR(10)'),
               ('n_battle_stars', 'INT1'),
               ('defender_id', 'INT4'),
               ('defender_type', 'VARCHAR(5)'),
               ('defender_level', 'INT4'),
               ('defender_townhall_level', 'INT4'),
               ('defender_outcome', 'VARCHAR(10)'),
               ('defender_apm', 'FLOAT4'),
               ('base_damage', 'FLOAT4'),
               ('starting_base_damage', 'FLOAT4'),
               ('base_region', 'VARCHAR(16)'),
               ('base_map_loc', 'POINT'),
               ('base_map_loc_x', 'INT4'), # derived from base_map_loc
               ('base_map_loc_y', 'INT4'), # derived from base_map_loc
               ('base_id', 'VARCHAR(16)'),
               ('base_type', 'VARCHAR(8)'),
               ('base_template', 'VARCHAR(32)'),
               ('base_creation_time', 'INT8'),
               ('base_times_attacked', 'INT4'),
               ('base_times_conquered', 'INT4'),
               ('home_base', sql_util.bit_type()),
               ('is_revenge', sql_util.bit_type()),
               ('auto_resolved', sql_util.bit_type()),
               ('battle_streak_ladder', 'INT4'),
               ('loot:xp', 'INT4'),
               ('loot:iron', 'INT4'),
#               ('loot:looted_uncapped_iron', 'INT4'),
               ('loot:water', 'INT4'),
#               ('loot:looted_uncapped_water', 'INT4'),
               ('loot:res3', 'INT4'),
#               ('loot:looted_uncapped_res3', 'INT4'),
               ('loot:trophies_pvp', 'INT4'),
               ('loot:viewing_trophies_pvp', 'INT4'),
               ('loot:trophies_pvv', 'INT4'),
               ('loot:viewing_trophies_pvv', 'INT4'),
               ('loot:iron_lost', 'INT4'),
               ('loot:water_lost', 'INT4'),
               ('loot:res3_lost', 'INT4'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}} # by active_player_id or active_opponent_id ?
    }

def battles_summary_schema(sql_util): return {
    'fields': [('day', 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('opponent_id', 'INT4'),
               ('base_region', 'VARCHAR(16)'),
               ('base_type', 'VARCHAR(8)'),
               ('base_template', 'VARCHAR(32)'),
               ('duration', 'INT8'),
               ('framerate', 'FLOAT4'), # average
               ('framerate_min', 'FLOAT4'), # min
               ('framerate_10th', 'FLOAT4'), # 10th percentile
               ('victory_ratio', 'FLOAT4'),
               ('loot:xp', 'INT8'),
               ('loot:iron', 'INT8'),
               ('loot:water', 'INT8'),
               ('loot:res3', 'INT8'),
               ('loot:iron_lost', 'INT8'),
               ('loot:water_lost', 'INT8'),
               ('loot:res3_lost', 'INT8'),
               ],
    'indices': {'by_day': {'unique': False, 'keys': [('day','ASC')]}}
    }

def battle_units_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24) NOT NULL'),
               ('specname', 'VARCHAR(32) NOT NULL'),
               ('deployed', 'INT4 NOT NULL')],
    'indices': {'by_battle_id': {'keys': [('battle_id','ASC')]}}
    }

def battle_units_summary_schema(sql_util): return {
    'fields': [('day', 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('base_type', 'VARCHAR(8)'),
               ('opponent_id', 'INT4'),
               ('specname', 'VARCHAR(32) NOT NULL'),
               ('deployed', 'INT4 NOT NULL'),
               ('battle_count', 'INT4')],
    'indices': {'by_day': {'unique': False, 'keys': [('day','ASC')]}}
    }

def battle_loot_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24) NOT NULL'),
               ('stack', 'INT4 NOT NULL'),
               ('expire_time', 'INT8'),
               ('item', 'VARCHAR(128) NOT NULL'),
               ],
    'indices': {'by_battle_id': {'keys': [('battle_id','ASC')]}}
    }

def battle_loot_summary_schema(sql_util): return {
    'fields': [('day', 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('base_type', 'VARCHAR(8)'),
               ('opponent_id', 'INT4'),
               ('item', 'VARCHAR(128) NOT NULL'),
               ('stack', 'INT4 NOT NULL')],
    'indices': {'by_day': {'unique': False, 'keys': [('day','ASC')]}}
    }

def battle_items_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24) NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('stack', 'INT4 NOT NULL'),
               ('item', 'VARCHAR(128) NOT NULL'),
               ],
    'indices': {'by_battle_id': {'keys': [('battle_id','ASC')]}}
    }

def battle_damage_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24) NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('mobile', 'TINYINT(1) NOT NULL'),
               ('level', 'INT2 NOT NULL'),
               ('stack', 'INT2 NOT NULL'),
               ('iron', 'INT4 NOT NULL'),
               ('water', 'INT4 NOT NULL'),
               ('res3', 'INT4 NOT NULL'),
               ('time', 'INT4 NOT NULL'), # note: number of seconds to repair - NOT current time
               ('spec', 'VARCHAR(128) NOT NULL'),
               ],
    'indices': {'by_battle_id': {'keys': [('battle_id','ASC')]}}
    }

# iterate through the compressed format in the battle summary
def battle_damage_iter(battle_id, damage):
    for suser_id, damage_dict in damage.iteritems():
        user_id = int(suser_id)
        for key, res_dict in damage_dict.iteritems():
            fields = key.split(':')
            specname = fields[0]
            level = int(fields[1][1:])
            is_mobile = specname in gamedata['units']
            count = res_dict.get('count',1)

            # ignore tiny resource amounts
            if not any(res_dict.get(res,0) >= 2 for res in ('iron','water','res3','time')): continue

            yield battle_id, user_id, is_mobile, level, count, res_dict.get('iron',0), res_dict.get('water',0), res_dict.get('res3',0), res_dict.get('time',0), specname

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 100
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

    # load some server-side-only pieces of gamedata for AI base parsing
    gamedata['ai_bases_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('ai_bases_server.json', override_game_id = game_id)))
    gamedata['quarries_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('quarries_server.json', override_game_id = game_id)))
    gamedata['hives_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('hives_server.json', override_game_id = game_id)))
    gamedata['raids_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('raids_server.json', override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('battles_to_mysql-%s' % game_id):

        battles_table = cfg['table_prefix']+game_id+'_battles'
        battles_summary_table = cfg['table_prefix']+game_id+'_battles_daily_summary'
        battle_units_table = cfg['table_prefix']+game_id+'_battle_units'
        battle_units_summary_table = cfg['table_prefix']+game_id+'_battle_units_daily_summary'
        battle_loot_table = cfg['table_prefix']+game_id+'_battle_loot'
        battle_loot_summary_table = cfg['table_prefix']+game_id+'_battle_loot_daily_summary'
        battle_items_table = cfg['table_prefix']+game_id+'_battle_items'
        battle_damage_table = cfg['table_prefix']+game_id+'_battle_damage'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config((game_id+'test') if SpinConfig.config['game_id'].endswith('test') else game_id))
        cur = con.cursor(MySQLdb.cursors.DictCursor)

        for table, schema in ((battles_table, battles_schema(sql_util)),
                              (battles_summary_table, battles_summary_schema(sql_util)),
                              (battle_units_table, battle_units_schema(sql_util)),
                              (battle_units_summary_table, battle_units_summary_schema(sql_util)),
                              (battle_loot_table, battle_loot_schema(sql_util)),
                              (battle_loot_summary_table, battle_loot_summary_schema(sql_util)),
                              (battle_items_table, battle_items_schema(sql_util)),
                              (battle_damage_table, battle_damage_schema(sql_util)),
                              ):
            sql_util.ensure_table(cur, table, schema)
        con.commit()

        # find most recent already-converted battle
        # assume that if we have one battle from a given second, we have all from that second
        start_time = -1
        end_time = time_now - 30*60 # skip entries too close to "now" (max battle length) to ensure all battles that *started* in a given second have all arrived
        cur.execute("SELECT time FROM "+sql_util.sym(battles_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:
            print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        qs = {'time':{'$gt':start_time, '$lt': end_time}}

        for row in nosql_client.battles_table().find(qs).sort([('time',pymongo.ASCENDING)]):
            battle_id = nosql_client.decode_object_id(row['_id'])

            # add redundant active_player/active_opponent fields
            if 'battle_type' in row:
                if row['battle_type'] in ('attack', 'raid'):
                    human_role = 'attacker'
                    row['active_opponent_id'] = row['defender_id']
                elif row['battle_type'] == 'defense':
                    human_role = 'defender'
                    row['active_opponent_id'] = row['attacker_id']
                else:
                    raise Exception('unknown battle_type '+row['battle_type'])

                for FIELD in ('id','apm','townhall_level','outcome'):
                    k = human_role+'_'+FIELD
                    if k in row:
                        row['active_player_'+FIELD] = row[k]

                # read summary dimensions for the human player
                if human_role+'_summary' in row:
                    if row[human_role+'_summary'].get('developer',False): continue # skip battles by developers
                    row.update(dict(sql_util.parse_brief_summary(row[human_role+'_summary'], prefix = 'active_player_')))

                elif human_role+'_townhall_level' in row:
                    # old battles that have no summary fields may still have townhall level
                    row['active_player_townhall_level'] = row[human_role+'_townhall_level']

            if 'battle_stars' in row:
                row['n_battle_stars'] = sum(row['battle_stars'].itervalues(), 0)

            keys = ['battle_id',]
            values = [battle_id,]
            formats = ['%s',]
            for kname, ktype in battles_schema(sql_util)['fields']:
                path = kname.split(':')
                probe = row
                val = None
                for i in xrange(len(path)):
                    if path[i] not in probe:
                        break
                    elif i == len(path)-1:
                        val = probe[path[i]]
                        break
                    else:
                        probe = probe[path[i]]

                if val is not None:
                    if ktype == 'POINT':
                        keys.append(kname)
                        values.append("POINT(%d %d)" % tuple(val))
                        formats.append("ST_GeomFromText(%s)")
                        keys.append(kname+'_x'); values.append(val[0]); formats.append('%s')
                        keys.append(kname+'_y'); values.append(val[1]); formats.append('%s')
                    else:
                        keys.append(kname)
                        values.append(val)
                        formats.append('%s')

            cur.execute("INSERT INTO " + sql_util.sym(battles_table) + \
                        " ("+', '.join(['`'+x+'`' for x in keys])+")"+ \
                        " VALUES ("+', '.join(formats) +")",
                        values)

            if 'deployed_units' in row:
                cur.executemany("INSERT INTO "+sql_util.sym(battle_units_table)+" (battle_id, specname, deployed) VALUES (%s, %s, %s)",
                                [(battle_id, specname, qty) for specname, qty in row['deployed_units'].iteritems()])

            if 'loot' in row and ('items' in row['loot']):
                cur.executemany("INSERT INTO "+sql_util.sym(battle_loot_table) + \
                                " (battle_id, stack, item, expire_time) VALUES (%s,%s,%s,%s)",
                                [(battle_id, item.get('stack',1), item['spec'], item['expire_time'] if item.get('expire_time',-1)>0 else None) \
                                 for item in row['loot']['items']])

            if 'items_expended' in row:
                cur.executemany("INSERT INTO "+sql_util.sym(battle_items_table) + \
                                " (battle_id, user_id, stack, item) VALUES (%s,%s,%s,%s)",
                                [(battle_id, int(suser_id), qty, specname) \
                                 for suser_id, item_dict in row['items_expended'].iteritems() \
                                 for specname, qty in item_dict.iteritems()
                                 ])
            if 'damage' in row:
                cur.executemany("INSERT INTO "+sql_util.sym(battle_damage_table) + \
                                " (battle_id,user_id,mobile,level,stack,iron,water,res3,time,spec) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                list(battle_damage_iter(battle_id, row['damage'])))

            batch += 1
            total += 1
            affected_days.add(86400*(row['time']//86400))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print total, 'total inserted', 'affecting', len(affected_days), 'day(s)'

        # update summary tables
        dt = 86400

        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(battles_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            battles_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            battles_range = None

        cur.execute("SELECT MIN(day) AS begin, MAX(day) AS end FROM "+sql_util.sym(battles_summary_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['begin'] and rows[0]['end']:
            # we already have summary data - update it incrementally
            if battles_range: # fill in any missing trailing summary data
                source_days = sorted(affected_days.union(set(xrange(dt*(rows[0]['end']//dt + 1), dt*(battles_range[1]//dt + 1), dt))))
            else:
                source_days = sorted(list(affected_days))
        else:
            # recreate entire summary
            if battles_range:
                source_days = range(dt*(battles_range[0]//dt), dt*(battles_range[1]//dt + 1), dt)
            else:
                source_days = None

        if source_days:
            for day_start in source_days:
                if verbose: print 'updating', battles_summary_table, 'at', time.strftime('%Y%m%d', time.gmtime(day_start))

                cur.execute("DELETE FROM "+sql_util.sym(battles_summary_table)+" WHERE day >= %s AND day < %s+86400", [day_start,]*2)
                cur.execute("DELETE FROM "+sql_util.sym(battle_loot_summary_table)+" WHERE day >= %s AND day < %s+86400", [day_start,]*2)
                cur.execute("DELETE FROM "+sql_util.sym(battle_units_summary_table)+" WHERE day >= %s AND day < %s+86400", [day_start,]*2)

                # merge all PvP opponents into a single "NULL" opponent_id to minimize summary table size
                opponent_id_expr = "IF(IF(battles.active_opponent_id = battles.attacker_id, attacker_type, defender_type) = 'ai', battles.active_opponent_id, NULL)"

                cur.execute("INSERT INTO "+sql_util.sym(battles_summary_table) + \
                            "SELECT 86400*FLOOR(battles.time/86400.0) AS day," + \
                            "       battles.active_player_frame_platform AS frame_platform," + \
                            "       battles.active_player_country_tier AS country_tier," + \
                            "       battles.active_player_townhall_level AS townhall_level," + \
                            "      "+sql_util.encode_spend_bracket("battles.active_player_prev_receipts")+" AS spend_bracket," + \
                            "      "+opponent_id_expr+" AS opponent_id," + \
                            "       battles.base_region AS base_region," + \
                            "       battles.base_type AS base_type," + \
                            "       battles.base_template AS base_template," + \
                            "       SUM(duration) AS duration," + \
                            "       AVG(framerate) AS framerate, " + \
                            "       MIN(framerate) AS framerate_min, " + \
                            sql_util.percentile('framerate', 0.1) + " AS framerate_10th, " + \
                            "       SUM(IF(active_player_outcome='victory',1,0))/COUNT(1) AS victory_ratio," + \
                            "       "+",".join(['SUM('+sql_util.sym('loot:'+res)+')' for res in ('xp','iron','water','res3','iron_lost','water_lost','res3_lost')]) + \
                            "FROM "+sql_util.sym(battles_table)+" battles " + \
                            "WHERE battles.time >= %s AND battles.time < %s+86400 " + \
                            "GROUP BY day, frame_platform, country_tier, townhall_level, spend_bracket, opponent_id, battles.base_region, battles.base_type, battles.base_template ORDER BY NULL",
                            [day_start,]*2)

                if verbose: print 'updating', battle_loot_summary_table, 'at', time.strftime('%Y%m%d', time.gmtime(day_start))
                cur.execute("INSERT INTO "+sql_util.sym(battle_loot_summary_table) + \
                            "SELECT 86400*FLOOR(battles.time/86400.0) AS day," + \
                            "       battles.active_player_frame_platform AS frame_platform," + \
                            "       battles.active_player_country_tier AS country_tier," + \
                            "       battles.active_player_townhall_level AS townhall_level," + \
                            "      "+sql_util.encode_spend_bracket("battles.active_player_prev_receipts")+" AS spend_bracket," + \
                            "       battles.base_type AS base_type," + \
                            "      "+opponent_id_expr+" AS opponent_id," + \
                            "       loot.item AS item, SUM(loot.stack) AS stack " + \
                            "FROM "+sql_util.sym(battles_table)+" battles INNER JOIN "+sql_util.sym(battle_loot_table)+" loot ON loot.battle_id = battles.battle_id " + \
                            "WHERE battles.time >= %s AND battles.time < %s+86400 " + \
                            "GROUP BY day, frame_platform, country_tier, townhall_level, spend_bracket, base_type, opponent_id, loot.item ORDER BY NULL",
                            [day_start,]*2)

                if verbose: print 'updating', battle_units_summary_table, 'at', time.strftime('%Y%m%d', time.gmtime(day_start))
                cur.execute("INSERT INTO "+sql_util.sym(battle_units_summary_table) + \
                            "SELECT 86400*FLOOR(battles.time/86400.0) AS day," + \
                            "       battles.active_player_frame_platform AS frame_platform," + \
                            "       battles.active_player_country_tier AS country_tier," + \
                            "       battles.active_player_townhall_level AS townhall_level," + \
                            "      "+sql_util.encode_spend_bracket("battles.active_player_prev_receipts")+" AS spend_bracket," + \
                            "       battles.base_type AS base_type," + \
                            "      "+opponent_id_expr+" AS opponent_id," + \
                            "       units.specname AS specname, SUM(deployed) AS deployed," + \
                            "       SUM(1) AS battle_count " + \
                            "FROM "+sql_util.sym(battles_table)+" battles INNER JOIN "+sql_util.sym(battle_units_table)+" units ON units.battle_id = battles.battle_id " + \
                            "WHERE battles.time >= %s AND battles.time < %s+86400 " + \
                            "GROUP BY day, frame_platform, country_tier, townhall_level, spend_bracket, base_type, opponent_id, units.specname ORDER BY NULL",
                            [day_start,]*2)

                con.commit() # one commit per day

        else:
            if verbose: print 'no change to summaries'

        if do_prune:
            # drop old data
            KEEP_DAYS = {'sg': 180}.get(game_id, 90)
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', battle_loot_table
            cur.execute("DELETE loot FROM "+sql_util.sym(battle_loot_table)+" loot INNER JOIN "+sql_util.sym(battles_table)+" battles ON loot.battle_id = battles.battle_id WHERE battles.time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'removing orphans and optimizing', battle_loot_table
                cur.execute("DELETE FROM "+sql_util.sym(battle_loot_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_loot_table))

            if verbose: print 'pruning', battle_units_table
            cur.execute("DELETE units FROM "+sql_util.sym(battle_units_table)+" units INNER JOIN "+sql_util.sym(battles_table)+" battles ON units.battle_id = battles.battle_id WHERE battles.time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'removing orphans and optimizing', battle_units_table
                cur.execute("DELETE FROM "+sql_util.sym(battle_units_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_units_table))

            if verbose: print 'pruning', battle_items_table
            cur.execute("DELETE items FROM "+sql_util.sym(battle_items_table)+" items INNER JOIN "+sql_util.sym(battles_table)+" battles ON items.battle_id = battles.battle_id WHERE battles.time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'removing orphans and optimizing', battle_items_table
                cur.execute("DELETE FROM "+sql_util.sym(battle_items_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_items_table))

            if verbose: print 'pruning', battle_damage_table
            cur.execute("DELETE damage FROM "+sql_util.sym(battle_damage_table)+" damage INNER JOIN "+sql_util.sym(battles_table)+" battles ON damage.battle_id = battles.battle_id WHERE battles.time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'removing orphans and optimizing', battle_damage_table
                cur.execute("DELETE FROM "+sql_util.sym(battle_damage_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_damage_table))

            if verbose: print 'pruning', battles_table
            cur.execute("DELETE FROM "+sql_util.sym(battles_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', battles_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(battles_table))

            con.commit()
