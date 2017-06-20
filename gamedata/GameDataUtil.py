#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# stand-alone library for parsing gamedata, without instantiating server-side objects

def get_leveled_quantity(qty, level):
    if type(qty) is list:
        return qty[level-1]
    return qty

# note: these are the officially-defined parameters that determine the max level of a spec
# it is mandatory that these be level-dependent arrays in the spec, even if the value does not change with level
MAX_LEVEL_FIELD = {'units': 'max_hp', 'buildings': 'build_time', 'tech': 'research_time',
                   'enhancement': 'enhance_time'}

def get_max_level(spec):
    if ('kind' in spec):
        if spec['kind'] == 'mobile':
            kind = 'units'
        elif spec['kind'] == 'building':
            kind = 'buildings'
    elif 'research_time' in spec:
        kind = 'tech'
    elif 'enhance_time' in spec:
        kind = 'enhancement'
    elif 'product' in spec: # crafting recipe
        return spec.get('max_level', 1)
    else:
        raise Exception('cannot determine kind of %r' % spec)
    return len(spec[MAX_LEVEL_FIELD[kind]])

def get_kind(spec):
    if ('kind' in spec):
        return 'unit' if spec['kind'] == 'mobile' else spec['kind']
    elif 'research_time' in spec:
        return 'tech'
    elif 'product' in spec:
        return 'crafting_recipe'
    else:
        raise Exception('cannot determine kind')

# parse a single predicate for minimum CC level requirement
def get_cc_requirement_predicate(gamedata, pred):
    if pred['predicate'] == 'BUILDING_LEVEL':
        if pred['building_type'] == gamedata['townhall']:
            if pred['trigger_level'] > len(gamedata['buildings'][gamedata['townhall']]['build_time']):
                raise Exception('requirement of CC > max level '+repr(pred))
            return pred['trigger_level']
        else:
            if pred['trigger_level'] > len(gamedata['buildings'][pred['building_type']]['requires']):
                raise Exception('requirement of %s > max level: ' % pred['building_type'] + repr(pred))
            return get_cc_requirement_predicate(gamedata, gamedata['buildings'][pred['building_type']]['requires'][pred['trigger_level']-1])
    elif pred['predicate'] == 'TECH_LEVEL':
        return get_cc_requirement_predicate(gamedata, gamedata['tech'][pred['tech']]['requires'][pred['min_level']-1])
    elif pred['predicate'] == 'AND':
        ls = [get_cc_requirement_predicate(gamedata, subpred) for subpred in pred['subpredicates']]
        if -1 in ls: return -1
        return max(ls)
    elif pred['predicate'] == 'ALWAYS_FALSE':
        return -1
    elif pred['predicate'] == 'LIBRARY':
        return get_cc_requirement_predicate(gamedata, gamedata['predicate_library'][pred['name']])
    elif pred['predicate'] == 'BASE_RICHNESS':
        return pred['min_richness']//10 # keep in sync with balance.py
    elif pred['predicate'] in ('ALWAYS_TRUE', 'ANY_ABTEST', 'OR', 'BUILDING_QUANTITY', 'HOME_REGION',
                               'LADDER_PLAYER', 'PLAYER_HISTORY', 'ABSOLUTE_TIME', 'QUEST_COMPLETED', 'AURA_INACTIVE','TRUST_LEVEL'):
        pass
    else:
        raise Exception('unhandled upgrade requirement: %s' % repr(pred))
    return 0

# parse a predicate (list) for a minimum CC level requirement for level "level" of this object
def get_cc_requirement(gamedata, req, level):
    if type(req) is not list: req = [req,]*level
    cc_requirement = 0
    for lev in xrange(1, level+1):
        pred = req[lev-1]
        pred_req = get_cc_requirement_predicate(gamedata, pred)
        if pred_req < 0: return -1
        cc_requirement = max(cc_requirement, pred_req)
    return cc_requirement


# calculate max (sum) of an attribute on a building you can build, indexed by CC level
def calc_max_building_attribute(gamedata, building_name, attribute):
    ret = []

    for cc_level in xrange(1, len(gamedata['buildings'][gamedata['townhall']]['build_time'])+1):
        spec = gamedata['buildings'][building_name]
        num = spec['limit'][cc_level-1] if type(spec['limit']) is list else spec['limit']

        level = 1
        while level < len(spec['build_time']):
            if cc_level < get_cc_requirement(gamedata, spec['requires'], level+1):
                break
            level += 1

        if attribute in spec:
            amount = spec[attribute][level-1] if isinstance(spec[attribute], list) else spec[attribute]
            ret.append(num * amount)
        else:
            ret.append(0)
        #import sys; sys.stderr.write("HERE CC L%d num %d lev %d CC %d total %d\n" % (cc_level, num, level, get_cc_requirement(gamedata, spec['requires'],3), ret[-1]))
    return ret

# calculate max capacity of resource storage, return as array indexed by CC level
def calc_max_storage_for_resource(gamedata, res):
    return calc_max_building_attribute(gamedata, gamedata['resources'][res]['storage_building'], 'storage_'+res)
def calc_max_harvest_rate_for_resource(gamedata, res):
    return calc_max_building_attribute(gamedata, gamedata['resources'][res]['harvester_building'], 'produces_'+res)
