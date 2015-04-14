#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump gamedata unit/building/item/etc stats to SQL for analytics use

import sys, getopt
import SpinConfig
import SpinJSON
import SpinSQLUtil
import MySQLdb

stats_schema = {
    'fields': [('kind', 'VARCHAR(16) NOT NULL'),
               ('spec', 'VARCHAR(64) NOT NULL'),
               ('stat', 'VARCHAR(64) NOT NULL'),
               ('level', 'INT1'),
               ('value_num', 'FLOAT8'),
               ('value_str', 'VARCHAR(128)')],
    'indices': {'master': {'keys': [('kind','ASC'),('spec','ASC'),('stat','ASC'),('level','ASC')]}}
    }
crafting_recipes_schema = {
    'fields': [('recipe_id', 'VARCHAR(64) NOT NULL'),
               ('recipe_level', 'INT4'),
               ('is_output', 'TINYINT(1) NOT NULL'),
               ('resource', 'VARCHAR(64) NOT NULL'),
               ('level', 'INT1'),
               ('amount', 'INT4 NOT NULL')],
    'indices': {'master': {'keys': [('recipe_id','ASC'),('is_output','ASC')]}}
    }
fishing_slates_schema = {
    'fields': [('slate_id', 'VARCHAR(64) NOT NULL'),
               ('recipe_id', 'VARCHAR(64) NOT NULL')],
    'indices': {'by_slate': {'keys': [('slate_id','ASC')]}}
    }
quest_stats_schema = {
    'fields': [('name', 'VARCHAR(64) NOT NULL'),
               ('ui_priority', 'INT4'),
               ('townhall_level', 'INT1'),
               ('reward_xp', 'INT4'),
               ('reward_gamebucks', 'INT4'),
               ('reward_iron', 'INT4'),
               ('reward_water', 'INT4'),
               ('reward_res3', 'INT4'),
               ('goal_history_key', 'VARCHAR(64)'),
               ('goal_history_value', 'INT4'),
               ('goal_building_spec', 'VARCHAR(64)'),
               ('goal_building_qty', 'INT1'),
               ('goal_building_level', 'INT1'),
               ],
    'indices': {'by_name': {'keys': [('name','ASC')]}}
    }

# commit block of inserts to a table
def flush_keyvals(sql_util, cur, tbl, keyvals):
    if not dry_run:
        try:
            sql_util.do_insert_batch(cur, tbl, keyvals)
        except MySQLdb.Warning as e:
            raise Exception('while inserting into %s:\n' % tbl+'\n'.join(map(repr, keyvals))+'\n'+repr(e))
        con.commit()
    del keyvals[:]

# iterate through (level, num_value, str_value) of a possibly per-level value
# but store non-leveled values as a single entry with level = None
def leveled_quantity_iter(val, num_levels, reason):
    val_type = None # 'num' or 'str'
    val_levels = None

    if type(val) in (int, float): # single number
        val_type = 'num'
        val_list = [float(val)]
    elif type(val) in (str, unicode): # single string
        val_type = 'str'
        val_list = [val]

    elif type(val) is list and len(val) == num_levels:
        val_levels = num_levels
        if type(val[0]) in (int, float): # per-level number
            val_type = 'num'
            val_list = map(float, val)
        elif type(val[0]) in (str, unicode): # per-level string
            val_type = 'str'
            val_list = val

    if val_type == 'str':
        if key == 'name' or key == 'icon' or (key.startswith('ui_') and key != 'ui_name'):
            # filter out unnecessary strings
            return

    if not val_type: return # not a recognized value type

    for i in xrange(len(val_list)):
        v = val_list[i]
        if val_type == 'num':
            if v < -2**31 or v > 2**31:
                print 'value out of range: % L%d: %s' % (reason, i+1, repr(v))
        elif val_type == 'str':
            if len(v) > 64:
                print 'value out of range: %s L%d: %s (len %d)' % (reason, i+1, v, len(v))

    for i in xrange(val_levels) if val_levels else [0,]:
        yield (i+1 if val_levels else None, val_list[i] if val_type == 'num' else None, val_list[i] if val_type == 'str' else None)

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if verbose or True:
        from warnings import filterwarnings
        filterwarnings('error', category = MySQLdb.Warning)
    else:
        sql_util.disable_warnings()

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    fishing_json_file = SpinConfig.gamedata_component_filename('fishing_slates.json', override_game_id = game_id)
    try:
        fishing_json_fd = open(fishing_json_file)
    except IOError:
        fishing_json_fd = None # no fishing in this game

    fishing_slates = SpinConfig.load_fd(fishing_json_fd, stripped=True) if fishing_json_fd else None

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    if not dry_run:
        con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        cur = con.cursor(MySQLdb.cursors.DictCursor)
    else:
        cur = None
    stats_table = cfg['table_prefix']+game_id+'_stats'
    recipes_table = cfg['table_prefix']+game_id+'_crafting_recipes'
    fishing_slates_table = cfg['table_prefix']+game_id+'_fishing_slates'
    quest_stats_table = cfg['table_prefix']+game_id+'_quest_stats'

    if not dry_run:
        filterwarnings('ignore', category = MySQLdb.Warning)
        for tbl, schema in ((stats_table, stats_schema),
                            (recipes_table, crafting_recipes_schema),
                            (fishing_slates_table, fishing_slates_schema),
                            (quest_stats_table, quest_stats_schema)):
            cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl+'_temp'))
            sql_util.ensure_table(cur, tbl, schema)
            sql_util.ensure_table(cur, tbl+'_temp', schema)

        # TIME PRICING FORMULA
        # has to be created dynamically because gamedata.store influences the formula
        cur.execute("DROP FUNCTION IF EXISTS time_price") # obsolete
        min_per_cred = gamedata['store']['speedup_minutes_per_credit']
        if type(min_per_cred) is dict:
            min_per_cred = min_per_cred['default']
        bucks_per_min = float(gamedata['store']['gamebucks_per_fbcredit'])/min_per_cred
        cur.execute("CREATE FUNCTION time_price (amount INT8) RETURNS INT8 DETERMINISTIC RETURN IF(amount=0, 0, IF(amount>0,1,-1) * FLOOR(%f *ABS(amount)/60)+1)" % bucks_per_min)

        # RESOURCE PRICING FORMULAS
        # returns the gamebucks price of an amount of fungible resources

        # these have to be created dynamically because gamedata.store influences the formulas

        cur.execute("DROP FUNCTION IF EXISTS iron_water_price") # obsolete

        for res in gamedata['resources']:
            cur.execute("DROP FUNCTION IF EXISTS "+res+"_price")
            def get_parameter(p, resname):
                ret = gamedata['store'][p]
                if type(ret) is dict:
                    ret = ret[resname]
                return ret
            formula = get_parameter('resource_price_formula', res)
            scale_factor = get_parameter('resource_price_formula_scale', res)
            if formula == 'legacy_exp_log':
                gamebucks_per_fbcredit = gamedata['store']['gamebucks_per_fbcredit']
                func = "IF(ABS(amount)<2, 1, %f*0.06*EXP(0.75*(LOG10(ABS(amount))-2.2*POW(LOG10(ABS(amount)),-1.25))))" % (scale_factor * gamebucks_per_fbcredit)
            elif formula == 'piecewise_linear':
                points = get_parameter('resource_price_formula_piecewise_linear_points', res)
                func = ""
                for i in xrange(1, len(points)):
                    slope = float(points[i][1] - points[i - 1][1]) / (points[i][0] - points[i - 1][0])
                    seg = "%f * (%f + %f * (amount - %f))" % (scale_factor, points[i-1][1], slope, points[i-1][0])
                    if i != len(points) - 1:
                        seg = "IF(amount < %f,%s," % (points[i][0], seg)
                    func += seg
                func += ")" * (len(points)-2)
            else:
                raise Exception('unknown resource_price_formula '+formula)
            final = "CREATE FUNCTION "+res+"_price (amount INT8) RETURNS INT8 DETERMINISTIC RETURN IF(amount=0, 0, IF(amount>0,1,-1) * GREATEST(1, CEIL("+func+")))"
            cur.execute(final)

        # some tables have res3 columns even if the game itself doesn't have res3.
        # Create a dummy function to satisfy queries.
        if 'res3' not in gamedata['resources']:
            cur.execute("DROP FUNCTION IF EXISTS res3_price")
            cur.execute("CREATE FUNCTION res3_price (amount INT8) RETURNS INT8 DETERMINISTIC RETURN 0")

        filterwarnings('error', category = MySQLdb.Warning)
        con.commit()

    # OBJECT STATS

    total = 0
    keyvals = []

    for objects, kind in ((gamedata['units'],'unit'),
                          (gamedata['buildings'],'building'),
                          (gamedata['tech'],'tech'),
                          (gamedata['items'],'item'),
                          (gamedata['crafting']['recipes'],'recipe')
                          ):
        for specname, data in objects.iteritems():
            if kind == 'unit': num_levels = len(data['max_hp'])
            elif kind == 'building': num_levels = len(data['build_time'])
            elif kind == 'tech': num_levels = len(data['research_time'])
            elif kind == 'item': num_levels = data.get('max_level',1)
            elif kind == 'recipe': num_levels = data.get('max_level',1)

            # add max_level stat (redundant, but makes writing other queries easier)
            if num_levels > 1 or kind in ('unit','building','tech'):
                keyvals.append([('kind',kind),
                                ('spec',specname),
                                ('stat','max_level'),
                                ('level',None),
                                ('value_num',num_levels),
                                ('value_str',None)])

            for key, val in data.iteritems():
                reason = '%s %s %s' % (kind, specname, key)
                keyvals += [[('kind',kind),
                             ('spec',specname),
                             ('stat',key),
                             ('level',level),
                             ('value_num',num_val),
                             ('value_str',str_val)] \
                            for level, num_val, str_val in leveled_quantity_iter(val, num_levels, reason)]

                total += len(keyvals)
                if commit_interval > 0 and len(keyvals) >= commit_interval:
                    flush_keyvals(sql_util, cur, stats_table+'_temp', keyvals)
                    if verbose: print total, 'object stats inserted'

    flush_keyvals(sql_util, cur, stats_table+'_temp', keyvals)
    if not dry_run: con.commit()
    if verbose: print 'total', total, 'object stats inserted'

    # CRAFTING RECIPE INGREDIENTS/PRODUCTS

    total = 0
    keyvals = []

    for specname, data in gamedata['crafting']['recipes'].iteritems():
        reason = 'crafting recipe: %s' % specname
        num_levels = data.get('max_level',1)

        keyvals += [(('recipe_id', specname),
                     ('recipe_level',level),
                     ('is_output', 0),
                     ('resource', 'time'),
                     ('level',None),
                     ('amount', num_val)) \
                    for level, num_val, str_val in leveled_quantity_iter(data['craft_time'], num_levels, reason)]

        if 'cost' in data:
            if type(data['cost']) is list:
                cost_list = data['cost']
                val_levels = num_levels
            else:
                cost_list = [data['cost']]
                val_levels = None
            for i in xrange(val_levels) if val_levels else [0,]:
                for res, amt in cost_list[i].iteritems():
                    keyvals += [(('recipe_id', specname),
                                 ('recipe_level',i+1 if val_levels else None),
                                 ('is_output', 0),
                                 ('resource', res),
                                 ('level', None),
                                 ('amount', amt))]

        if 'ingredients' in data:
            assert type(data['ingredients']) is list
            if len(data['ingredients']) > 0:

                if type(data['ingredients'][0]) is list: # per-level list
                    ingr_list = data['ingredients']
                    assert len(ingr_list) == num_levels
                    val_levels = num_levels
                else:
                    ingr_list = [data['ingredients']] # same for all levels
                    val_levels = None
            for i in xrange(val_levels) if val_levels else [0,]:
                for entry in ingr_list[i]:
                    keyvals += [(('recipe_id', specname),
                                 ('recipe_level',i+1 if val_levels else None),
                                 ('is_output', 0),
                                 ('resource', entry['spec']),
                                 ('level', entry.get('level',None)),
                                 ('amount', entry.get('stack',1)))]
        if 'product' in data:
            assert type(data['product']) is list
            if len(data['product']) > 0:
                if type(data['product'][0]) is list: # per-level list
                    prod_list = data['product']
                    assert len(prod_list) == num_levels
                    val_levels = num_levels
                else:
                    prod_list = [data['product']]
                    val_levels = None
                for i in xrange(val_levels) if val_levels else [0,]:
                    for entry in prod_list[i]:
                        if 'spec' not in entry:
                            raise Exception('cannot parse crafting recipe product: %s' % repr(entry))
                        keyvals += [(('recipe_id', specname),
                                     ('recipe_level', i+1 if val_levels else None),
                                     ('is_output', 1),
                                     ('resource', entry['spec']),
                                     ('level', entry.get('level',None)),
                                     ('amount', entry.get('stack',1)))]

        total += len(keyvals)
        if commit_interval > 0 and len(keyvals) >= commit_interval:
            flush_keyvals(sql_util, cur, recipes_table+'_temp', keyvals)
            if verbose: print total, 'crafting recipe inputs/outputs inserted'

    flush_keyvals(sql_util, cur, recipes_table+'_temp', keyvals)
    if not dry_run: con.commit()
    if verbose: print 'total', total, 'crafting recipe inputs/outputs inserted'

    # QUEST STATS
    if 1:
        total = 0
        for name, data in gamedata['quests'].iteritems():
            keyvals = []
            # straight fields
            for FIELD in ('name', 'ui_priority', 'townhall_level', 'reward_xp', 'reward_gamebucks', 'reward_iron', 'reward_water', 'reward_res3'):
                if FIELD in data:
                    keyvals.append((FIELD, data[FIELD]))
            # do some basic parsing of the goal predicate
            if data['goal']['predicate'] == 'PLAYER_HISTORY':
                keyvals.append(('goal_history_key', data['goal']['key']))
                keyvals.append(('goal_history_value', data['goal']['value']))
            elif data['goal']['predicate'] in ('BUILDING_LEVEL','BUILDING_QUANTITY'):
                keyvals.append(('goal_building_spec', data['goal']['building_type']))
                keyvals.append(('goal_building_qty', data['goal'].get('trigger_qty',1)))
                keyvals.append(('goal_building_level', data['goal'].get('trigger_level',1)))
            if not dry_run: sql_util.do_insert(cur, quest_stats_table+'_temp', keyvals)
            total += 1
        if not dry_run: con.commit()
        if verbose: print 'total', total, 'quest stats inserted'

    # FISHING SLATES
    if fishing_slates:
        total = 0
        keyvals = []

        for slate_name, data in fishing_slates.iteritems():
            for recipe_id in data['recipes']:
                keyvals.append((('slate_id', slate_name),
                                ('recipe_id', recipe_id)))
                total += 1
        flush_keyvals(sql_util, cur, fishing_slates_table+'_temp', keyvals)
        if not dry_run: con.commit()
        if verbose: print 'total', total, 'fishing slate entries inserted'

    if not dry_run:
        filterwarnings('ignore', category = MySQLdb.Warning)
        for tbl in (stats_table, recipes_table, fishing_slates_table, quest_stats_table):
            cur.execute("RENAME TABLE "+\
                        sql_util.sym(tbl)+" TO "+sql_util.sym(tbl+'_old')+","+\
                        sql_util.sym(tbl+'_temp')+" TO "+sql_util.sym(tbl))
            cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl+'_old'))

        con.commit()
