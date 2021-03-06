#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# automatically generate inverse_requirements.json from buildings.json, tech.json, and crafting.json
# by inverting the "requirements" predicates for various things back to the building/tech upgrades that trigger them.
# this is not intended to be a fully comprehensive predicate parser, just enough to show basic info about building/tech upgrades.

import SpinConfig
import SpinJSON
import AtomicFileWrite
import GameDataUtil
import sys, os, getopt

# if all entries in arr are false, then return None, else return arr
def prune_array(arr):
    if all(not x for x in arr):
        return None
    return arr

# return version of d without items where value is false
def prune_dict(d):
    return dict((k,v) for k,v in d.iteritems() if v)

# given an arbitrary predicate, return a list of basic requirement predicates that involve ONLY building or tech levels
def parse_predicate(gamedata, pred):
    if pred['predicate'] == 'BUILDING_QUANTITY':
        return [{'predicate': 'BUILDING_LEVEL', 'building_type': pred['building_type'], 'trigger_level': 1}]
    elif pred['predicate'] == 'BUILDING_LEVEL':
        return [pred]
    elif pred['predicate'] == 'TECH_LEVEL':
        return [pred]
    elif pred['predicate'] in ('AND','OR'):
        return sum([parse_predicate(gamedata, sub) for sub in pred['subpredicates']], [])
    elif pred['predicate'] == 'LIBRARY':
        return parse_predicate(gamedata, gamedata['predicate_library'][pred['name']])
    elif pred['predicate'] == 'PLAYER_HISTORY':
        # some building levels are referenced via history keys
        if pred['key'].endswith('_level'):
            b = pred['key'][:-len('_level')]
            if b in gamedata['buildings']:
                return [{'predicate': 'BUILDING_LEVEL', 'building_type': b, 'trigger_level': pred['value']}]
        if pred['key'].endswith('_unlocked'): # some kind of ONP-based thing
            return [{'dead_end':1}] # mark this requirement as one that we shouldn't show in the GUI
    return []

# get basic requirement list for one level of a given spec
def do_get_requirements(gamedata, kind, spec, level):
    ret = []

    if 'requires' in spec:
        if type(spec['requires']) is list and len(spec['requires']) < level:
            raise Exception('%s "requires" array is too short, needs to have at least %d entries' % (spec['name'], level))
        ret += parse_predicate(gamedata, GameDataUtil.get_leveled_quantity(spec['requires'], level))

    if kind == 'enhancement':
        if 'min_host_level' in spec:
            applicable_buildings = [name for name in gamedata['buildings'] if spec['enhancement_category'] in gamedata['buildings'][name].get('enhancement_categories', [])]
            if len(applicable_buildings) == 1:
                name = applicable_buildings[0]
                ret += [{'predicate': 'BUILDING_LEVEL', 'building_type': name, 'trigger_level': spec['min_host_level'][level-1]}]

    elif kind == 'tech' and 'associated_unit' in spec:
        # check for factory requirements on units
        unit_spec = gamedata['units'][spec['associated_unit']]
        if 'requires_factory_level' in unit_spec:
            if level == 1: # don't bother notifying about higher levels
                factories = [name for name in gamedata['buildings'] if unit_spec['manufacture_category'] == gamedata['buildings'][name].get('manufacture_category')]
                if len(factories) == 1:
                    name = factories[0]
                    if isinstance(unit_spec['requires_factory_level'], list):
                        req_level = unit_spec['requires_factory_level'][level-1]
                    else:
                        assert isinstance(unit_spec['requires_factory_level'], int)
                        req_level = unit_spec['requires_factory_level']
                    ret += [{'predicate': 'BUILDING_LEVEL', 'building_type': name, 'trigger_level': req_level}]

    return prune_array(ret)

# get basic requirement lists for all levels of a given spec
def get_requirements(gamedata, kind, spec):
    return prune_array([do_get_requirements(gamedata, kind, spec, level) for level in xrange(1,GameDataUtil.get_max_level(spec)+1)])

# get goodies unlocked by one level of a given spec
# this just does a brute-force search through all buildings/techs/crafting recipes for anything that "requires" this level of this spec
def do_invert_requirements(gamedata, requirements, spec, level):
    ret = []
    mykind = GameDataUtil.get_kind(spec)

    for req_kind in requirements:
        for req_specname in requirements[req_kind]:

            # skip any specs for which there is a dead_end in any requirement at any level
            if any(('dead_end' in req) for req_list in requirements[req_kind][req_specname] if req_list for req in req_list): continue

            for req_level in xrange(1,len(requirements[req_kind][req_specname])+1):
                req_list = requirements[req_kind][req_specname][req_level-1]
                if not req_list: continue
                for req in req_list:
                    goodie = None

                    if req['predicate'] == 'BUILDING_LEVEL' and mykind == 'building' and req['building_type'] == spec['name'] and req['trigger_level'] == level:
                        goodie = {req_kind: req_specname, 'level': req_level}
                    elif req['predicate'] == 'TECH_LEVEL' and  mykind == 'tech' and req['tech'] == spec['name'] and req['min_level'] == level:
                        goodie = {req_kind: req_specname, 'level': req_level}

                    if goodie:
                        if goodie['level'] == 1: del goodie['level'] # just to save space - client assumes missing level implies level 1

                        # if this isn't the only requirement for an unlock, list the other predicates that are required too
                        if len(req_list) != 1:
                            goodie['with'] = [r for r in req_list if r is not req]

                        ret.append(goodie)

    return prune_array(ret)

# get goodies unlocked by all levels of a given spec
def invert_requirements(gamedata, requirements, spec):
    return prune_array([do_invert_requirements(gamedata, requirements, spec, level) for level in xrange(1,GameDataUtil.get_max_level(spec)+1)])


if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['game-id=',])

    game_id = None
    for key, val in opts:
        if key == '--game-id' or key == '-g':
            game_id = val
    assert game_id

    # partial build of gamedata
    gamedata = {'predicate_library': SpinConfig.load(args[0], override_game_id = game_id),
                'units': SpinConfig.load(args[1], override_game_id = game_id),
                'buildings': SpinConfig.load(args[2], override_game_id = game_id),
                'tech': SpinConfig.load(args[3], override_game_id = game_id),
                'crafting': SpinConfig.load(args[4], override_game_id = game_id),
                'enhancements': SpinConfig.load(args[5], override_game_id = game_id),
                }

    out_fd = AtomicFileWrite.AtomicFileWrite(args[6], 'w', ident=str(os.getpid()))

    print >>out_fd.fd, "// AUTO-GENERATED BY invert_requirements.py"

    # note pluralization of the keys - this matches what UpgradeBar expects
    requirements = {'building': prune_dict(dict((name, get_requirements(gamedata, 'building', gamedata['buildings'][name])) for name in gamedata['buildings'])),
                    'tech': prune_dict(dict((name, get_requirements(gamedata, 'tech', gamedata['tech'][name])) for name in gamedata['tech'])),
                    'enhancement': prune_dict(dict((name, get_requirements(gamedata, 'enhancement', gamedata['enhancements'][name])) for name in gamedata['enhancements'])),
                    'crafting_recipe': prune_dict(dict((name, get_requirements(gamedata, 'crafting_recipe', gamedata['crafting']['recipes'][name])) for name in gamedata['crafting']['recipes'])),
                    }

    # note pluralization of the keys - this matches what UpgradeBar expects
    out = {'building': prune_dict(dict((name, invert_requirements(gamedata, requirements, gamedata['buildings'][name])) for name in gamedata['buildings'])),
           'tech': prune_dict(dict((name, invert_requirements(gamedata, requirements, gamedata['tech'][name])) for name in gamedata['tech'])),
           #'zzz-requirements': requirements
           }

    count = 0
    print >>out_fd.fd, '{'
    for name, data in sorted(out.iteritems()):
        print >>out_fd.fd, '"%s":' % name, SpinJSON.dumps(data, pretty=True),
        if count != len(out)-1:
            print >>out_fd.fd, ','
        else:
            print >>out_fd.fd
        count += 1
    print >>out_fd.fd, '}'
    out_fd.complete()
