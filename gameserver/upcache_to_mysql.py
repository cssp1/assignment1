#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump upcache out to a MySQL database for analytics

import sys, time, getopt, re
import SpinConfig
import SpinJSON
import SpinS3
import SpinUpcache
import SpinUpcacheIO
import SkynetLTV # for outboard LTV estimate table
import SpinSQLUtil
import SpinParallel
import SpinSingletonProcess
import MySQLdb
from abtests_to_sql import abtests_schema

INT2_MAX = 32767

def field_column(key, val):
    return "`%s` %s" % (key, val)

def achievement_table_schema(sql_util):
    # note: indexed fields need to be NOT NULL or else ON DUPLICATE KEY UPDATE will not work
    return {'fields': sql_util.summary_out_dimensions()  + \
              [('kind', 'VARCHAR(16) NOT NULL'),
               ('spec', 'VARCHAR(64) NOT NULL'),
               ('level', 'INT2 NOT NULL'),
               ('is_maxed', sql_util.bit_type()+' NOT NULL'), # flag that this is the max level of the spec
               ('num_players', 'INT4 NOT NULL')
               ],
    'indices': {'master': {'unique': True, 'keys': [(x[0],'ASC') for x in sql_util.summary_out_dimensions()] + [('kind','ASC'),('spec','ASC'),('level','ASC')]}}
    }

# to optimize space usage of time-series tables, collapse some summary dimensions
def collapsed_summary_dimensions(sql_util):
    return [(name, datatype) for name, datatype in sql_util.summary_out_dimensions() if name not in ('frame_platform', 'country_tier')]

def army_composition_table_schema(sql_util):
    # note: indexed fields need to be NOT NULL or else ON DUPLICATE KEY UPDATE will not work
    return {'fields': [('time','INT8 NOT NULL')] + \
                       collapsed_summary_dimensions(sql_util) + \
                      [('kind','VARCHAR(16) NOT NULL'),
                       ('spec','VARCHAR(255) NOT NULL'),
                       ('level','INT2 NOT NULL'),
                       ('location','VARCHAR(32) NOT NULL'),
                       ('total_count','INT4 NOT NULL')],
            'indices': {
                'master': {'unique': True, 'keys': [('time','ASC')] + \
                                                   [(x[0],'ASC') for x in collapsed_summary_dimensions(sql_util)] + \
                                                   [('kind','ASC'),('spec','ASC'),('level','ASC'),('location','ASC')]}
            }
    }

def resource_levels_table_schema(sql_util):
    # note: indexed fields need to be NOT NULL or else ON DUPLICATE KEY UPDATE will not work
    return {'fields': [('time','INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('resource', 'VARCHAR(64) NOT NULL'),
                       ('total_amount','INT8 NOT NULL'),
                       ('num_players','INT4 NOT NULL'),
                       ],
            'indices': {
                'master': {'unique': True, 'keys': [('time','ASC')] + \
                                                   [(x[0],'ASC') for x in sql_util.summary_out_dimensions()] + \
                                                   [('resource','ASC')]}
            }
    }

# detect A/B test names
abtest_filter = re.compile('^T[0-9]+')

# "ALL" mode
# always accept these keys
accept_filter = re.compile('^feature_used:playfield_speed|^feature_used:client_ingame|^feature_used:first_action|^feature_used:region_map_scroll_help|ai_tutorial.*_progress$|^achievement:.*blitz')
# then, always reject these keys
reject_filter = re.compile('^T[0-9]+_|acquisition_game_version|account_creation_hour|account_creation_wday|^fb_notification:|^achievement:|^quest:|_conquests$|_progress$|_attempted$|days_since_joined|days_since_last_login|lock_state|^visits_[0-9]+d$|^retained_[0-9]+d$|oauth_token|facebook_permissions_str|acquisition_type|^link$|_context$|^item:|^unit:.+:(killed|lost)|_times_(started|completed)$')

# "lite" mode
lite_accept_filter = re.compile('|'.join('^'+x+'$' for x in \
                                         ['account_creation_time', 'account_creation_flow',
                                          'last_login_time', 'last_login_ip', 'time_of_first_purchase',
                                          'acquisition_campaign',
                                          'acquisition_ad_skynet',
                                          'country', 'country_tier', 'currency', 'timezone',
                                          'completed_tutorial',
                                          'frame_platform', 'social_id', 'facebook_id', 'facebook_name', 'facebook_first_name', 'kg_id', 'kg_username', 'ag_id', 'ag_username', 'bh_id', 'bh_username', 'mm_id', 'mm_username',
                                          'money_spent', 'money_refunded', 'num_purchases',
                                          'client:purchase_ui_opens', 'client:purchase_ui_opens_preftd',
                                          'client:purchase_inits', 'client:purchase_inits_preftd',
                                          'player_level', 'player_xp',
                                          'home_region', 'tutorial_state', 'upcache_time',
                                          'returned_[0-9]+-[0-9]+h',
                                          'reacquired_[0-9]+d', 'first_time_reacquired_[0-9]+d', 'last_time_reacquired_[0-9]+d',
                                          'townhall_level', # note: this is wishful thinking - upcache actually just uses toc_,central_computer_ etc
                                          'birth_year', 'gender', 'friends_in_game', 'email', 'logged_in_times', 'alliance_id_cache', 'alliances_joined', 'time_in_game',
                                          'spend_[0-9]+d', 'attacks_launched_vs_human', 'attacks_launched_vs_ai',
                                          'chat_messages_sent',
                                          'canvas_width', 'canvas_height', 'screen_width', 'screen_height', 'devicePixelRatio',
                                          ]))

def setup_field(gamedata, sql_util, key, val, field_mode = None):
    # always accept A/B tests that are still ongoing
    if abtest_filter.search(key) and \
       key in gamedata['abtests'] and \
       gamedata['abtests'][key].get('active', 0) and \
       gamedata['abtests'][key].get('show_in_analytics', True):
        return 'VARCHAR(64)'

    # always accept townhall level
    if key == gamedata['townhall']+'_level':
        return 'INT1'

    # always accept developer flag
    if key == 'developer': return sql_util.bit_type()

    # check reject filter
    if field_mode == 'lite':
        if not lite_accept_filter.search(key):
            return None
    elif field_mode == 'ALL':
        if reject_filter.search(key) and (not accept_filter.search(key)):
            return None # reject
    else:
        raise Exception('unknown field_mode '+field_mode)

    if type(val) is float:
        return 'FLOAT4'

    elif type(val) is int:
        if key.endswith(':completed'):
            return 'INT4' # counters
        elif key.startswith('achievement:'):
            return 'INT8' # time value
        elif key.endswith('_time') or key in ('time_in_game','player_xp') or ('time_reacquired' in key) or ('stolen' in key) or ('harvested' in key) or ('looted' in key) or key.startswith('peak_'):
            return 'INT8' # times / big resource amounts
        elif key.startswith('likes_') or key.startswith('returned_') or key.startswith('feature_used:'):
            return sql_util.bit_type() # booleans
        elif key.endswith('_level') or key.endswith('_level_started') or ('_townhall_L' in key):
            return 'INT1' # level numbers
        elif key.endswith('_concurrency'):
            return 'INT1' # build/upgrade/manufacture concurrency
        elif key.endswith('_num') and key[:-4] in gamedata['buildings']:
            return 'INT2' if key[:-4] == 'barrier' else 'INT1' # building quantities
        elif key.endswith('_migrated'):
            return 'INT1' # migration flags
        elif key.endswith('_unlocked'):
            return 'INT1' # count of techs unlocked in various categories, or single-bit flags
        elif key == 'has_facebook_likes':
            return 'INT1' # version number for Likes data
        elif key in ('canvas_oversample','devicePixelRatio'):
            return 'FLOAT4'
        else:
            return 'INT4'

    elif type(val) in (str, unicode):
        if key == 'country_tier': return 'CHAR(1)'
        elif key == 'country': return 'CHAR(2)'
        elif key == 'frame_platform': return 'CHAR(2)'
        elif key == 'gender': return 'VARCHAR(7)'
        elif key == 'currency': return 'VARCHAR(8)'
        elif key == 'locale': return 'VARCHAR(8)'
        elif key == 'timezone': return 'INT4'
        elif key == 'facebook_id': return 'VARCHAR(24)'
        elif key == 'acquisition_campaign': return 'VARCHAR(64)'
        elif key == 'tutorial_state': return 'VARCHAR(32)'
        elif key == 'browser_os': return 'VARCHAR(16)'
        elif key == 'browser_name': return 'VARCHAR(16)'
        elif key == 'birthday': return 'VARCHAR(10)'
        elif key == 'last_login_ip': return 'VARCHAR(64)'
        elif key == 'browser_user_agent': return 'VARCHAR(255)'
        else: return 'VARCHAR(128)'

    else: # not a recognized data type
        return None

level_identifier_pattern = re.compile('_L([0-9]+)')

# parses an Upcache entry key to determine the name and level of an item which are returned in a tuple
# if None is returned as the name, ignore this entry
def get_item_spec_level(gamedata, item):
    assert type(item) in (str,unicode)
    if ':L' in item:
        name, level_str = item.split(':L')
        level = int(level_str)
    else:
        name = item
        if 'level' in gamedata['items'].get(name,{}):
            level = gamedata['items'][name]['level']
        else:
            match = level_identifier_pattern.match(name)

            if match:
                level = int(match.group(0))
            else:
                level = 1

    if name == 'None': # compatibility with buggy upcache entries
        return None, level

    return name, level

def open_cache(game_id, info = None, use_local = False, skip_developer = True):
    if use_local:
        return SpinUpcacheIO.LocalReader('logs/%s-upcache' % SpinConfig.game_id_long(game_id), verbose=False, info=info, skip_developer=skip_developer)
    else:
        bucket, name = SpinConfig.upcache_s3_location(game_id)
        return SpinUpcacheIO.S3Reader(SpinS3.S3(SpinConfig.aws_key_file()), bucket, name, verbose=False, info=info, skip_developer=skip_developer)

def do_slave(input):
    cache = open_cache(input['game_id'], input['cache_info'], input['use_local'], input['skip_developer'])
    batch = 0
    total = 0

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = input['game_id'])))
    gamedata['ai_bases_server'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('ai_bases_server.json', override_game_id = input['game_id'])))
    gamedata['loot_tables'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename('loot_tables.json', override_game_id = input['game_id'])))

    time_now = input['time_now']
    sql_util = SpinSQLUtil.MySQLUtil()

    if input['mode'] == 'get_fields':
        fields = {'money_spent': 'FLOAT4', # force this column into existence because analytics_views.sql depends on it
                  'account_creation_time': 'INT8', # same here
                  'account_creation_flow': 'VARCHAR(32)',
                  'country_tier': 'CHAR(1)', 'country': 'CHAR(2)',
                  'acquisition_campaign': 'VARCHAR(64)',
                  'acquisition_ad_skynet': 'VARCHAR(128)',

                  # these fields are extracted from compound objects inside of "user"
                  'connection_method': 'VARCHAR(32)',
                  'last_ping': 'FLOAT4',
                  'last_direct_ssl_ping': 'FLOAT4',
                  'playfield_speed': 'INT2',
                  }
        for user in cache.iter_segment(input['segnum']):
            for key, val in user.iteritems():
                if key not in fields:
                    field = setup_field(gamedata, sql_util, key, val, field_mode = input['field_mode'])
                    if field is not None:
                        fields[key] = field
            batch += 1
            total += 1
            if batch >= 1000:
                batch = 0
                if input['verbose']: print >> sys.stderr, 'seg', input['segnum'], 'user', total
        return fields

    elif input['mode'] == 'get_rows':
        if not input['verbose']: sql_util.disable_warnings()
        sorted_field_names = input['sorted_field_names']
        cfg = input['dbconfig']
        con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        cur = con.cursor()

        # buffer up keyvals to be updated in the achievement tables
        upgrade_achievement_counters = {}

        # accumulate batch totals for army composition
        army_composition = {}

        # accumulate batch totals for resource levels
        resource_levels = {}

        # accumulate A/B test updates
        abtest_memberships = {}

        def flush():
            con.commit() # commit other tables first

            # MySQL often throws deadlock exceptions when doing upserts that reference existing rows (!),
            # so we need to loop on committing these updates
            deadlocks = 0

            while len(upgrade_achievement_counters) > 0:
                try:
                    cur.executemany("INSERT INTO "+sql_util.sym(input['upgrade_achievement_table']) + \
                                    " (" + ','.join([x[0] for x in sql_util.summary_out_dimensions()]) + ", kind, spec, level, is_maxed, num_players) " + \
                                    " VALUES (" + ','.join(['%s'] * len(sql_util.summary_out_dimensions())) + ", %s, %s, %s, %s, %s) " + \
                                    " ON DUPLICATE KEY UPDATE num_players = num_players + VALUES(num_players)",
                                    [k + (v,) for k,v in upgrade_achievement_counters.iteritems()])
                    con.commit()
                    upgrade_achievement_counters.clear()  # clear accumulator
                    break
                except MySQLdb.OperationalError as e:
                    if e.args[0] == 1213: # deadlock
                        con.rollback()
                        deadlocks += 1
                        continue
                    else:
                        raise

            while len(army_composition) > 0:
                try:
                    cur.executemany("INSERT INTO "+sql_util.sym(input['army_composition_table']) + \
                                    " (time, " + ','.join([x[0] for x in collapsed_summary_dimensions(sql_util)]) + ", kind, spec, level, location, total_count) " + \
                                    " VALUES (%s, " + ','.join(['%s'] * len(collapsed_summary_dimensions(sql_util))) + ", %s, %s, %s, %s, %s) " + \
                                    " ON DUPLICATE KEY UPDATE total_count = total_count + VALUES(total_count)",
                                    [(time_now,) + k + (v,) for k,v in army_composition.iteritems()])
                    con.commit()
                    army_composition.clear() # clear accumulator
                    break
                except MySQLdb.OperationalError as e:
                    if e.args[0] == 1213: # deadlock
                        con.rollback()
                        deadlocks += 1
                        continue
                    else:
                        raise

            while len(resource_levels) > 0:
                try:
                    cur.executemany("INSERT INTO "+sql_util.sym(input['resource_levels_table']) + \
                                    " (time, " + ','.join([x[0] for x in sql_util.summary_out_dimensions()]) + ", resource, total_amount, num_players) " + \
                                    " VALUES (%s, " + ','.join(['%s'] * len(sql_util.summary_out_dimensions())) + ", %s, %s, %s) " + \
                                    " ON DUPLICATE KEY UPDATE total_amount = total_amount + VALUES(total_amount), num_players = num_players + VALUES(num_players)",
                                    # note: "v" here is (amount, num_players) for each summary dimension combination
                                    [(time_now,) + k + tuple(v) for k,v in resource_levels.iteritems()])
                    con.commit()
                    resource_levels.clear() # clear accumulator
                    break
                except MySQLdb.OperationalError as e:
                    if e.args[0] == 1213: # deadlock
                        con.rollback()
                        deadlocks += 1
                        continue
                    else:
                        raise

            while len(abtest_memberships) > 0:
                try:
                    cur.executemany("INSERT INTO "+sql_util.sym(input['abtests_table']) + \
                                    " (user_id, test_name, group_name, join_time) " + \
                                    " VALUES (%s, %s, %s, %s) " + \
                                    " ON DUPLICATE KEY UPDATE group_name = VALUES(group_name), join_time = VALUES(join_time)",
                                    # note: "k" is (user_id, test_name, "v" is (group_name, join_time)
                                    [k + v for k,v in abtest_memberships.iteritems()])
                    con.commit()
                    abtest_memberships.clear() # clear accumulator
                    break
                except MySQLdb.OperationalError as e:
                    if e.args[0] == 1213: # deadlock
                        con.rollback()
                        deadlocks += 1
                        continue
                    else:
                        raise

            if input['verbose']: print >> sys.stderr, 'seg', input['segnum'], total, 'flushed', deadlocks, 'deadlocks'

        for user in cache.iter_segment(input['segnum']):
            user_id = user['user_id']

            # manual adjustments

            # unknown country should show as NULL
            if user.get('country') == 'unknown':
                del user['country']

            keys = [x for x in sorted_field_names if x in user]
            values = [user[x] for x in keys]

            # manual parsing of sprobe fields
            if ('last_sprobe_result' in user):
                connection_method = None
                if ('connection' in user['last_sprobe_result']['tests']):
                    connection_method = user['last_sprobe_result']['tests']['connection'].get('method',None)
                    if connection_method:
                        keys.append('connection_method')
                        values.append(connection_method)
                        if (connection_method in user['last_sprobe_result']['tests']) and ('ping' in user['last_sprobe_result']['tests'][connection_method]):
                            keys.append('last_ping')
                            values.append(user['last_sprobe_result']['tests'][connection_method]['ping'])

                if ('direct_ssl' in user['last_sprobe_result']['tests']) and ('ping' in user['last_sprobe_result']['tests']['direct_ssl']):
                    keys.append('last_direct_ssl_ping')
                    values.append(user['last_sprobe_result']['tests']['direct_ssl']['ping'])

            # manual parsing of other compound fields
            prefs = user.get('player_preferences', None)
            if prefs:
                if 'playfield_speed' in prefs:
                    keys.append('playfield_speed')
                    values.append(prefs['playfield_speed'])

            cur.execute("INSERT INTO " + input['upcache_table'] + \
                        "(user_id, "+', '.join(['`'+x+'`' for x in keys])+")"+ \
                        " VALUES (%s, "+', '.join(['%s'] * len(values)) +")",
                        [user_id,] + values)

            # we need the summary dimensions for achievement and army composition tables
            summary_keyvals = {'frame_platform': user.get('frame_platform',None),
                               'country_tier': str(user['country_tier']) if user.get('country_tier',None) else None,
                               'townhall_level': user.get(gamedata['townhall']+'_level',1),
                               'spend_bracket': sql_util.get_spend_bracket(user.get('money_spent',0))}
            # ordered tuples of summary coordinates
            summary_vals = tuple(summary_keyvals[key] for key, datatype in sql_util.summary_out_dimensions())
            collapsed_summary_vals = tuple(summary_keyvals[key] for key, datatype in collapsed_summary_dimensions(sql_util))

            # parse townhall progression
            if input['do_townhall'] and ('account_creation_time' in user):
                ts_key = gamedata['townhall']+'_level_at_time'
                if ts_key in user:
                    # iterate manually up the levels, so we can track the elapsed time interval between upgrades
                    sage_to_level = user[ts_key]
                    level_to_age = dict((level, int(sage)) for sage, level in sage_to_level.iteritems())
                    max_level_attained = max(sage_to_level.itervalues())

                    rows = []

                    for level in range(1, max_level_attained+1):
                        if level in level_to_age:
                            age = level_to_age[level]

                            # age at which previous level was achieved
                            if level == 1:
                                prev_age = None
                            elif level == 2:
                                prev_age = 0
                            elif level-1 in level_to_age:
                                prev_age = level_to_age[level-1]
                            else:
                                prev_age = None

                            # age at which next level was achieved
                            if level+1 in level_to_age:
                                next_age = level_to_age[level+1]
                            else:
                                next_age = None

                            rows.append((user['user_id'], level,
                                         user['account_creation_time'] + age, age,
                                         (user['account_creation_time'] + prev_age) if (prev_age is not None) else None,
                                         prev_age,
                                         (user['account_creation_time'] + next_age) if (next_age is not None) else None,
                                         next_age))

                    cur.executemany("INSERT INTO " +sql_util.sym(input['townhall_table']) + \
                                    " (user_id,townhall_level,time,age,prev_time,prev_age,next_time,next_age) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE user_id=user_id;",
                                    rows)

            # parse tech unlock timing
            if input['do_tech']:
                cur.executemany("INSERT INTO "+sql_util.sym(input['tech_table']) + " (user_id, tech_name, level, time, age) VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE user_id=user_id;",
                                [(user['user_id'], tech, level, user['account_creation_time'] + int(sage), int(sage)) \
                                 for tech in gamedata['tech'] \
                                 for sage, level in user.get('tech:'+tech+'_at_time', {}).iteritems()
                                 ])

                # summary dimensions, kind, spec, level, is_maxed
                for spec, level in user.get('tech',{}).iteritems():
                    if spec in gamedata['tech']:
                        is_maxed = 1 if (len(gamedata['tech'][spec]['research_time']) > 1 and level >= len(gamedata['tech'][spec]['research_time'])) else 0
                        k = summary_vals + ('tech', spec, level, is_maxed)
                        upgrade_achievement_counters[k] = upgrade_achievement_counters.get(k,0) + 1
                        if is_maxed:
                            # one row for "any" maxed tech
                            km = summary_vals + ('tech', 'ANY', -1, 1)
                            upgrade_achievement_counters[km] = upgrade_achievement_counters.get(km,0) + 1

            # parse building upgrade timing
            if input['do_buildings']:
                cur.executemany("INSERT INTO "+sql_util.sym(input['buildings_table']) + " (user_id, building, max_level, time, age) VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE user_id=user_id;",
                                [(user['user_id'], building, level, user['account_creation_time'] + int(sage), int(sage)) \
                                 for building in gamedata['buildings'] \
                                 for sage, level in user.get(building+'_level_at_time', user.get('building:'+building+':max_level_at_time', {})).iteritems()
                                 ])

                # summary dimensions, kind, spec, level, is_maxed
                for spec in gamedata['buildings']:
                    level = max(user.get('building:'+spec+':max_level_at_time',{'asdf':0}).itervalues())
                    if level >= 1:
                        is_maxed = 1 if (len(gamedata['buildings'][spec]['build_time']) > 1 and level >= len(gamedata['buildings'][spec]['build_time'])) else 0
                        k = summary_vals + ('building', spec, level, is_maxed)
                        upgrade_achievement_counters[k] = upgrade_achievement_counters.get(k,0) + 1
                        if is_maxed:
                            # one row for "any" maxed building
                            km = summary_vals + ('building', 'ANY', -1, 1)
                            upgrade_achievement_counters[km] = upgrade_achievement_counters.get(km,0) + 1

            # update LTV estimate
            if input['do_ltv']:
                ltv_est = SkynetLTV.ltv_estimate(input['game_id'], gamedata, user, cache.update_time(), use_post_install_data = 9999999)
                if ltv_est is not None:
                    cur.execute("INSERT INTO "+sql_util.sym(input['ltv_table']) + " (user_id, est_90d) VALUES (%s,%s) ON DUPLICATE KEY UPDATE user_id=user_id;",
                                (user['user_id'], ltv_est))

            # alts table
            if input['do_alts']:
                alt_accounts = user.get('known_alt_accounts', None)
                if alt_accounts and type(alt_accounts) is dict:
                    cur.executemany("INSERT INTO "+sql_util.sym(input['alts_table']) + \
                                    " (user_id, other_id, lower_id, higher_id, logins, attacks, last_simultaneous_login, last_ip)" + \
                                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                    [(user['user_id'], int(alt_sid),
                                      min(user['user_id'], int(alt_sid)),
                                      max(user['user_id'], int(alt_sid)),
                                      alt.get('logins',1), alt.get('attacks',1), alt.get('last_login',None), alt.get('last_ip',None)) \
                                     for alt_sid, alt in alt_accounts.iteritems() if alt.get('logins',1) > 0 and not alt.get('ignore',False)])

            # army composition table
            ACTIVE_PLAYER_RECENCY = 7*86400 # only include players active more recently than this
            if input['do_army_composition'] and time_now - user.get('last_login_time', 0) < ACTIVE_PLAYER_RECENCY:
                def update_army_composition_entry(kind, spec, level, location, count):
                    # note: use non-NULL defaults so that the ON DUPLICATE KEY UPDATE will work
                    key = collapsed_summary_vals + (kind, spec or '', level or 0, location or '')
                    army_composition[key] = army_composition.get(key, 0) + count

                # track number of players
                update_army_composition_entry('player', None, None, None, 1)

                # track unit composition
                for squad in user.get('unit_counts', {}):
                    for unit, count in user['unit_counts'][squad].iteritems():
                        spec, level_str = unit.split(':L')
                        level = int(level_str)
                        assert 0 <= level <= INT2_MAX
                        update_army_composition_entry('unit', spec, level, squad, count)

                # track building composition
                for building, count in user.get('building_counts', {}).iteritems():
                    spec, level_str = building.split(':L')
                    level = int(level_str)
                    assert 0 <= level <= INT2_MAX
                    update_army_composition_entry('building', spec, level, 'home', count)

                # track equipment composition
                for game_object in user.get('equipment_counts', {}):
                    for item, count in user['equipment_counts'][game_object].iteritems():
                        spec, level = get_item_spec_level(gamedata, item)
                        if spec is None: continue
                        assert 0 <= level <= INT2_MAX

                        if game_object in gamedata['buildings']:
                            location = 'building'
                        elif game_object in gamedata['units']:
                            location = 'unit'
                        else:
                            location = 'unknown'

                        update_army_composition_entry('equipment', spec, level, location, count)

                for item, count in user.get('inventory_counts', {}).iteritems():
                    spec, level = get_item_spec_level(gamedata, item)
                    if spec is None: continue
                    assert 0 <= level <= INT2_MAX
                    if 'equip' in gamedata['items'].get(spec, {}):
                        # note: for now, we only track EQUIPPABLE items in inventory
                        update_army_composition_entry('equipment', spec, level, 'inventory', count)

                # track tech composition
                for tech, level in user.get('tech', {}).iteritems():
                    assert 0 <= level <= INT2_MAX
                    update_army_composition_entry('tech', tech, level, None, 1)

            # current resource levels table
            if input['do_resource_levels'] and time_now - user.get('last_login_time', 0) < ACTIVE_PLAYER_RECENCY:
                def update_resource_levels_entry(resource, amount):
                    assert resource
                    key = summary_vals + (resource,)
                    if key in resource_levels:
                        resource_levels[key][0] += amount
                        resource_levels[key][1] += 1 # N
                    else:
                        resource_levels[key] = [amount, 1]

                update_resource_levels_entry('gamebucks', user.get('gamebucks_balance', 0))
                for res in gamedata['resources']:
                    update_resource_levels_entry(res, user.get(res, 0))

            # current A/B test memberships
            for test_name in gamedata['abtests']:
                if test_name in user:
                    group_name = user[test_name]
                    abtest_memberships[(user_id, test_name)] = (group_name, -1)

            batch += 1
            total += 1
            if input['commit_interval'] > 0 and batch >= input['commit_interval']:
                batch = 0
                flush()

        # flush last commits
        flush()

# main program
if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    time_now = int(time.time())

    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    parallel = 1
    field_mode = 'ALL'
    do_townhall = True
    do_tech = True
    do_buildings = True
    do_ltv = True
    do_alts = True
    do_army_composition = True
    do_resource_levels = True
    do_prune = False
    use_local = False
    skip_developer = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['parallel=','lite','use-local','include-developers','prune'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--parallel': parallel = int(val)
        elif key == '--lite':
            field_mode = 'lite'
            do_townhall = False
            #do_tech = False
            #do_buildings = False
            #do_ltv = False
            do_army_composition = False
        elif key == '--use-local': use_local = True
        elif key == '--include-developers': skip_developer = False
        elif key == '--prune': do_prune = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    with SpinSingletonProcess.SingletonProcess('upcache_to_mysql-%s' % game_id):
        cache = open_cache(game_id, use_local=use_local, skip_developer=skip_developer)

        # mapping of upcache fields to MySQL
        fields = {}

        # PASS 1 - get field names
        if 1:
            tasks = [{'game_id':game_id, 'cache_info':cache.info,
                      'mode':'get_fields', 'field_mode': field_mode, 'segnum':segnum,
                      'commit_interval':commit_interval, 'verbose':verbose, 'use_local':use_local,
                      'skip_developer':skip_developer, 'time_now':time_now} for segnum in range(0, cache.num_segments())]

            if parallel <= 1:
                output = [do_slave(task) for task in tasks]
            else:
                output = SpinParallel.go(tasks, [sys.argv[0], '--slave'], on_error='continue', nprocs=parallel, verbose=False)

            # reduce
            for slave_fields in output:
                for key, val in slave_fields.iteritems():
                    if val is not None:
                        fields[key] = val

            # filter field names
            for key, val in fields.items():
                if val is None: del fields[key]
            if 'user_id' in fields: del fields['user_id'] # handled specially

            if verbose: print 'fields =', fields

        # PASS 2 - dump the rows
        if 1:
            cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
            con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
            cur = con.cursor()

            upcache_table = cfg['table_prefix']+game_id+'_upcache'
            if field_mode != 'ALL':
                upcache_table += '_'+field_mode
            townhall_table = cfg['table_prefix']+game_id+'_townhall_at_time'
            tech_table = cfg['table_prefix']+game_id+'_tech_at_time'
            upgrade_achievement_table = cfg['table_prefix']+game_id+'_upgrade_achievement'
            buildings_table = cfg['table_prefix']+game_id+'_building_levels_at_time'
            facebook_campaign_map_table = cfg['table_prefix']+game_id+'_facebook_campaign_map'
            ltv_table = cfg['table_prefix']+game_id+'_user_ltv'
            alts_table = cfg['table_prefix']+game_id+'_alt_accounts'
            army_composition_table = cfg['table_prefix']+game_id+'_active_player_army_composition'
            resource_levels_table = cfg['table_prefix']+game_id+'_active_player_resource_levels'
            abtests_table = cfg['table_prefix']+game_id+'_abtests'

            # these are the tables that are replaced entirely each run
            atomic_tables = [upcache_table,facebook_campaign_map_table] + \
                            ([townhall_table] if do_townhall else []) + \
                            ([upgrade_achievement_table] if (do_tech or do_buildings) else []) + \
                            ([buildings_table] if do_buildings else []) + \
                            ([tech_table] if do_tech else []) + \
                            ([ltv_table] if do_ltv else []) + \
                            ([alts_table] if do_alts else [])

            for TABLE in atomic_tables:
                # get rid of temp tables
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(TABLE+'_temp'))
                # ensure that non-temp version actually exists, so that the RENAME operation below will work
                sql_util.ensure_table(cur, TABLE, {'fields': [('unused','INT4')]})
            con.commit()

            # set up FACEBOOK_CAMPAIGN_MAP table
            for t in (facebook_campaign_map_table, facebook_campaign_map_table+'_temp'):
                sql_util.ensure_table(cur, t,
                                      {'fields': [('from', 'VARCHAR(64) NOT NULL PRIMARY KEY'),
                                                  ('to', 'VARCHAR(64)')]})
            sql_util.do_insert_batch(cur, facebook_campaign_map_table+'_temp',
                                     [[('from',k),('to',v)] for k,v in SpinUpcache.FACEBOOK_CAMPAIGN_MAP.iteritems()])

            sql_util.ensure_table(cur, abtests_table, abtests_schema)

            sorted_field_names = sorted(fields.keys())

            sql_util.ensure_table(cur, upcache_table+'_temp', {'fields': [('user_id', 'INT4 NOT NULL PRIMARY KEY')] +
                                                                         [(key, fields[key]) for key in sorted_field_names],
                                                               'indices': {'by_account_creation_time': {'keys': [('account_creation_time','ASC')]},
                                                                           'by_last_login_time': {'keys': [('last_login_time','ASC')]}}
                                                               })

            if do_townhall:
                sql_util.ensure_table(cur, townhall_table+'_temp',
                                      {'fields': [('user_id','INT4 NOT NULL'),
                                                  ('time','INT8 NOT NULL'),
                                                  ('age','INT8 NOT NULL'),
                                                  ('townhall_level','INT4 NOT NULL'),
                                                  # also include time/age at which previous townhall_level was reached, to allow easy interval computations
                                                  ('prev_time', 'INT8'),
                                                  ('prev_age', 'INT8'),
                                                  ('next_time', 'INT8'),
                                                  ('next_age', 'INT8'),
                                                  ]}) # make index after load

            if do_tech:
                sql_util.ensure_table(cur, tech_table+'_temp',
                                      {'fields': [('user_id','INT4 NOT NULL'),
                                                  ('level','INT4 NOT NULL'),
                                                  ('time','INT8 NOT NULL'),
                                                  ('age','INT8 NOT NULL'),
                                                  ('tech_name','VARCHAR(200) NOT NULL')],
                                       # note: make index incrementally rather than all at once at the end, to avoid long lockup of the database
                                       'indices': {'lev_then_time': {'unique': False, # technically unique, but don't waste time enforcing it
                                                                     'keys': [('user_id','ASC'),('tech_name','ASC'),('level','ASC'),('time','ASC')]}}
                                       })

            if do_buildings:
                sql_util.ensure_table(cur, buildings_table+'_temp',
                                      {'fields': [('user_id','INT4 NOT NULL'),
                                                  ('max_level','INT4 NOT NULL'),
                                                  ('time','INT8 NOT NULL'),
                                                  ('age','INT8 NOT NULL'),
                                                  ('building','VARCHAR(64) NOT NULL')],
                                       # note: make index incrementally rather than all at once at the end, to avoid long lockup of the database
                                       'indices': {'lev_then_time': {'unique': False, # technically unique, but don't waste time enforcing it
                                                                     'keys': [('user_id','ASC'),('building','ASC'),('max_level','ASC'),('time','ASC')]}}
                                       })

            if do_tech or do_buildings:
                sql_util.ensure_table(cur, upgrade_achievement_table+'_temp', achievement_table_schema(sql_util))

            if do_ltv:
                sql_util.ensure_table(cur, ltv_table+'_temp',
                                      {'fields': [('user_id','INT4 NOT NULL PRIMARY KEY'),
                                                  ('est_90d','FLOAT4 NOT NULL')]})

            if do_alts:
                sql_util.ensure_table(cur, alts_table+'_temp',
                                      {'fields': [('user_id','INT4 NOT NULL'),
                                                  ('other_id','INT4 NOT NULL'),
                                                  ('lower_id','INT4 NOT NULL'),
                                                  ('higher_id','INT4 NOT NULL'),
                                                  ('logins','INT4'),
                                                  ('attacks','INT4'),
                                                  ('last_simultaneous_login','INT8'),
                                                  ('last_ip', 'VARCHAR(64)'),
                                                  ],
                                       'indices': {'by_user_id': {'keys': [('user_id','ASC')]},
                                                   # to uniquify alt "groups", knock out any user_id that appears as a higher_id in this table
                                                   'by_higher_id': {'keys': [('higher_id','ASC')]},
                                                   #'by_logins': {'keys': [('logins','ASC')]},
                                                   #'by_attacks': {'keys': [('attacks','ASC')]},
                                                   }
                                       })

            if do_army_composition:
                sql_util.ensure_table(cur, army_composition_table, army_composition_table_schema(sql_util))
            if do_resource_levels:
                sql_util.ensure_table(cur, resource_levels_table, resource_levels_table_schema(sql_util))

            con.commit()

            try:
                tasks = [{'game_id':game_id, 'cache_info':cache.info, 'dbconfig':cfg,
                          'do_townhall': do_townhall, 'do_tech': do_tech, 'do_buildings': do_buildings,
                          'do_ltv': do_ltv, 'ltv_table': ltv_table+'_temp',
                          'do_alts': do_alts, 'alts_table': alts_table+'_temp',
                          'upcache_table': upcache_table+'_temp',
                          'townhall_table': townhall_table+'_temp',
                          'tech_table': tech_table+'_temp',
                          'upgrade_achievement_table': upgrade_achievement_table+'_temp',
                          'buildings_table': buildings_table+'_temp',
                          'do_army_composition': do_army_composition, 'army_composition_table': army_composition_table,
                          'do_resource_levels': do_resource_levels, 'resource_levels_table': resource_levels_table,
                          'abtests_table': abtests_table,
                          'mode':'get_rows', 'sorted_field_names':sorted_field_names,
                          'segnum':segnum,
                          'commit_interval':commit_interval, 'verbose':verbose, 'use_local':use_local,
                          'skip_developer':skip_developer, 'time_now':time_now} for segnum in range(0, cache.num_segments())]

                if parallel <= 1:
                    output = [do_slave(task) for task in tasks]
                else:
                    output = SpinParallel.go(tasks, [sys.argv[0], '--slave'], on_error='continue', nprocs=parallel, verbose=False)

            except:
                for TABLE in atomic_tables:
                    cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(TABLE+'_temp'))
                con.commit()
                raise

            if verbose: print 'inserts done'

            if verbose: print 'replacing old tables'
            for TABLE in atomic_tables:
                # t -> t_old, t_temp -> t
                cur.execute("RENAME TABLE "+\
                            sql_util.sym(TABLE)+" TO "+sql_util.sym(TABLE+'_old')+","+\
                            sql_util.sym(TABLE+'_temp')+" TO "+sql_util.sym(TABLE))
                con.commit()

                # kill t_old
                cur.execute("DROP TABLE "+sql_util.sym(TABLE+'_old'))
                con.commit()

            # created incrementally now
            #if verbose: print 'building indices for', upcache_table
            #cur.execute("ALTER TABLE "+sql_util.sym(upcache_table)+" ADD INDEX by_account_creation_time (account_creation_time), ADD INDEX by_last_login_time (last_login_time)")

            if do_townhall:
                if verbose: print 'building indices for', townhall_table
                cur.execute("ALTER TABLE "+sql_util.sym(townhall_table)+" ADD INDEX ts (user_id, townhall_level, time), ADD INDEX ts2 (user_id, time, townhall_level), ADD INDEX by_th_time (townhall_level, time)")

            if do_tech:
                pass # note: index is created incrementally now, to avoid long lockup of database
                #if verbose: print 'building indices for', tech_table
                #cur.execute("ALTER TABLE "+sql_util.sym(tech_table)+" ADD INDEX lev_then_time (user_id, tech_name, level, time)")
            if do_buildings:
                pass # note: index is created incrementally now, to avoid long lockup of database
                #if verbose: print 'building indices for', buildings_table
                #cur.execute("ALTER TABLE "+sql_util.sym(buildings_table)+" ADD INDEX lev_then_time (user_id, building, max_level, time)")

            con.commit()

            if do_prune:
                for table in army_composition_table, resource_levels_table:
                    if verbose: print 'pruning', table

                    KEEP_DAYS = 999
                    old_limit = time_now - KEEP_DAYS * 86400

                    cur.execute("DELETE FROM "+sql_util.sym(table)+" WHERE time < %s", [old_limit])
                    con.commit()

            if verbose: print 'all done.'
