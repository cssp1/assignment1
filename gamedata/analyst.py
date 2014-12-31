#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# THIS SCRIPT IS OBSOLETE, see game_simulator/ for replacement

import SpinJSON
import SpinConfig
import sys, math, copy, getopt

verbose = True
obey_requires = False
gamedata = None

def get_leveled_quantity(qty, level): return qty[level-1] if type(qty) is list else qty

def resource_to_gamebucks(x):
    # compute how many gamebucks a player would be charged to buy x units of iron or water in the in-game Store
    return math.ceil(10 * gamedata['store']['new_boost_formula_scale']* 0.06 * math.exp(0.75 * (math.log10(x) - 2.2*math.pow(math.log10(x),-1.25)))) if x > 2 else 1

def time_to_gamebucks(sec):
    # compute how many gamebucks a player would be charged to speed up an action that takes "sec" seconds
    minutes = sec/60.0
    return int(10*minutes/gamedata['store']['speedup_minutes_per_credit'])+1

def gamebucks_to_time(gamebucks):
    # compute the number of seconds worth of speedup that you could buy for this many gamebucks
    return gamedata['store']['speedup_minutes_per_credit']*(gamebucks/10.0)*60

def upgrade_building(state, b):
    spec = gamedata['buildings'][b['spec']]
    bom = bom_new()
    new_level = b.get('level',1) + 1
    assert new_level <= len(spec['build_time'])

    if obey_requires and ('requires' in spec):
        pred = get_leveled_quantity(spec['requires'], new_level)
        incr_bom, new_state = predicate_to_bom(pred, state)
        bom = bom_add(bom, incr_bom)
        if new_state is not state: # break
            return bom, new_state

    build_time = get_leveled_quantity(spec['build_time'], new_level)
    if build_time > 0:
        bom['time'] = bom.get('time',0) + build_time
    for res in gamedata['resources']:
        if 'build_cost_'+res in spec:
            bom[res] = bom.get(res,0) + get_leveled_quantity(spec['build_cost_'+res], new_level)

    if verbose:
        print '(%s %s to L%d: %s)' % ('build  ' if new_level==1 else 'upgrade', b['spec'], new_level, pretty_print_bom(bom))

    new_state = copy.deepcopy(state)
    new_state['buildings'][state['buildings'].index(b)]['level'] = new_level

    return bom, new_state

def build_building(state, name):
    new_state = copy.deepcopy(state)
    b = {'spec':name, 'level':0}
    new_state['buildings'].append(b)
    return upgrade_building(new_state, b)

def upgrade_tech(state, name):
    spec = gamedata['tech'][name]
    bom = {}
    new_level = state['tech'].get(name,0) + 1
    assert new_level <= len(spec['research_time'])
    bom['time'] = get_leveled_quantity(spec['research_time'], new_level)
    for res in gamedata['resources']:
        if 'cost_'+res in spec:
            bom[res] = get_leveled_quantity(spec['cost_'+res], new_level)

    if verbose:
        print '(research %s to L%d: %s)' % (name, new_level, repr(bom))

    new_state = copy.deepcopy(state)
    new_state['tech'][name] = new_level

    return bom, new_state

def bom_new(): return dict()
def bom_add(a, b):
    r = copy.copy(a)
    for key, val in b.iteritems():
        r[key] = r.get(key,0) + val
    return r

def building_predicate_to_bom(name, want_qty, want_level, state):
    bom = bom_new()
    while True:
        best = None
        num_built = 0
        num_satisfied = 0
        for b in state['buildings']:
            if b['spec'] == name:
                num_built += 1
                if b.get('level',1) >= want_level:
                    num_satisfied += 1
                elif best is None or best.get('level',1) > b.get('level',1):
                    best = b

        if num_satisfied >= want_qty:
            return bom, state # already there
        elif num_built < want_qty:
            # build another at L1
            incr_bom, state = build_building(state, name)
        else:
            assert best
            incr_bom, state = upgrade_building(state, best)

        bom = bom_add(bom, incr_bom)

    raise Exception('impossible predicate %s' % obj)

def predicate_to_bom(obj, state):
    if obj['predicate'] == 'ALWAYS_TRUE':
        return bom_new(), state

    elif obj['predicate'] == 'AND':
        bom = bom_new()
        for sub in obj['subpredicates']:
            incr_bom, state = predicate_to_bom(sub, state)
            bom = bom_add(bom, incr_bom)
        return bom, state

    elif obj['predicate'] == 'BUILDING_LEVEL':
        return building_predicate_to_bom(obj['building_type'], obj.get('trigger_qty',1), obj['trigger_level'], state)
    elif obj['predicate'] == 'BUILDING_QUANTITY':
        return building_predicate_to_bom(obj['building_type'], obj.get('trigger_qty',1), 1, state)

    elif obj['predicate'] == 'TECH_LEVEL':
        bom = bom_new()
        spec = gamedata['tech'][obj['tech']]
        while True:
            if state['tech'].get(obj['tech'],0) >= obj['min_level']:
                return bom, state # already there

            new_level = state['tech'].get(obj['tech'],0)+1

            if obey_requires and ('requires' in spec):
                pred = get_leveled_quantity(spec['requires'], new_level)
                incr_bom, new_state = predicate_to_bom(pred, state)
                bom = bom_add(bom, incr_bom)
                if new_state is not state: # break
                    state = new_state
                    continue

            incr_bom, state = upgrade_tech(state, obj['tech'])
            bom = bom_add(bom, incr_bom)

        raise Exception('impossible predicate %s' % obj)

    else:
        raise Exception('unhandled predicate %s' % obj)

def to_bom(obj, state = None):
    if 'predicate' in obj:
        if state is None:
            state = {'tech':{}, 'buildings':[{'spec':gamedata['townhall']}]}
        bom, new_state = predicate_to_bom(obj, state)
        return bom
    else:
        return obj

def pct(num, denom):
    return ' (%2.0f%%)' % (100.0*num/denom)

def pretty_print_bom(bom):
    total = bom_to_gamebucks(bom)
    p = {}
    for key, val in bom.iteritems():
        if key == 'time':
            p[str(key)] = SpinConfig.pretty_print_time(val) + pct(time_to_gamebucks(val), total)
        elif key in gamedata['resources']:
            p[str(key)] = str(val) + pct(resource_to_gamebucks(val), total)
        else:
            p[str(key)] = val
    return repr(p)

def bom_to_gamebucks(obj):
    total = 0
    for key, val in obj.iteritems():
        if key == 'gamebucks':
            total += val
        elif key in gamedata['resources']:
            if key in ('water','iron'):
                total += resource_to_gamebucks(val)
            else:
                raise Exception('unhandled resource '+key)
        elif key == 'time':
            total += time_to_gamebucks(val)
        else:
            raise Exception('unhandled bom component '+key)
    return total

if __name__ == '__main__':
    game_id = SpinConfig.game()
    thing_to_cost = None

    opts, args = getopt.gnu_getopt(sys.argv, 'g:vqr', ['cost='])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-v': verbose = True
        elif key == '-q': verbose = False
        elif key == '-r': obey_requires = True
        elif key == '--cost': thing_to_cost = SpinJSON.loads(val)

    if not thing_to_cost:
        sys.exit(1)

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    bom = to_bom(thing_to_cost)
    gb = bom_to_gamebucks(bom)
    tm = gamebucks_to_time(gb)
    print 'bom of', thing_to_cost, 'is', pretty_print_bom(bom), '=', gb, 'gamebucks =', SpinConfig.pretty_print_time(tm)
