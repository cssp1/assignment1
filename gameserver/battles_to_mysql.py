#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "battles" table from MongoDB to a MySQL database for analytics

# creates tables:
# ai_bases (from scratch each time)
# battles (grows incrementally)
# battle_units (grows incrementally)
# battle_loot (grows incrementally)

import sys, time, getopt
import SpinConfig
import SpinUpcache
import SpinJSON
import SpinNoSQL
import SpinSQLUtil
import MySQLdb

gamedata = None
time_now = int(time.time())

def ai_bases_schema(sql_util):
    return {'fields': [('user_id', 'INT4 NOT NULL PRIMARY KEY'),
                       ('kind', 'VARCHAR(16)'),
                       ('player_level', 'INT4'),
                       ('ui_name', 'VARCHAR(32)'),
                       ('class', 'VARCHAR(32)'),
                       ('analytics_tag', 'VARCHAR(32)'), # XXX deprecated - this can vary over time, so we need to switch to "assignments"
                       ], 'indices': {}}
def ai_base_templates_schema(sql_util):
    return {'fields': [('base_type', 'VARCHAR(16) NOT NULL'),
                       ('base_template', 'VARCHAR(32) NOT NULL'),
                       ('owner_id', 'INT4'),
                       ('class', 'VARCHAR(32)'),
                       ('analytics_tag', 'VARCHAR(32)'), # XXX deprecated - this can vary over time, so we need to switch to "assignments"
                       ], 'indices': {'master': {'unique':True, 'keys':[('base_type','ASC'),('base_template','ASC')]}}}

# since analytics tags can change over time, the base->tag assignment has to be in a separate table
def ai_analytics_tag_assignments_schema(sql_util):
    return {'fields': [('base_type', 'VARCHAR(8)'),
                       ('base_template', 'VARCHAR(32)'), # 'home' when base_type = 'home'
                       ('user_id', 'INT4'), # -1 when base_type != 'home' (cannot use NULL because we want to parameterize matches)
                       ('start_time', 'INT8'),
                       ('end_time', 'INT8'),
                       ('analytics_tag', 'VARCHAR(32)'),
                       ('difficulty', 'VARCHAR(16)'), # "Normal"/"Heroic"/"Epic"
                       ('difficulty_step', 'INT2'), # counts starts from 1 within each Normal/Heroic/Epic progression
                       ('progression_step', 'INT2'), # counts from 1 and merges Normal/Heroic/Epic into a single progression
                       ],
            'indices': {'master':{'unique': True, 'keys':[('base_type','ASC'),('base_template','ASC'),('user_id','ASC'),('start_time','ASC')]}}
            }

def ai_analytics_tag_info_schema(sql_util):
    return {'fields': [('analytics_tag', 'VARCHAR(32) NOT NULL PRIMARY KEY'),
                       ('event_type', 'VARCHAR(32)'),
                       ('num_difficulties', 'INT1'), # number of difficulty progressions (3 for Normal/Heroic/Epic, 1 for Normal only, NULL for non-linear-progression events)
                       ('num_progression', 'INT4'),
                       ('num_hives', 'INT4'),
                       ('start_time', 'INT8'),
                       ('end_time', 'INT8'),
                       ('repeat_interval', 'INT4')
                       ], 'indices': {}}

def battles_schema(sql_util): return {
    'fields': [('battle_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'),
               ('duration', 'INT4'),
               ('framerate', 'FLOAT4'),
               ('active_player_ping', 'FLOAT4'),
               ('battle_type', 'VARCHAR(8)'), # 'attack' or 'defense'
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
               ('home_base', 'TINYINT(1)'),
               ('is_revenge', 'TINYINT(1)'),
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
               ('level', 'INT1 NOT NULL'),
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
    gamedata['ai_bases'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('ai_bases_compiled.json', override_game_id = game_id)))
    gamedata['quarries'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('quarries_compiled.json', override_game_id = game_id)))
    gamedata['hives'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('hives_compiled.json', override_game_id = game_id)))
    gamedata['loot_tables'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('loot_tables.json', override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    battles_table = cfg['table_prefix']+game_id+'_battles'
    battles_summary_table = cfg['table_prefix']+game_id+'_battles_daily_summary'
    battle_units_table = cfg['table_prefix']+game_id+'_battle_units'
    battle_units_summary_table = cfg['table_prefix']+game_id+'_battle_units_daily_summary'
    battle_loot_table = cfg['table_prefix']+game_id+'_battle_loot'
    battle_loot_summary_table = cfg['table_prefix']+game_id+'_battle_loot_daily_summary'
    battle_items_table = cfg['table_prefix']+game_id+'_battle_items'
    battle_damage_table = cfg['table_prefix']+game_id+'_battle_damage'
    ai_bases_table = cfg['table_prefix']+game_id+'_ai_bases'
    ai_base_templates_table = cfg['table_prefix']+game_id+'_ai_base_templates'
    ai_analytics_tag_info_table = cfg['table_prefix']+game_id+'_ai_analytics_tag_info'
    ai_analytics_tag_assignments_table = cfg['table_prefix']+game_id+'_ai_analytics_tag_assignments'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))
    cur = con.cursor(MySQLdb.cursors.DictCursor)

    # prepare for big GROUP_CONCAT()s below (MySQL-specific)
    cur.execute("SET @@session.group_concat_max_len = @@global.max_allowed_packet")

    # recreate AI bases and analytics tag tables
    if verbose: print 'updating AI bases and analytics tag tables'
    for table, schema in ((ai_bases_table, ai_bases_schema(sql_util)),
                          (ai_base_templates_table, ai_base_templates_schema(sql_util)),
                          (ai_analytics_tag_info_table, ai_analytics_tag_info_schema(sql_util)),
                          (ai_analytics_tag_assignments_table, ai_analytics_tag_assignments_schema(sql_util)),
                          ):
        if table not in (ai_analytics_tag_info_table, ai_analytics_tag_assignments_table): # these tables are persistent
            cur.execute("DROP TABLE IF EXISTS %s" % table)
        sql_util.ensure_table(cur, table, schema)

    ai_bases_rows = []
    ai_base_templates_rows = []
    analytics_tag_info = {} # indexed by tag
    for sid, data in gamedata['ai_bases']['bases'].iteritems():
        tag = data.get('analytics_tag', None)
        klass = SpinUpcache.classify_ai_base(gamedata, int(sid))
        ui_difficulty = data.get('ui_difficulty', 'Normal')

        ai_bases_rows.append([('user_id',int(sid)),
                              ('kind', data.get('kind', 'ai_base')),
                              ('player_level', data['resources']['player_level']),
                              ('ui_name', data['ui_name']),
                              ('analytics_tag', tag),
                              ('class', klass)])
        event_klass = {'pve_event_progression': 'event',
                       'hitlist': 'hitlist',
                       'pve_immortal_progression': 'immortal',
                       'pve_tutorial_progression': 'tutorial'}.get(klass, None)
        if tag and event_klass:
            if tag not in analytics_tag_info:
                analytics_tag_info[tag] = {'analytics_tag': tag,
                                           'event_type': event_klass,
                                           'difficulties': [],
                                           'base_ids': [],
                                           'hives': [],
                                           'start_end_times': None, # array of all applicable [start,end] times
                                           'start_time': None, # earliest of all applicable start_times
                                           'end_time': None, # latest of all applicable end_times
                                           'repeat_interval': None}
            info = analytics_tag_info[tag]
            info['base_ids'].append(int(sid))

            if ui_difficulty not in info['difficulties']:
                info['difficulties'].append(ui_difficulty)

            # add timing info to existing entry
            start_end_times = SpinUpcache.ai_base_timings(gamedata, data)
            if start_end_times:
                info['start_end_times'] = []
                for start_time, end_time, repeat_interval in start_end_times:
                    if (start_time,end_time) not in info['start_end_times']: info['start_end_times'].append((start_time, end_time))
                    if start_time is not None: info['start_time'] = start_time if (info['start_time'] is None or start_time < 0) else min(info['start_time'], start_time)
                    if end_time is not None: info['end_time'] = end_time if (info['end_time'] is None or end_time < 0) else max(info['end_time'], end_time)
                    if repeat_interval is not None: info['repeat_interval'] = repeat_interval

    for kind, dir in (('quarry', 'quarries'), ('hive', 'hives')):
        for name, data in gamedata[dir]['templates'].iteritems():
            owner_id = data.get('owner_id', None)
            owner_base = gamedata['ai_bases']['bases'].get(str(owner_id), None) if owner_id else None
            tag = data.get('analytics_tag', owner_base.get('analytics_tag',None) if owner_base else None)
            klass = {'quarry': SpinUpcache.classify_quarry,
                     'hive': SpinUpcache.classify_hive}[kind](gamedata, name)
            ai_base_templates_rows.append([('base_type', kind),
                                           ('base_template', name),
                                           ('owner_id', owner_id),
                                           ('class', klass),
                                           ('analytics_tag', tag)])
            event_klass = {'pve_event_hive': 'event',
                           'pve_immortal_hive': 'immortal'}.get(klass, None)

            if tag and event_klass:
                if tag not in analytics_tag_info:
                    analytics_tag_info[tag] = {'analytics_tag': tag,
                                               'event_type': event_klass,
                                               'difficulties': [],
                                               'base_ids': [],
                                               'hives': [],
                                               'start_end_times': None, # array of all applicable [start,end] times
                                               'start_time': None, # earliest of all applicable start_times
                                               'end_time': None, # latest of all applicable end_times
                                               'repeat_interval': None}
                info = analytics_tag_info[tag]
                info['hives'].append(name)
                start_end_times = SpinUpcache.hive_timings(gamedata, name)
                if start_end_times:
                    info['start_end_times'] = []
                    for start_time, end_time in start_end_times:
                        if (start_time,end_time) not in info['start_end_times']: info['start_end_times'].append((start_time, end_time))
                        if start_time is not None: info['start_time'] = start_time if (info['start_time'] is None or start_time < 0) else min(info['start_time'], start_time)
                        if end_time is not None: info['end_time'] = end_time if (info['end_time'] is None or end_time < 0) else max(info['end_time'], end_time)


    # fix up repeat_interval to be NULL instead of the end-start time for once-only events
#    for entry in analytics_tag_info.itervalues():
#        if entry['start_time'] > 0 and entry['end_time'] > 0 and entry['repeat_interval'] and (entry['repeat_interval'] >= (entry['end_time'] - entry['start_time'])):
#            entry['repeat_interval'] = None

    sql_util.do_insert_batch(cur, ai_bases_table, ai_bases_rows)
    sql_util.do_insert_batch(cur, ai_base_templates_table, ai_base_templates_rows)
    con.commit()

    # note: upsert into ai_analytics_tag_info
    if len(analytics_tag_info) > 0:
        cur.execute("DELETE FROM "+sql_util.sym(ai_analytics_tag_info_table)+" WHERE analytics_tag IN (" + \
                    (','.join(["%s",] * len(analytics_tag_info)))+")", analytics_tag_info.keys())
        sql_util.do_insert_batch(cur, ai_analytics_tag_info_table, [(('analytics_tag',entry['analytics_tag']),
                                                                     ('event_type',entry['event_type']),
                                                                     ('num_difficulties', len(entry['difficulties']) if entry['difficulties'] else None),
                                                                     ('num_progression', len(entry['base_ids'])),
                                                                     ('num_hives', len(entry['hives'])),
                                                                     ('start_time', entry['start_time']),
                                                                     ('end_time', entry['end_time']),
                                                                     ('repeat_interval', entry['repeat_interval']))
                                                                    for entry in analytics_tag_info.itervalues()])
        # upsert into ai_analytics_tag_assignments
        assignments_keys = [] # master keys to upsert
        assignments_rows = []
        for entry in analytics_tag_info.itervalues():
            if entry['start_end_times']:
                start_end_times = entry['start_end_times']
            else:
                start_end_times = [[-1,-1]]

            for base_id in entry['base_ids']:
                base = gamedata['ai_bases']['bases'][str(base_id)]
                if 'ui_progress' in base:
                    difficulty_step = base['ui_progress']['cur']
                    if 'overall_cur' in base['ui_progress']: # detect updated events
                        progression_step = base['ui_progress']['overall_cur']
                    else:
                        progression_step = None
                else:
                    difficulty_step = None
                    progression_step = None

                for start_time, end_time in start_end_times:
                    assignments_keys.append(('home', 'home', base_id, start_time))
                    assignments_rows.append((('base_type', 'home'),
                                             ('base_template', 'home'),
                                             ('user_id', base_id),
                                             ('start_time', start_time),
                                             ('end_time', end_time),
                                             ('analytics_tag', entry['analytics_tag']),
                                             ('difficulty', base.get('ui_difficulty', 'Normal')),
                                             ('difficulty_step', difficulty_step),
                                             ('progression_step', progression_step),
                                             ))
            for hive in entry['hives']:
                for start_time, end_time in start_end_times:
                    assignments_keys.append(('hive', hive, -1, start_time))
                    assignments_rows.append((('base_type', 'hive'),
                                             ('base_template', hive),
                                             ('user_id', -1),
                                             ('start_time', start_time),
                                             ('end_time', end_time),
                                             ('analytics_tag', entry['analytics_tag']),
                                             ('difficulty', None),
                                             ('difficulty_step', None),
                                             ('progression_step', None)))
        cur.executemany("DELETE FROM "+sql_util.sym(ai_analytics_tag_assignments_table)+" WHERE base_type = %s AND base_template = %s AND user_id = %s AND start_time = %s",
                        assignments_keys)
        sql_util.do_insert_batch(cur, ai_analytics_tag_assignments_table, assignments_rows)

    con.commit()

    #sys.exit(0)

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

    for row in nosql_client.battles_table().find(qs):
        battle_id = nosql_client.decode_object_id(row['_id'])

        # add redundant active_player/active_opponent fields
        if 'battle_type' in row:
            if row['battle_type'] == 'attack':
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
                    formats.append("GeomFromText(%s)")
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
                            battle_damage_iter(battle_id, row['damage']))

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
                        """     -- MySQL percentile trick
                                SUBSTRING_INDEX(
                                  SUBSTRING_INDEX(
                                    GROUP_CONCAT(framerate ORDER BY framerate SEPARATOR ',')
                                    , ','
                                    ,  10/100 * COUNT(*) + 1
                                    ), ',' , -1) + 0.0 AS framerate_10th, """ + \
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
        KEEP_DAYS = {'sg': 180}.get(game_id, 45)
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', battle_loot_table
        cur.execute("DELETE loot FROM "+sql_util.sym(battle_loot_table)+" loot INNER JOIN "+sql_util.sym(battles_table)+" battles ON loot.battle_id = battles.battle_id WHERE battles.time < %s", old_limit)
        if do_optimize:
            if verbose: print 'removing orphans and optimizing', battle_loot_table
            cur.execute("DELETE FROM "+sql_util.sym(battle_loot_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_loot_table))

        if verbose: print 'pruning', battle_units_table
        cur.execute("DELETE units FROM "+sql_util.sym(battle_units_table)+" units INNER JOIN "+sql_util.sym(battles_table)+" battles ON units.battle_id = battles.battle_id WHERE battles.time < %s", old_limit)
        if do_optimize:
            if verbose: print 'removing orphans and optimizing', battle_units_table
            cur.execute("DELETE FROM "+sql_util.sym(battle_units_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_units_table))

        if verbose: print 'pruning', battle_items_table
        cur.execute("DELETE items FROM "+sql_util.sym(battle_items_table)+" items INNER JOIN "+sql_util.sym(battles_table)+" battles ON items.battle_id = battles.battle_id WHERE battles.time < %s", old_limit)
        if do_optimize:
            if verbose: print 'removing orphans and optimizing', battle_items_table
            cur.execute("DELETE FROM "+sql_util.sym(battle_items_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_items_table))

        if verbose: print 'pruning', battle_damage_table
        cur.execute("DELETE damage FROM "+sql_util.sym(battle_damage_table)+" damage INNER JOIN "+sql_util.sym(battles_table)+" battles ON damage.battle_id = battles.battle_id WHERE battles.time < %s", old_limit)
        if do_optimize:
            if verbose: print 'removing orphans and optimizing', battle_damage_table
            cur.execute("DELETE FROM "+sql_util.sym(battle_damage_table)+" WHERE battle_id NOT IN (SELECT battle_id FROM "+sql_util.sym(battles_table)+")")
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(battle_damage_table))

        if verbose: print 'pruning', battles_table
        cur.execute("DELETE FROM "+sql_util.sym(battles_table)+" WHERE time < %s", old_limit)
        if do_optimize:
            if verbose: print 'optimizing', battles_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(battles_table))

        con.commit()
