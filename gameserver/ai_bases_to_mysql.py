#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump static info about AI bases, hives, quarries, and events from gamedata to SQL database for analytics

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
                       ('reset_interval', 'INT8'),
                       ('repeat_interval', 'INT8'),
                       ('analytics_tag', 'VARCHAR(32)'),
                       ('difficulty', 'VARCHAR(16)'), # "Normal"/"Heroic"/"Epic"
                       ('difficulty_step', 'INT2'), # counts starts from 1 within each Normal/Heroic/Epic progression
                       ('progression_step', 'INT2'), # counts from 1 and merges Normal/Heroic/Epic into a single progression
                       ],
            'indices': {'master':{'unique': True, 'keys':[('base_type','ASC'),('base_template','ASC'),('user_id','ASC'),('start_time','ASC')]}}
            }

def ai_analytics_tag_info_schema(sql_util):
    return {'fields': [('analytics_tag', 'VARCHAR(32) NOT NULL'),
                       ('event_type', 'VARCHAR(32)'),
                       ('num_difficulties', 'INT1'), # number of difficulty progressions (3 for Normal/Heroic/Epic, 1 for Normal only, NULL for non-linear-progression events)
                       ('num_progression', 'INT4'),
                       ('num_hives', 'INT4'),
                       ('start_time', 'INT8'),
                       ('end_time', 'INT8'),
                       ('reset_interval', 'INT8'),
                       ('repeat_interval', 'INT8'),
                       ], 'indices': {'master':{'unique': True, 'keys':[('analytics_tag','ASC'),('start_time','ASC')]}}
            }

def new_analytics_tag_info(tag, event_klass):
    return {'analytics_tag': tag,
            'event_type': event_klass,
            'difficulties': [],
            'base_ids': [],
            'hives': [],
            'start_end_times': None, # array of all applicable [start,end] times
            'start_time': None, # earliest of all applicable start_times
            'end_time': None, # latest of all applicable end_times
            'reset_interval': None,
            'repeat_interval': None}

def is_historical(start_time, end_time, reset_interval, repeat_interval):
    return (start_time >= 0) and (not (repeat_interval > 0)) and (start_time < time_now - 14*86400)

# incorporate timing info from one AI base or hive into the info for the entire event tag
def apply_timing_info(info, start_end_times):
    # to avoid disturbing historical data, do not update runs that were long in the past
    start_end_times = filter(lambda s_e_t: not is_historical(*s_e_t), start_end_times)
    if len(start_end_times) < 1: return

    # overwrite existing contents
    info['start_end_times'] = []
    for start_time, end_time, reset_interval, repeat_interval in start_end_times:
        if (start_time,end_time,reset_interval, repeat_interval) not in info['start_end_times']: info['start_end_times'].append((start_time,end_time,reset_interval,repeat_interval))
        # set min/max ranges
        if start_time is not None: info['start_time'] = start_time if (info['start_time'] is None or start_time < 0) else min(info['start_time'], start_time)
        if end_time is not None: info['end_time'] = end_time if (info['end_time'] is None or end_time < 0) else max(info['end_time'], end_time)
        if reset_interval is not None: info['reset_interval'] = reset_interval
        if repeat_interval is not None: info['repeat_interval'] = repeat_interval


if __name__ == '__main__':
    game_id = SpinConfig.game()
    verbose = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:q', [])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-q': verbose = False

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

    with SpinSingletonProcess.SingletonProcess('ai_bases_to_mysql-%s' % game_id):

        ai_bases_table = cfg['table_prefix']+game_id+'_ai_bases'
        ai_base_templates_table = cfg['table_prefix']+game_id+'_ai_base_templates'
        ai_analytics_tag_info_table = cfg['table_prefix']+game_id+'_ai_analytics_tag_info'
        ai_analytics_tag_assignments_table = cfg['table_prefix']+game_id+'_ai_analytics_tag_assignments'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))
        cur = con.cursor(MySQLdb.cursors.DictCursor)

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
                    analytics_tag_info[tag] = new_analytics_tag_info(tag, event_klass)
                info = analytics_tag_info[tag]
                info['base_ids'].append(int(sid))

                if ui_difficulty not in info['difficulties']:
                    info['difficulties'].append(ui_difficulty)

                # add timing info to existing entry
                start_end_times = SpinUpcache.ai_base_timings(gamedata, data)
                if start_end_times:
                    apply_timing_info(info, start_end_times)

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
                        analytics_tag_info[tag] = new_analytics_tag_info(tag, event_klass)
                    info = analytics_tag_info[tag]
                    info['hives'].append(name)
                    start_end_times = SpinUpcache.hive_timings(gamedata, name)
                    if start_end_times:
                        apply_timing_info(info, start_end_times)

        # fix up repeat_interval to be NULL instead of the end-start time for once-only events
    #    for entry in analytics_tag_info.itervalues():
    #        if entry['start_time'] > 0 and entry['end_time'] > 0 and entry['repeat_interval'] and (entry['repeat_interval'] >= (entry['end_time'] - entry['start_time'])):
    #            entry['repeat_interval'] = None

        sql_util.do_insert_batch(cur, ai_bases_table, ai_bases_rows)
        sql_util.do_insert_batch(cur, ai_base_templates_table, ai_base_templates_rows)
        con.commit()

        # note: upsert into ai_analytics_tag_info
        if len(analytics_tag_info) > 0:
            cur.executemany("DELETE FROM "+sql_util.sym(ai_analytics_tag_info_table)+" WHERE analytics_tag = %s AND start_time >= %s",
                            [(k, inf['start_time']) for k, inf in analytics_tag_info.iteritems() if inf['start_time'] is not None])

            if verbose: print 'replacing ai_analytics_tag_info:\n', '\n'.join('%s start >= %d, start_end_times %r' % (k, info['start_time'], info['start_end_times']) for k, info in analytics_tag_info.iteritems() if info['start_time'] is not None)
            sql_util.do_insert_batch(cur, ai_analytics_tag_info_table, [(('analytics_tag',entry['analytics_tag']),
                                                                         ('event_type',entry['event_type']),
                                                                         ('num_difficulties', len(entry['difficulties']) if entry['difficulties'] else None),
                                                                         ('num_progression', len(entry['base_ids'])),
                                                                         ('num_hives', len(entry['hives'])),
                                                                         ('start_time', entry['start_time']),
                                                                         ('end_time', entry['end_time']),
                                                                         ('reset_interval', entry['reset_interval']),
                                                                         ('repeat_interval', entry['repeat_interval']))
                                                                        for entry in analytics_tag_info.itervalues() if entry['start_time'] is not None])
            # upsert into ai_analytics_tag_assignments
            assignments_keys = [] # master keys to upsert
            assignments_rows = []
            for entry in analytics_tag_info.itervalues():
                if entry['start_time'] is None:
                    continue

                start_end_times = entry['start_end_times']

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

                    for start_time, end_time, reset_interval, repeat_interval in start_end_times:
                        assignments_keys.append(('home', 'home', base_id, start_time))
                        assignments_rows.append((('base_type', 'home'),
                                                 ('base_template', 'home'),
                                                 ('user_id', base_id),
                                                 ('start_time', start_time),
                                                 ('end_time', end_time),
                                                 ('reset_interval', reset_interval),
                                                 ('repeat_interval', repeat_interval),
                                                 ('analytics_tag', entry['analytics_tag']),
                                                 ('difficulty', base.get('ui_difficulty', 'Normal')),
                                                 ('difficulty_step', difficulty_step),
                                                 ('progression_step', progression_step),
                                                 ))
                for hive in entry['hives']:
                    for start_time, end_time, reset_interval, repeat_interval in start_end_times:
                        assignments_keys.append(('hive', hive, -1, start_time))
                        assignments_rows.append((('base_type', 'hive'),
                                                 ('base_template', hive),
                                                 ('user_id', -1),
                                                 ('start_time', start_time),
                                                 ('end_time', end_time),
                                                 ('reset_interval', reset_interval),
                                                 ('repeat_interval', repeat_interval),
                                                 ('analytics_tag', entry['analytics_tag']),
                                                 ('difficulty', None),
                                                 ('difficulty_step', None),
                                                 ('progression_step', None)))
            cur.executemany("DELETE FROM "+sql_util.sym(ai_analytics_tag_assignments_table)+" WHERE base_type = %s AND base_template = %s AND user_id = %s AND start_time = %s",
                            assignments_keys)
            sql_util.do_insert_batch(cur, ai_analytics_tag_assignments_table, assignments_rows)

        con.commit()
