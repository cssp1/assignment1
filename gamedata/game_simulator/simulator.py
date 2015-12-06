#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.


# Builder gameplay simulator
# note: requires gamedata to be built before running.

import SpinJSON # JSON reading/writing library
import SpinConfig
import ResPrice
import sys, getopt, csv, copy

PAGE_BUGS = False # reproduce bugs in Page's original script to ensure identical output

verbose = False
gamedata = None # will be loaded below

is_payer = False # if true, player is willing to spend gamebucks where possible
free_resources = False # if true, assume player can get unlimited amounts of iron/water for free (via alts or battle)
max_harvesters = True # if true, player maxes out harvester quantity and levels before doing anything else
max_barriers = False # if true, player maxes out barrier quantity and levels before doing anything else
max_core_unit_tech = False # if true, player maxes out researchable core unit techs before doing anything else

def get_leveled_quantity(qty, level):
    if type(qty) is list:
        return qty[level-1]
    return qty

# how many buildings of a given type have been built
def get_building_quantity(s, buildType):
    return len(filter(lambda x: x['spec'] == buildType, s['base']))

# parse a single predicate for minimum CC level requirement
def get_cc_requirement_predicate(pred):
    if pred['predicate'] == 'BUILDING_LEVEL':
        if pred['building_type'] == gamedata['townhall']:
            if pred['trigger_level'] > len(gamedata['buildings'][gamedata['townhall']]['build_time']):
                raise Exception('requirement of CC > max level '+repr(pred))
            return pred['trigger_level']
        else:
            if pred['trigger_level'] > len(gamedata['buildings'][pred['building_type']]['requires']):
                raise Exception('requirement of %s > max level: ' % pred['building_type'] + repr(pred))
            return get_cc_requirement_predicate(gamedata['buildings'][pred['building_type']]['requires'][pred['trigger_level']-1])
    elif pred['predicate'] == 'TECH_LEVEL':
        return get_cc_requirement_predicate(gamedata['tech'][pred['tech']]['requires'][pred['min_level']-1])
    elif pred['predicate'] == 'AND':
        ls = [get_cc_requirement_predicate(subpred) for subpred in pred['subpredicates']]
        if -1 in ls: return -1
        return max(ls)
    elif pred['predicate'] == 'ALWAYS_FALSE':
        return -1
    elif pred['predicate'] == 'LIBRARY':
        return get_cc_requirement_predicate(gamedata['predicate_library'][pred['name']])
    elif pred['predicate'] in ('ALWAYS_TRUE', 'ANY_ABTEST', 'OR', 'BUILDING_QUANTITY', 'HOME_REGION',
                               'LADDER_PLAYER', 'PLAYER_HISTORY', 'ABSOLUTE_TIME', 'QUEST_COMPLETED'):
        pass
    else:
        raise Exception('unhandled upgrade requirement: %s' % repr(pred))
    return 0

# parse a predicate (list) for a minimum CC level requirement for level 'level' of this object
def get_cc_requirement(req, level):
    if type(req) is not list: req = [req,]*level
    cc_requirement = 0
    for lev in xrange(1, level+1):
        pred = req[lev-1]
        pred_req = get_cc_requirement_predicate(pred)
        if pred_req < 0: return -1
        cc_requirement = max(cc_requirement, pred_req)
    return cc_requirement

def get_starting_conditions():
    return {'t': 0,
            'gamebucks_spent': 0,
            'tech': copy.copy(gamedata['starting_conditions']['tech']),
            'resources_in_storage': dict((res, gamedata['starting_conditions'].get(res, 0)) for res in gamedata['resources']),
            'base': [{'spec': x['spec'], 'level':x.get('level',1)} for x in gamedata['starting_conditions']['buildings']]}

def advance_time(wt,state): # where wt stands for wait time and st stands for state
    state['t']+=wt
    rpt = get_amount_resources_produced_in_given_time(wt,state) #should happen at same time
    gain_resources(state, rpt)

def get_power_state(base):
    power = [0,0]
    if gamedata.get('enable_power', False):
        for building in base:
            spec = gamedata['buildings'][building['spec']]
            if 'provides_power' in spec:
                power[0] += get_leveled_quantity(spec['provides_power'], building['level'])
            if 'consumes_power' in spec:
                power[1] += get_leveled_quantity(spec['consumes_power'], building['level'])
    return power

###################################################
## Functions that deal with harvesting resources ##
###################################################

def get_cost_of_action(actionDict):
    costDict = dict((res, 0) for res in gamedata['resources'])

    if actionDict['action']=='upgrade_existing_building' or actionDict['action']=='build_new_building':
        if actionDict['action']=='build_new_building':
            level = 1
        else:
            level = actionDict['level']
        spec = gamedata['buildings'][actionDict['building_type']]
        for res in gamedata['resources']:
             costDict[res] += get_leveled_quantity(spec.get('build_cost_'+res,0), level)
    elif actionDict['action'] == 'research_tech':
        spec = gamedata['tech'][actionDict['specname']]
        for res in gamedata['resources']:
            costDict[res] += get_leveled_quantity(spec.get('cost_'+res,0), actionDict['level'])
    elif actionDict['action'] in ('wait', 'buy_resources'):
            pass
    else:
        raise Exception('unhandled action: '+actionDict['action'])
    return costDict


def harvest_enough_resources_for_action(actionDict, state):
    if is_payer and actionDict['action'] == 'upgrade_existing_building' and \
       get_leveled_quantity(gamedata['buildings'][actionDict['building_type']].get('upgrade_credit_cost',-1), actionDict['level']) >= 0:
        return actionDict # instant option available, don't need to harvest

    gca = get_cost_of_action(actionDict)

    # do we have enough resources right now?
    if all(state['resources_in_storage'][res] >= gca[res] for res in gca):
        return actionDict # just do the next action

    storage_avail = get_tot_storage_available(state)

    need_res = None
    need_amount = -1
    for res in gca:
        if storage_avail[res] < gca[res]:
            # don't have enough space to store it - add storage (starting with the most needy resource)
            if gca[res] - storage_avail[res] > need_amount:
                need_res = res
                need_amount = gca[res] - storage_avail[res]
    if need_res:
        return get_next_action(state, {'action':'increase_storage','type':need_res})

    if free_resources:
        return {'action': 'get_resources_for_free', 'amounts': dict((res, max(gca[res] - state['resources_in_storage'][res], 0)) for res in gca)}

    if is_payer:
        return {'action': 'buy_resources', 'amounts': dict((res, max(gca[res] - state['resources_in_storage'][res], 0)) for res in gca)}

    # wait for harvesters
    wait_time = 0
    for res in gca:
        needed = max(gca[res] - state['resources_in_storage'][res], 0)
        if needed > 0:
            wait_time = max(wait_time, get_time_to_produce_resource(state, needed, res))
    assert wait_time > 0
    return {'action':'wait', 'amt_time':wait_time}

def get_tot_storage_available(state):
    total = dict((res,0) for res in gamedata['resources'])
    for building in state['base']:
        spec = gamedata['buildings'][building['spec']]
        if PAGE_BUGS and (building['spec'] == gamedata['townhall']): continue # ignores townhall
        for res in gamedata['resources']:
            if 'storage_'+res in spec:
                total[res] += get_leveled_quantity(spec['storage_'+res], building['level'])
    return total

def get_list_of_buildings_of_type(buildType,state):
        ls = []
        count = 0
        for building in state['base']:
                if building['spec']==buildType:
                        building['index']= count # XXXXXX WHOA
                        ls.append(building)
                count +=1
        return ls

def get_overall_rate_for_harvesters_of_type(state,harvestType):
    rate = 0
    harvest_building = gamedata['resources'][harvestType]['harvester_building']
    attribute = 'produces_'+harvestType
    for building in get_list_of_buildings_of_type(harvest_building,state):
        rate += get_leveled_quantity(gamedata['buildings'][harvest_building][attribute], building['level'])
    return rate


# where rate is items per hour
def get_produced_per_time(rate, time):
        return int((rate/3600.0)*time)

def get_time_to_produce_resource(state, amount, res):
    denom = 0
    for building in state['base']:
        spec = gamedata['buildings'][building['spec']]
        if 'produces_'+res in spec:
            denom += get_leveled_quantity(spec['produces_'+res], building['level'])
    return int(amount*3600.0/denom+0.5)

# return amount we can harvest in 'time' (assuming continuous collection), capping once storages are full
def get_amount_resources_produced_in_given_time(time, state):
    time += 0.5 # shouldn't be necessary
    harvestable = dict((res, get_produced_per_time(get_overall_rate_for_harvesters_of_type(state,res), time)) for res in gamedata['resources'])
    storage_room = dict((res, get_tot_storage_available(state)[res] - state['resources_in_storage'][res]) for res in gamedata['resources'])
    if PAGE_BUGS: # doesn't compute on a per-resource basis
        if any(harvestable[res] > storage_room[res] for res in gamedata['resources']):
            return storage_room
        else:
            return harvestable
    return dict((res, min(harvestable[res], storage_room[res])) for res in gamedata['resources'])

def gain_resources(state, amounts):
    for res, qty in amounts.iteritems():
        state['resources_in_storage'][res] += qty

def spend_resources(state, amounts):
    for res, qty in amounts.iteritems():
        assert qty <= state['resources_in_storage'][res]
        state['resources_in_storage'][res] -= qty
def spend_gamebucks(state, amount):
    state['gamebucks_spent'] += amount

#############################################################
## Functions that deal with Predicates and Building Levels ##
#############################################################

def goal_is_satisfied(state,goal):
    return check_status_of_action(goal, state)

def get_index_of_lowest(buildType,state):
    lowest_level = get_lowest_level(buildType,state)
    for buildingI in range(len(state['base'])):
        if (state['base'][buildingI]['spec']==buildType) and (state['base'][buildingI]['level']==lowest_level):
            return buildingI
    return -1

# Takes a building type and a state and returns the lowest building level of that type
def get_lowest_level(buildType,state):
    levelList = []
    for building in state['base']:
        if building['spec']==buildType:
            levelList.append(building['level'])
    levelList.sort()
    if len(levelList)>0:
        return levelList[0]
    return 0

def building_is_at_max_level(building):
    return building['level']==len(gamedata['buildings'][building['spec']]['build_time'])
def max_are_built_for_current_townhall(state,buildType):
    thl = state['base'][0]['level'] # where thl stands for townhall level XXXXXX
    return (len(get_list_of_buildings_of_type(buildType,state)) >= get_leveled_quantity(gamedata['buildings'][buildType]['limit'], thl))

def try_to_max_buildings(state, spec_test, try_hard = False): # XXXXXX
    candidate_specs = filter(spec_test, gamedata['buildings'].itervalues())
    candidate_actions = []

    for spec in candidate_specs:
        if not max_are_built_for_current_townhall(state, spec['name']):
            candidate_actions.append({'action':'build_new_building','building_type':spec['name'],'level':1})

    for building in state['base']:
        if gamedata['buildings'][building['spec']] in candidate_specs:
            if not building_is_at_max_level(building):
                candidate_actions.append({'action':'upgrade_existing_building','building_type':building['spec'],'building_index':building['index'],'level':building['level']+1})

    if not candidate_actions:
        return None

    # pick action with lowest total resource cost
    candidate_actions.sort(key = lambda a: sum(get_cost_of_action(a).itervalues(),0))
    action = candidate_actions[0]
    spec = gamedata['buildings'][action['building_type']]
    ls = get_leveled_quantity(spec['requires'], action['level'])
    ip = interpret_predicate(ls, state)
    if ip.get('condition','false')!='all_predicates_true': # XXXXXX needs to recurse
        if try_hard and ip.get('action') == 'check_subpredicates':
            for sp in ls['subpredicates']:
                isp = interpret_predicate(sp, state)
                if isp.get('condition') != 'all_predicates_true':
                    return None
            return action
        return None
    storage_avail = get_tot_storage_available(state)
    # not enough storage to hold the resources to do this (XXX convert to increase_storage?)
    for res in gamedata['resources']:
        if get_leveled_quantity(spec.get('build_cost_'+res,0), action['level']) > storage_avail.get(res,0):
            if try_hard:
                return get_next_action(state, {'action': 'increase_storage', 'type': res}, allow_try_hard = False)
            return None
    return action

def try_to_max_tech(state, spec_test):
    candidate_specs = filter(spec_test, gamedata['tech'].itervalues())
    candidate_actions = []

    for spec in candidate_specs:
        if state['tech'].get(spec['name'],0) < len(spec['research_time']):
            candidate_actions.append({'action':'research_tech','specname':spec['name'],'level':state['tech'].get(spec['name'],0)+1})
    if not candidate_actions:
        return None

    # pick action with lowest total resource cost
    candidate_actions.sort(key = lambda a: sum(get_cost_of_action(a).itervalues(),0))
    action = candidate_actions[0]

    spec = gamedata['tech'][action['specname']]
    ls = get_leveled_quantity(spec['requires'], action['level'])
    ip = interpret_predicate(ls, state)
    if ip.get('condition','false')!='all_predicates_true': # XXXXXX needs to recurse
        if True and ip.get('action') == 'check_subpredicates':
            for sp in ls['subpredicates']:
                isp = interpret_predicate(sp, state)
                if isp.get('condition') != 'all_predicates_true':
                    return None
            return action
        return None
    storage_avail = get_tot_storage_available(state)
    if not all(get_leveled_quantity(spec.get('cost_'+res,0), action['level']) <= storage_avail.get(res,0) for res in gamedata['resources']):
        # not enough storage to hold the resources to do this (XXX convert to increase_storage?)
        return None
    return action

# This function takes a predicate and returns a dictionary describing its status (XXXXXX ?)
def interpret_predicate(pred,state):
    if pred['predicate']=='BUILDING_QUANTITY':
        pred = {'predicate': 'BUILDING_LEVEL', 'trigger_level': 1, 'building_type':pred['building_type'],'trigger_qty': pred.get('trigger_qty',1) }
    if pred['predicate'] == 'BUILDING_LEVEL':
            count = 0
            for building in state['base']:
                        if (pred['building_type'] == building['spec']) and (building['level']< pred['trigger_level']):
                                return {'action' : 'upgrade_existing_building','building_type' : pred['building_type'], 'level': pred['trigger_level'], 'building_index':count}
                        elif get_building_quantity(state, pred['building_type'])<pred.get('trigger_qty',1):
                                        return {'action' : 'build_new_building', 'building_type' : pred['building_type'], 'qty' : pred.get('trigger_qty',1), 'level':1}
                        count+=1
            return {'condition': 'all_predicates_true'}
    elif pred['predicate'] == 'TECH_LEVEL':
        if state['tech'].get(pred['tech'],0) >= pred['min_level']:
            return {'condition': 'all_predicates_true'}
        return {'action': 'research_tech', 'specname': pred['tech'], 'level': pred['min_level']}
    elif pred['predicate'] == 'AND':
                return {'action':'check_subpredicates'} # XXXXXX
    elif pred['predicate'] in ('ALWAYS_TRUE', 'ANY_ABTEST', 'OR', 'BUILDING_QUANTITY', 'HOME_REGION', 'LADDER_PLAYER', 'PLAYER_HISTORY','QUEST_COMPLETED'):
        return {'condition': 'all_predicates_true'}
    else:
        raise Exception('unhandled upgrade requirement: %s' % repr(pred))
    print 'got here'

def research_tech(specname, new_level, state):
    assert state['tech'].get(specname,0) == new_level - 1
    spec = gamedata['tech'][specname]
    research_time = get_leveled_quantity(spec['research_time'], new_level)
    instant_credit_cost = get_leveled_quantity(spec.get('research_credit_cost',-1), new_level)
    if is_payer and instant_credit_cost >= 0: # instant purchase
        spend_gamebucks(state, gamedata['store']['gamebucks_per_fbcredit'] * instant_credit_cost)
    else:
        gca = get_cost_of_action({'action':'research_tech', 'specname':specname, 'level':new_level})
        spend_resources(state,gca)
        if is_payer: # use resources, then speed up
            gamebucks = cost_of_time(get_leveled_quantity(spec.get('research_speedup_cost_factor',1), 1) * research_time, 'tech_research')
            spend_gamebucks(state, gamebucks)
        else:
            advance_time(research_time, state)
    state['tech'][specname] = new_level

# Should take a state and an index and return the state
def upgradeBuildingLevel(buildingI,state):
    specname = state['base'][buildingI]['spec']
    spec = gamedata['buildings'][specname]
    new_level = state['base'][buildingI]['level']+1
    build_time = get_leveled_quantity(spec['build_time'], new_level-1 if PAGE_BUGS else new_level) # indexed wrong here
    instant_credit_cost = get_leveled_quantity(spec.get('upgrade_credit_cost',-1), new_level)
    if is_payer and instant_credit_cost >= 0: # instant purchase
        spend_gamebucks(state, gamedata['store']['gamebucks_per_fbcredit'] * instant_credit_cost)
    else:
        gca = get_cost_of_action({'action':'upgrade_existing_building','building_type':specname,'building_index':buildingI,'level':new_level})
        spend_resources(state,gca)
        if is_payer: # use resources, then speed up
            gamebucks = cost_of_time(get_leveled_quantity(spec.get('upgrade_speedup_cost_factor',1), 1) * build_time, 'building_upgrade')
            spend_gamebucks(state, gamebucks)
        else:
            advance_time(build_time, state)
    state['base'][buildingI]['level']+=1
    if verbose: print 'Upgrading building of type', state['base'][buildingI]['spec'], 'at t=',state['t'], 'to level', state['base'][buildingI]['level']

# Takes a building spec and a state and return a new state
def make_new_building(specname, state):
    spec = gamedata['buildings'][specname]
    gca = get_cost_of_action({'action':'build_new_building','building_type':specname})
    spend_resources(state,gca)
    state['base'].append({'spec':specname, 'level':1})
    build_time = get_leveled_quantity(spec['build_time'], 1)
    if is_payer:
        gamebucks = cost_of_time(get_leveled_quantity(spec.get('upgrade_speedup_cost_factor',1), 1) * build_time, 'building_upgrade')
        spend_gamebucks(state, gamebucks)
    else: # let time pass until construction finishes
        # XXX assumes nothing else going on
        advance_time(build_time,state)
    return state

def buy_resources(amounts, state):
    for res, qty in amounts.iteritems():
        state['gamebucks_spent'] += ResPrice.get_resource_price(gamedata, None, res, qty, 'gamebucks')
    gain_resources(state, amounts)

def get_resources_for_free(amounts, state):
    gain_resources(state, amounts)

def cost_of_time(sec, kind):
    if sec <= 0: return 0

    minutes = sec/60.0

    if type(gamedata['store']['speedup_minutes_per_credit']) is dict:
        minutes_per_credit = gamedata['store']['speedup_minutes_per_credit'][kind]
    else:
        minutes_per_credit = gamedata['store']['speedup_minutes_per_credit']

    # compute how many gamebucks a player would be charged to speed up an action that takes 'sec' seconds
    return int(gamedata['store']['gamebucks_per_fbcredit']*minutes/minutes_per_credit)+1

def time_of_cost(gamebucks):
    # compute the number of seconds worth of speedup that you could buy for this many gamebucks
    return gamedata['store']['speedup_minutes_per_credit']*(gamebucks/gamedata['store']['gamebucks_per_fbcredit'])*60

# Accepts an action & a state & returns a boolean telling if the action has been completed
def check_status_of_action(actionDict, state): ##Should return true if completed
    if actionDict['action']=='build_new_building':
        return actionDict.get('qty',1)>get_building_quantity(state, actionDict['building_type'])
    elif actionDict['action']== 'upgrade_existing_building':
        return state['base'][actionDict['building_index']]['level']>=actionDict['level']
    elif actionDict['action']== 'all_predicates_true':
        return True

# accepts an action and a state.  Will return a new state without changing the old one
def do_next_action(actionDict, state):
    if actionDict['action'] == 'build_new_building':
        make_new_building(actionDict['building_type'],state)
    elif actionDict['action'] == 'upgrade_existing_building':
        upgradeBuildingLevel(actionDict['building_index'],state)
    elif actionDict['action'] == 'research_tech':
        research_tech(actionDict['specname'], actionDict['level'], state)
    elif actionDict['action'] == 'buy_resources':
        buy_resources(actionDict['amounts'],state)
    elif actionDict['action'] == 'get_resources_for_free':
        get_resources_for_free(actionDict['amounts'],state)
    elif actionDict['action'] == 'wait':
        advance_time(actionDict['amt_time'],state)
    else:
        raise Exception('unknown action type '+actionDict['action'])
    return state

def is_blueprint_predicate(pred):
    if pred['predicate'] == 'PLAYER_HISTORY' and ('_blueprint_unlocked' in pred['key']):
        return True
    elif pred['predicate'] == 'LIBRARY':
        return is_blueprint_predicate(gamedata['predicate_library'][pred['name']])
    elif 'subpredicates' in pred:
        return any(is_blueprint_predicate(sub) for sub in pred['subpredicates'])
    return False

def is_core_unit_tech(spec):
    if not ('associated_unit' in spec):
        return False
    if is_blueprint_predicate(get_leveled_quantity(spec['requires'], 1)):
        return False
    return True

# given a state, return the next action that would advance the state towards the goal
# does not modify state. But may append additional unfulfilled requirements to 'requirements'.
def get_next_action(state, requirement, allow_try_hard = True):
    # print 'action', requirement
    current_power = get_power_state(state['base'])
    gen = gamedata['strings']['modstats']['stats']['limit:energy']['check_spec']

    if max_harvesters:
        temp = try_to_max_buildings(state, lambda spec: any(('produces_'+res in spec) for res in gamedata['resources']))
        if temp:
            return temp

    if max_barriers:
        temp = try_to_max_buildings(state, lambda spec: spec['name'] == 'barrier')
        if temp:
            return temp

    if max_core_unit_tech:
        # first max out buildings that produce core units or research core unit tech
        # XXXXXX this isn't really accurate, really we need to recurse into the requirements predicates
        temp = try_to_max_buildings(state,
                                    lambda spec:
                                    any(cat in gamedata['strings']['manufacture_categories'] for cat in spec.get('research_categories',[])) or \
                                    any(cat in gamedata['strings']['manufacture_categories'] for cat in spec.get('manufacture_categories',[spec.get('manufacture_category',None)])),
                                    try_hard = allow_try_hard)
        if temp:
            return temp
        temp = try_to_max_tech(state, lambda spec: is_core_unit_tech(spec))
        if temp:
            return temp

    if requirement['action']== 'fix_power':
        if (get_building_quantity(state, gen)< gamedata['buildings'][gen]['limit'][state['base'][0]['level']-1]):
            return {'action':'build_new_building','building_type':gen, 'level':1}
        else:
            return {'action':'upgrade_existing_building','building_type':gen,'building_index':get_index_of_lowest(gen,state), 'level':state['base'][get_index_of_lowest(gen,state)]['level']+1}

    elif requirement['action'] == 'increase_storage':
        storage_type = gamedata['resources'][requirement['type']]['storage_building'] # storage_type gives building name
        if (get_building_quantity(state, storage_type)< gamedata['buildings'][storage_type]['limit'][state['base'][0]['level']-1]): # XXX
            return {'action':'build_new_building','building_type':storage_type, 'level':1}
        else:
            return {'action':'upgrade_existing_building','building_type':storage_type,'building_index':get_index_of_lowest(storage_type,state), 'level':state['base'][get_index_of_lowest(storage_type,state)]['level']+1}

    elif requirement['action']== 'build_new_building':
        requiresList = gamedata['buildings'][requirement['building_type']]['requires']
        ip = interpret_predicate(requiresList[0],state)
        if (requirement['building_type']==gen):
            pow_to_build = 0
        else:
            pow_to_build = get_leveled_quantity(gamedata['buildings'][requirement['building_type']].get('consumes_power',0),1)
        if ip.get('condition','not_true')=='all_predicates_true':
            if (not gamedata['enable_power']) or (((1.0*current_power[1]+pow_to_build)/current_power[0])<=1):
                requirement['level']=1
                return requirement ### breaking the recursion in build_new_building_part
            else: # need more power before build
                return get_next_action(state, {'action':'fix_power'})
        if ip['action'] == 'check_subpredicates':
            for sp in requiresList[0]['subpredicates']:
                isp =interpret_predicate(sp,state)
                if isp.get('condition', 'not_true')!='all_predicates_true': # if condition isn't all true, get next action
                    return get_next_action(state, isp)
                if (not gamedata['enable_power']) or (((1.0*current_power[1]+pow_to_build)/current_power[0])<=1):
                    requirement['level']=1
                    return requirement ### breaking the recursion in build_new_building_part
                else: # need more power before build
                    return get_next_action(state, {'action':'fix_power'})
        else:
            return get_next_action(state,ip) # get next action of interpreted predicate

    elif requirement['action'] == 'upgrade_existing_building':
        requiresList = gamedata['buildings'][requirement['building_type']]['requires']
        index = state['base'][requirement['building_index']]['level']## current level should be index of next level up
        ls = requiresList[index]
        ip = interpret_predicate(requiresList[index],state)
        # print 'ip',ip
        if ip.get('condition','not_true')=='all_predicates_true':
            new_requirement = requirement.copy()
            new_requirement['level']=state['base'][new_requirement['building_index']]['level']+1
            return new_requirement ### breaking the recursion in build_new_building_part
        if ip.get('action','all_predicates_true') == 'check_subpredicates':
            for sp in ls['subpredicates']:
                isp =interpret_predicate(sp,state)
                if verbose: print 'isp',isp
                if isp.get('condition','not_true')!='all_predicates_true': # if condition isn't all true, get next action
                    return get_next_action(state, isp)

            new_requirement = requirement.copy()
            new_requirement['level']=state['base'][new_requirement['building_index']]['level']+1
            return new_requirement ### breaking the recursion in build_new_building_part
        else:
            # print 'in upgrade else'
            return get_next_action(state,ip) # get next action of interpretted predicate
    else:
        raise Exception('unhandled action: %r' % requirement)

if __name__ == '__main__':
    game_id = SpinConfig.game()
    output = 'json'
    goal = None
    to_cc_level = None
    opts, args = getopt.gnu_getopt(sys.argv, 'g:vpf', ['verbose','output=','pred=','payer','free-resources',
                                                      'to-cc-level=','no-max-harvesters','max-barriers',
                                                       'max-core-unit-tech'])
    for key,val in opts:
        # print key
        if key == '-g':
            game_id = val
        elif key == '-v' or key == '--verbose':
            verbose = True
        elif key == '--output':
            assert val in ('json','csv')
            output = val
        elif key == '--pred':
            goal = SpinJSON.loads(val)
        elif key == '-p' or key == '--payer':
            is_payer = True
        elif key == '-f' or key == '--free-resources':
            free_resources = True
        elif key == '--to-cc-level':
            to_cc_level = int(val)
        elif key == '--no-max-harvesters':
            max_harvesters = False
        elif key == '--max-barriers':
            max_barriers = True
        elif key == '--max-core-unit-tech':
            max_core_unit_tech = True

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    if goal is None:
        goal = {'action':'upgrade_existing_building',
                'building_type':gamedata['townhall'],
                'level': to_cc_level or len(gamedata['buildings'][gamedata['townhall']]['build_time']),
                'building_index':0} # XXXXXX

    state = get_starting_conditions()

    i = 0
    tOld = 0
    time_spent_harvesting = 0
    other_time = 0

    # initialize CSV writer object
    if output == 'csv':
        res_keys = sorted(gamedata['resources'].keys())
        CSV_FIELDS = ['time','building_type','action_type','level','time_change'] + [res+'_cost' for res in res_keys] + ['stored_'+res for res in res_keys] + ['gamebucks_spent']
        writer = csv.DictWriter(sys.stdout, CSV_FIELDS, dialect='excel')
        writer.writerow(dict((fn,fn) for fn in CSV_FIELDS)) # write the header row

    while (not goal_is_satisfied(state,goal)):
        if verbose:
            print '-'*80
            print 'i', i, 't', state['t'], 'state', state

        next_action = goal

        while True:
            next_action = get_next_action(state, next_action)
            if verbose: print 'get_next_action', next_action, 'cost', get_cost_of_action(next_action)

            temp = harvest_enough_resources_for_action(next_action,state)
            if verbose: print 'harvest_enough action', temp, 'cost', get_cost_of_action(temp), 'res', state['resources_in_storage']

            if temp is next_action or temp['action'] in ('wait','buy_resources','get_resources_for_free'):
                next_action = temp
                break
            next_action = temp



        tOld = state['t']
        old_state = state
        new_state = do_next_action(next_action,state)
        deltaT = state['t'] - tOld
        res_cost = get_cost_of_action(next_action)

        if next_action.get('action',1)=='wait':
            time_spent_harvesting+= deltaT
        else:
            other_time+=deltaT

        if output == 'json':
            print SpinJSON.dumps({'time': tOld,'time_change':deltaT,'action':next_action})

        elif output == 'csv':
            csv_row = {'time': tOld,'time_change':deltaT,
                       'action_type':next_action['action'],
                       'building_type':next_action.get('building_type'),
                       'level':next_action.get('level'),
                       'gamebucks_spent': old_state['gamebucks_spent']}
            csv_row.update(dict((res+'_cost', res_cost[res]) for res in res_keys))
            csv_row.update(dict(('stored_'+res, old_state['resources_in_storage'][res]) for res in res_keys))
            writer.writerow(csv_row)
        state=new_state
        i+=1

    print 'Final tech levels:'
    for techname, level in sorted(state['tech'].items()):
        print '    %-30s  %d' % (techname, level)
    print 'Time spent waiting for harvesting:',time_spent_harvesting
    print 'Other time:',other_time
    print 'Total time: %d sec (= %.1f days) (= %d gamebucks)' % (state['t'], (state['t']/86400.0), cost_of_time(state['t'], 'default'))
    print 'Gamebucks spent: %d' % state['gamebucks_spent']

    if verbose:
        print 'Power in base:', get_power_state(state['base'])
        print 'final state:', state
        print 'cost in gamebucks:', cost_of_time(state['t'], 'default')
        print '-'*180
