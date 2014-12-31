#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import random, copy, bisect

def max_slots_needed(tables, tab):
    assert type(tab) is list
    ret = 0
    for data in tab:
        if 'table' in data: ret = max(ret, max_slots_needed(tables, tables[data['table']]['loot']))
        elif 'cond' in data: ret = max(ret, max(max_slots_needed(tables, result) for pred, result in data['cond']))
        elif 'spec' in data: ret = max(ret, 1)
        elif 'multi' in data:ret = max(ret, sum((max_slots_needed(tables, item) for item in data['multi']),1))
        elif data.get('nothing',False): continue
        else: raise Exception('unhandled loot table entry %s' % repr(data))
    return ret

# get looted item(s)
# tables = gamedata['loot_tables']
# tab = the table you want the result from
# cond_resolver = called to resolve truth value of predicates of "cond" items

def get_loot(tables, tab, tabname = 'toplevel', depth = 0, cond_resolver = None, rand_func = random.random, verbose = False):
    assert type(tab) is list
    if verbose:
        print '\t'*depth, '->', tabname

    breakpoints = []
    bp = 0.0
    for item in tab:
        weight = item.get('weight',1.0)
        bp += weight
        breakpoints.append(bp)

    #print 'BREAKPOINTS', breakpoints

    r = rand_func()
    r *= breakpoints[-1]

    groupnum = min(bisect.bisect(breakpoints, r), len(breakpoints)-1)
    #print 'PICKED', groupnum

    winner = tab[groupnum]

    data = winner
    if 'table' in data:
        ret = get_loot(tables, tables[data['table']]['loot'], tabname = data['table'], cond_resolver = cond_resolver, rand_func = rand_func, depth = depth+1)
    elif 'cond' in data:
        ret = []
        for pred, result in data['cond']:
            if cond_resolver(pred):
                ret = get_loot(tables, result if (type (result) is list) else [result], cond_resolver = cond_resolver, rand_func = rand_func, depth = depth+1)
                break
    elif 'spec' in data:
        # make a copy of the entry, just in case the caller is naughty and mutates it
        ret_item = copy.deepcopy(data)
        if 'weight' in ret_item: del ret_item['weight']
        if 'random_stack' in ret_item:
            random_stack = ret_item['random_stack']
            del ret_item['random_stack']
            # pick a random stack amount between the min and max, inclusive
            ret_item['stack'] = int(random_stack[0] + rand_func()*(random_stack[1]+1-random_stack[0]))
        ret = [ret_item]
    elif 'multi' in data:
        # combine multiple loot drops into a flat list
        ret = sum([get_loot(tables, x if (type(x) is list) else [x], cond_resolver = cond_resolver, rand_func = rand_func, depth = depth+1) for x in data['multi']], [])
        if 'multi_stack' in data:
            for item in ret:
                item['stack'] = item.get('stack',1) * data['multi_stack']
    elif data.get('nothing',False):
        return []
    else:
        raise Exception('invalid loot table entry %s' % repr(data))
    return ret

if __name__ == "__main__":
    import SpinJSON, sys, SpinConfig, getopt, functools

    verbose = False
    trials = 10000
    game_id = SpinConfig.game()

    opts, args = getopt.gnu_getopt(sys.argv, 'g:', [])

    for key, val in opts:
        if key == '-g':
            game_id = val

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    tables = SpinJSON.load(open(SpinConfig.gamedata_component_filename("loot_tables.json", override_game_id = game_id)))

    def pred_resolver(verbose, pred):
        if verbose: print 'RESOLVING', pred
        if pred['predicate'] == "ALWAYS_TRUE": return True
        return False

    if len(args) >= 2:
        tables_to_test = args[1:]
    else:
        tables_to_test = ("store_random_item",)

    by_item = {}

    for toplevel in tables_to_test:
        for i in xrange(trials):
            result = get_loot(tables, tables[toplevel]['loot'], cond_resolver = functools.partial(pred_resolver, verbose), verbose = False)
            if verbose: print 'FROM "%s" YOU GOT:' % toplevel,
            for item in result:
                by_item[item['spec']] = by_item.get(item['spec'],0) + item.get('stack',1)
                spec = gamedata['items'][item['spec']]
                if verbose:
                    rarity = spec.get('rarity',0)
                    if rarity > 0:
                        rarity_str = '*' * rarity
                    else:
                        rarity_str = ''
                    print ' %s %dx %s' % (rarity_str, item.get('stack',1), spec['ui_name']),
            if verbose: print

    VALUES = {'boost_iron_10000': 0.01,
              'boost_water_10000': 0.01,
              'boost_iron_20000': 0.02,
              'boost_water_20000': 0.02,
              'boost_iron_50000': 0.05,
              'boost_water_50000': 0.05,
              'boost_iron_100000': 0.1,
              'boost_water_100000': 0.1,
              'boost_iron_250000': 0.25,
              'boost_water_250000': 0.25,
              'boost_iron_500000': 0.5,
              'boost_water_500000': 0.5,
              'boost_iron_1000000': 1.0,
              'boost_water_1000000': 1.0,
              'all_damage_boost_100pct': 0.75,
              'attack_space_boost_10pct': 0.2,
              'attack_space_boost_20pct': 0.5,
              'attack_space_boost_50pct': 0.6,
              'protection_1h': 0.05625,
              'protection_3h': 0.1125,
              'protection_6h': 0.225,
              'protection_12h': 0.45,
              'protection_1d': 0.9,
              'rover_damage_boost_20pct': 0.1,
              'rover_damage_boost_50pct': 0.2,
              'rover_damage_boost_100pct': 0.3,
              'detonator_droid_damage_boost_50pct': 0.10,
              'detonator_droid_speed_boost_50pct': 0.05,
              'elevation_droid_damage_boost_25pct': 0.10,
              'elevation_droid_damage_boost_50pct': 0.25,
              'elevation_droid_damage_boost_100pct': 0.50,
              'rover_speed_boost_50pct': 0.2,
              'sniper_damage_boost_20pct': 0.009,
              'sniper_damage_boost_25pct': 0.01,
              'sniper_damage_boost_50pct': 0.02,
              'tactical_nuke': 1.0,
              'tactical_emp': 2.0,
              'tactical_nuke2': 0.66,
              'tactical_emp2': 0.90,
              'tactical_nuke2_volley': 0.80,
              'tactical_emp2_volley': 1.13,
              'tactical_armor': 0.70,
              'tactical_teargas': 0.60,
              'tactical_bunker': 1.99,
              'tactical_fire': 0.99,
              'gamebucks': 0.01,
              'alloy': 0.01}
    def value_item(name):
        if name.startswith('packaged_'):
            return 0.10
        return VALUES[name]

    total_value = 0.0
    for k in sorted(by_item.keys()):
        qty = by_item[k]
        value = value_item(k)
        print '%-40s %7dx $%4.2f = $%.2f (EV $%.4f)' % (k, qty, value, value*qty, value*qty/float(trials))
        total_value += value*qty
    print 'EV = $%.2f' % (total_value/trials)

    #print get_loot(tables, [{'spec':'alloy','random_stack':[50,55]}], cond_resolver = pred_resolver, verbose = False)
