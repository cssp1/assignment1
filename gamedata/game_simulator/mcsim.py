#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Builder gameplay simulator
# Simulates player progression along the building upgrade/tech path by enumerating
# all possible actions at any given time and randomly choosing one.

# Run in gameserver/ directory as:

# PYTHONPATH=. ../gamedata/game_simulator/mcsim.py --to-cc-level=5 --take-breaks -v

import SpinJSON
import SpinConfig
import ResPrice
import Predicates # share code with gameserver!
import sys, getopt, copy, time, random

verbose = 0
gamedata = None # will be loaded below
time_now = int(time.time())

constrain_resources = True # enable resource system
constrain_power = True # enable power system
constrain_foreman = False # XXXXXX foreman accounting

is_payer = False # if true, player is willing to spend gamebucks where possible
free_resources = False # if true, assume player can get unlimited amounts of iron/water for free (via alts or battle)
take_breaks = False # if true, waits above 15m turn into longer breaks
collect_quests = False # if true, player always immediately collects quest rewards XXX buggy since we don't support all predicates

def get_leveled_quantity(qty, level):
    if type(qty) is list:
        return qty[level-1]
    return qty

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

class MockPlayer(object):
    def __init__(self):
        self.my_base = []
        self.history = {}
        self.tech = {}
        self.resources = {}
        self.completed_quests = {}
        self.home_region = None
        self.creation_time = 0
        self.frame_platform = 'fb'

    def clone(self):
        new = MockPlayer()
        new.my_base = self.my_base
        new.history = self.history
        new.tech = self.tech
        new.resources = self.resources
        new.completed_quests = self.completed_quests
        new.home_region = self.home_region
        return new
    def get_absolute_time(self): return time_now
    def get_abtest_predicate(self, name): return gamedata['predicate_library'][name]
    def get_abtest_quest(self, name): return MockQuest(gamedata['quests'][name])
    def get_any_abtest_value(self, key, defvalue): return defvalue
    def home_base_iter(self): return self.my_base
    def get_power_state(self):
        power = [0,0]
        if gamedata.get('enable_power', False):
            for building in self.home_base_iter():
                power[0] += building.get_leveled_quantity(building.spec.provides_power)
                power[1] += building.get_leveled_quantity(building.spec.consumes_power)
        return power
    def get_resource_storage_cap(self):
        cap = dict((res,0) for res in gamedata['resources'])
        for obj in self.home_base_iter():
            for res in gamedata['resources']:
                cap[res] += obj.get_leveled_quantity(getattr(obj.spec, 'storage_'+res))
        return cap
    def get_townhall_level(self):
        assert self.my_base[0].spec.name == gamedata['townhall']
        return self.my_base[0].level

class MockSpec(object):
    DEFAULTS = {'research_credit_cost': -1,
                'research_speedup_cost_factor':1,
                'upgrade_credit_cost':-1,
                'upgrade_speedup_cost_factor':1}
    def __init__(self, json_spec):
        self.json_spec = json_spec
    def __getattr__(self, name):
        return self.json_spec.get(name, self.DEFAULTS.get(name, 0))

class MockQuest(object):
    def __init__(self, json_spec):
        self.json_spec = json_spec
        self.force_claim = True
    def __getattr__(self, name):
        if name not in self.json_spec:
            raise Exception('missing quest field "%s"' % name)
        if name in ('show_if','requires','activation','goal'):
            if name in self.json_spec:
                return Predicates.read_predicate(self.json_spec[name])
            else:
                return None
        return self.json_spec.get(name, 0)

class MockBuilding(object):
    def __init__(self, spec, level):
        self.spec = MockSpec(gamedata['buildings'][spec])
        self.level = level
        self.research_item = None
        self.research_finish_time = -1
        self.upgrade_finish_time = -1
    def clone(self):
        new = MockBuilding(self.spec.name, self.level)
        new.research_item = self.research_item
        new.research_finish_time = self.research_finish_time
        new.upgrade_finish_time = self.upgrade_finish_time
        return new
    def get_leveled_quantity(self, qty): return get_leveled_quantity(qty, self.level)
    def is_under_construction(self): return False
    def is_upgrading(self): return self.upgrade_finish_time > 0
    def is_researching(self): return bool(self.research_item)
    def is_busy(self): return self.is_under_construction() or self.is_upgrading() or self.is_researching()

class State(object):
    def __init__(self):
        self.t = 0
        self.optimal_t = 0
        self.gamebucks_spent = 0
        self.player = MockPlayer()

    def init_starting_conditions(self):
        # gamedata starting conditions
        self.player.tech = copy.copy(gamedata['starting_conditions']['tech'])
        self.player.resources = dict((res, gamedata['starting_conditions'].get(res, 0)) for res in gamedata['resources'])
        self.player.my_base = [MockBuilding(x['spec'], x.get('level',1)) for x in gamedata['starting_conditions']['buildings']]

        # special-case hack for SG, which requires using gamebucks on the CCL1->2 upgrade during the tutorial
        if game_id == 'sg':
            self.player.my_base[0].level = 2

    def serialize(self):
        return {'t': self.t, 'townhall_level': self.player.get_townhall_level() }

    def clone(self):
        new = State()
        new.t = self.t
        new.optimal_t = self.optimal_t
        new.gamebucks_spent = self.gamebucks_spent
        new.player = self.player
        return new

    def get_min_wait(self):
        min_wait = -1
        for obj in self.player.my_base:
            if obj.research_finish_time > 0:
                togo = max(obj.research_finish_time - self.t, 0)
                if min_wait < 0 or togo < min_wait:
                    min_wait = togo
            if obj.upgrade_finish_time > 0:
                togo = max(obj.upgrade_finish_time - self.t, 0)
                if min_wait < 0 or togo < min_wait:
                    min_wait = togo

        if min_wait < 0: # no buildings to wait on - check for harvesting
            cap = self.player.get_resource_storage_cap()
            if any(self.player.resources[res] < cap[res] for res in gamedata['resources']):
                for obj in self.player.home_base_iter():
                    if not obj.is_busy():
                        for res in gamedata['resources']:
                            if getattr(obj.spec, 'produces_'+res, 0):
                                to_harvest = cap[res] - self.player.resources[res]
                                if to_harvest > 0:
                                    rate = obj.get_leveled_quantity(getattr(obj.spec, 'produces_'+res))
                                    togo = max(to_harvest * (3600.0/rate), 1)
                                    if min_wait < 0 or togo < min_wait:
                                        min_wait = togo

        return min_wait

    def spend_resources(self, amounts):
        new = self.clone()
        new.player = new.player.clone()
        new.player.resources = copy.copy(new.player.resources)
        for res, qty in amounts.iteritems():
            assert new.player.resources[res] >= qty
            new.player.resources[res] -= qty
        return new

    def advance_time(self, min_dt, actual_dt):
        # min_dt is the optimal "speedup-able" wait time
        # acutal_dt is how long the player actually waits

        new = self.clone()
        new.t += actual_dt
        new.optimal_t += min_dt
        new.player = new.player.clone()

        # add resources we can harvest in 'time'
        if actual_dt > 0:
            new.player.resources = copy.copy(new.player.resources)
            cap = new.player.get_resource_storage_cap()
            if free_resources:
                new.player.resources = cap
            else:
                for obj in new.player.home_base_iter():
                    if obj.is_busy(): continue
                    for res in gamedata['resources']:
                        if getattr(obj.spec, 'produces_'+res, 0):
                            rate = obj.get_leveled_quantity(getattr(obj.spec, 'produces_'+res))
                            amount = int(rate*(actual_dt/3600.0))
                            new.player.resources[res] = max(cap[res], new.player.resources[res] + amount)

        # update building states
        new_base = []
        for obj in new.player.my_base:
            if obj.research_finish_time > 0 and new.t >= obj.research_finish_time:
                obj = obj.clone()
                techname, obj.research_item, obj.research_finish_time = obj.research_item, None, -1
                new.player.tech = copy.copy(new.player.tech)
                new.player.tech[techname] = new.player.tech.get(techname,0) + 1
            if obj.upgrade_finish_time > 0 and new.t >= obj.upgrade_finish_time:
                obj = obj.clone()
                obj.upgrade_finish_time = -1
                obj.level += 1
            new_base.append(obj)

        new.player.my_base = new_base
        return new

    def upgrade_tech(self, techname, newlevel):
        new = self.clone()
        new.player = new.player.clone()
        new.player.tech = copy.copy(new.player.tech)
        new.player.tech[techname] = newlevel
        return new

    def start_research(self, specname, newlevel, lab_idx, research_time):
        new = self.clone()
        new.player = new.player.clone()
        new.player.my_base = new.player.my_base[:]
        obj = new.player.my_base[lab_idx].clone()
        assert not obj.is_busy()
        obj.research_item = specname
        obj.research_finish_time = self.t + research_time
        new.player.my_base[lab_idx] = obj
        return new

    def add_building(self, specname):
        new = self.clone()
        new.player = new.player.clone()
        new.player.my_base = new.player.my_base[:]
        new.player.my_base.append(MockBuilding(specname, 1))
        return new

    def start_building_upgrade(self, specname, newlevel, idx, upgrade_time):
        new = self.clone()
        new.player = new.player.clone()
        new.player.my_base = new.player.my_base[:]
        obj = new.player.my_base[idx].clone()
        assert obj.spec.name == specname and obj.level == newlevel - 1
        assert not obj.is_busy()
        obj.upgrade_finish_time = self.t + upgrade_time
        new.player.my_base[idx] = obj
        return new

    def upgrade_building(self, specname, newlevel, idx):
        new = self.clone()
        new.player = new.player.clone()
        new.player.my_base = new.player.my_base[:]
        obj = new.player.my_base[idx].clone()
        assert obj.spec.name == specname and obj.level == newlevel - 1
        obj.level = newlevel
        new.player.my_base[idx] = obj
        return new

    def buy_resources(self, amounts):
        new = self.clone()
        new.player = new.player.clone()
        new.player.resources = copy.copy(new.player.resources)
        cap = new.player.get_resource_storage_cap()
        for res, qty in amounts.iteritems():
            new.gamebucks_spent += ResPrice.get_resource_price(gamedata, None, res, qty, 'gamebucks')
            new.player.resources[res] = max(cap[res], new.player.resources[res] + qty)
        return new

    def collect_quests(self):
        new = self.clone()
        new.player = new.player.clone()
        new.player.resources = copy.copy(new.player.resources)
        cap = new.player.get_resource_storage_cap()
        for quest_name, quest in gamedata['quests'].iteritems():
            if quest_name in new.player.completed_quests: continue # already complete

            if any(pred and (not Predicates.read_predicate(pred).is_satisfied(new.player, None)) \
                   for pred in (quest.get('show_if'), quest.get('requires'), quest.get('activation'), quest.get('goal'))):
                continue # predicate failed
            # success!
            print 'QUEST', quest_name
            new.player.completed_quests = copy.copy(new.player.completed_quests)
            new.player.completed_quests[quest_name] = {'count': 1, 'time': self.t}
            for res in gamedata['resources']:
                new.player.resources[res] = min(cap[res], new.player.resources[res] + quest.get('reward_'+res,0))
        return new

class Action(object): pass

class WaitAction(Action):
    def __init__(self, duration):
        self.min_duration = duration

        # if simulating human attention span, turn any 15m+ wait
        # into a random number of hours
        if take_breaks and duration > 15*60:
            self.actual_duration = max(duration, random.randint(0,24)* 3600)
        else:
            self.actual_duration = self.min_duration

    def __repr__(self):
        if take_breaks:
            return 'Wait %s (actual %s)' % (SpinConfig.pretty_print_time(self.min_duration),
                                            SpinConfig.pretty_print_time(self.actual_duration))
        else:
            return 'Wait %s' % SpinConfig.pretty_print_time(self.min_duration)

    def apply(self, state):
        return state.advance_time(self.min_duration, self.actual_duration)

class ConstructBuildingAction(Action):
    def __init__(self, specname):
        self.specname = specname
    def __repr__(self): return 'Construct "%s" L%d' % (self.specname, 1)
    def apply(self, state):
        spec = MockSpec(gamedata['buildings'][self.specname])

        build_time = get_leveled_quantity(spec.build_time, 1)

        cost = dict((res, get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), 1)) for res in gamedata['resources'])
        state = state.spend_resources(cost)

        if is_payer:
            state = state.spend_gamebucks(cost_of_time(get_leveled_quantity(spec.upgrade_speedup_cost_factor, 1) * build_time, 'building_upgrade'))
        else:
            state = state.advance_time(build_time, build_time)

        state = state.add_building(self.specname)
        return state

class UpgradeBuildingAction(Action):
    def __init__(self, specname, newlevel, idx):
        self.specname = specname
        self.newlevel = newlevel
        self.idx = idx
    def __repr__(self): return 'Upgrade "%s" L%d #%d' % (self.specname, self.newlevel, self.idx)
    def apply(self, state):
        spec = MockSpec(gamedata['buildings'][self.specname])

        build_time = get_leveled_quantity(spec.build_time, self.newlevel)
        instant_credit_cost = get_leveled_quantity(spec.upgrade_credit_cost, self.newlevel)

        if is_payer and instant_credit_cost >= 0: # instant purchase
            state = state.spend_gamebucks(gamedata['store']['gamebucks_per_fbcredit'] * instant_credit_cost)
            state = state.upgrade_building(self.specname, self.newlevel, self.idx)

        else:
            cost = dict((res, get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), self.newlevel)) for res in gamedata['resources'])
            state = state.spend_resources(cost)

            if is_payer: # use resources, then speed up
                gamebucks = cost_of_time(get_leveled_quantity(spec.upgrade_speedup_cost_factor, self.newlevel) * build_time, 'building_upgrade')
                state = state.spend_gamebucks(gamebucks)
                state = state.upgrade_building(self.specname, self.newlevel, self.idx)

            else:
                if build_time >= 0:
                    state = state.start_building_upgrade(self.specname, self.newlevel, self.idx, build_time)
                else:
                    state = state.upgrade_building(self.specname, self.newlevel, self.idx)

        return state

class ResearchTechAction(Action):
    def __init__(self, specname, newlevel, lab_idx):
        self.specname = specname
        self.newlevel = newlevel
        self.lab_idx = lab_idx
    def __repr__(self): return 'Research "%s" L%d' % (self.specname, self.newlevel)
    def apply(self, state):
        spec = MockSpec(gamedata['tech'][self.specname])
        assert state.player.tech.get(self.specname,0) == self.newlevel - 1
        assert self.newlevel <= len(spec.research_time)

        research_time = get_leveled_quantity(spec.research_time, self.newlevel)
        instant_credit_cost = get_leveled_quantity(spec.research_credit_cost, self.newlevel)

        if is_payer and instant_credit_cost >= 0: # instant purchase
            state = state.spend_gamebucks(gamedata['store']['gamebucks_per_fbcredit'] * instant_credit_cost)
            state = state.upgrade_tech(self.specname, self.newlevel)

        else:
            cost = dict((res, get_leveled_quantity(getattr(spec, 'cost_'+res, 0), self.newlevel)) for res in gamedata['resources'])
            state = state.spend_resources(cost)

            if is_payer: # use resources, then speed up
                gamebucks = cost_of_time(get_leveled_quantity(spec.research_speedup_cost_factor, self.newlevel) * research_time, 'tech_research')
                state = state.spend_gamebucks(gamebucks)
                state = state.upgrade_tech(self.specname, self.newlevel)

            else:
                state = state.start_research(self.specname, self.newlevel, self.lab_idx, research_time)

        return state

def get_possible_actions(state):
    ret = []
    player = state.player
    current_power = state.player.get_power_state()
    cc_level = state.player.get_townhall_level()
    gen = gamedata['strings']['modstats']['stats']['limit:energy']['check_spec']

    # tech research
    for techname, json_spec in gamedata['tech'].iteritems():
        spec = MockSpec(json_spec)
        if spec.developer_only: continue
        newlevel = player.tech.get(spec.name,0)+1
        if newlevel > len(spec.research_time): continue # already at max level

        pred_ok = True
        if any(pred and (not Predicates.read_predicate(get_leveled_quantity(pred, newlevel)).is_satisfied(player, None)) \
               for pred in (spec.show_if, spec.requires, spec.activation)):
            continue # predicate failed
        if constrain_resources and \
           any(get_leveled_quantity(getattr(spec, 'cost_'+res, 0), newlevel) > player.resources[res] \
               for res in gamedata['resources']):
            continue # resource cost failed

        # find open lab
        lab = None
        lab_idx = -1
        for idx, obj in enumerate(player.home_base_iter()):
            if obj.spec.research_categories and \
               spec.research_category in obj.spec.research_categories and \
               (not obj.is_busy()):
                lab = obj; lab_idx = idx; break
        if not lab: continue # no lab

        ret.append(ResearchTechAction(techname, newlevel, lab_idx))

    # building construction
    for specname, json_spec in gamedata['buildings'].iteritems():
        if specname in ('barrier', 'minefield'): continue # skip these for now
        spec = MockSpec(json_spec)
        if spec.developer_only: continue

        if constrain_power and \
           (not spec.provides_power) and current_power[0] < current_power[1]: continue

        limit = get_leveled_quantity(spec.limit, cc_level)
        if Predicates.read_predicate({'predicate': 'BUILDING_QUANTITY', 'building_type': specname, 'trigger_qty': limit, 'under_construction_ok': 1}).is_satisfied(player, None): continue
        if any(pred and (not Predicates.read_predicate(get_leveled_quantity(pred, 1)).is_satisfied(player, None)) \
               for pred in (spec.show_if, spec.requires, spec.activation)):
            continue # predicate failed
        if (not is_payer) and \
           any(get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), 1) < 0 \
               for res in gamedata['resources']):
            continue # not allowed to Use Resources
        if constrain_resources and \
           any(get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), 1) > player.resources[res] \
               for res in gamedata['resources']):
            continue # resource cost failed
        ret.append(ConstructBuildingAction(specname))

    # building upgrade
    for i, obj in enumerate(player.home_base_iter()):
        if obj.is_busy(): continue
        if obj.spec.name == 'barrier': continue # skip for now
        if obj.level >= len(obj.spec.build_time): continue # maxed level
        newlevel = obj.level + 1
        spec = obj.spec
        if any(pred and (not Predicates.read_predicate(get_leveled_quantity(pred, newlevel)).is_satisfied(player, None)) \
               for pred in (spec.show_if, spec.requires, spec.activation)):
            continue # predicate failed
        if (not is_payer) and \
           any(get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), 1) < 0 \
               for res in gamedata['resources']):
            continue # not allowed to Use Resources
        if constrain_resources and \
           any(get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), newlevel) > player.resources[res] \
               for res in gamedata['resources']):
            continue # resource cost failed
        ret.append(UpgradeBuildingAction(spec.name, newlevel, i))

    if not ret:
        # do nothing (only if no other options are possible)
        min_wait = state.get_min_wait()
        if min_wait >= 0:
            ret.append(WaitAction(min_wait))

    return ret

#            return {'action':'build_new_building','building_type':gen, 'level':1}
#            return {'action':'upgrade_existing_building','building_type':gen,'building_index':get_index_of_lowest(gen,state), 'level':state['base'][get_index_of_lowest(gen,state)]['level']+1}

if __name__ == '__main__':
    game_id = SpinConfig.game()
    to_cc_level = None
    max_iter = 9999999
    heuristic = 'random'
    output_filename = None

    opts, args = getopt.gnu_getopt(sys.argv, 'g:vpf', ['verbose','payer','free-resources','take-breaks',
                                                       'to-cc-level=','heuristic=','output=',
                                                       'max-iter='])
    for key,val in opts:
        if key == '-g': game_id = val
        elif key == '-v' or key == '--verbose': verbose += 1
        elif key == '-p' or key == '--payer': is_payer = True
        elif key == '-f' or key == '--free-resources': free_resources = True
        elif key == '--take-breaks': take_breaks = True
        elif key == '--to-cc-level': to_cc_level = int(val)
        elif key == '--heuristic':
            assert val in ('random', 'first')
            heuristic = val
        elif key == '--output': output_filename = val
        elif key == '--max-iter': max_iter = int(val)

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    state = State()
    state.init_starting_conditions()

    i = 0

    while i < max_iter:

        cc_level = state.player.get_townhall_level()
        if to_cc_level and cc_level >= to_cc_level:
            break

        storage_cap = state.player.get_resource_storage_cap()

        if verbose:
            print '-'*80
            print 'i', i, 't', SpinConfig.pretty_print_time(state.t), ', '.join('%s: %d/%d' % (res, state.player.resources[res], storage_cap[res]) for res in gamedata['resources'])

        actions = get_possible_actions(state)
        if not actions:
            print 'no actions!'
            break

        if verbose >= 2:
            print '\n'.join(map(str,actions))

        if heuristic == 'first':
            action = actions[0]
        elif heuristic == 'random':
            action = actions[random.randint(0, len(actions)-1)]

        if verbose:
            print action

        new_state = action.apply(state)

        if collect_quests:
            new_state = new_state.collect_quests()

        deltaT = new_state.t - state.t

        state = new_state
        i += 1

    if verbose:
        print 'Final tech levels:'
        for techname, level in sorted(state.player.tech.items()):
            print '    %-30s  %d' % (techname, level)
        print 'Final building levels:'
        for obj in sorted(state.player.my_base, key = lambda obj: (obj.spec.name, obj.level)):
            print '    %-30s %d' % (obj.spec.name, obj.level)
        power = state.player.get_power_state()
        print 'Power:', power[1], '/', power[0]

        print 'Gamebucks spent: %d' % state.gamebucks_spent

    print 'Total time: %d sec (= %.1f days, %.1f days optimal) (= %d gamebucks)' % \
          (state.t, (state.t/86400.0), (state.optimal_t/86400.0), cost_of_time(state.optimal_t, 'default'))

    if output_filename:
        with open(output_filename, 'a+') as fd:
            SpinJSON.dump(state.serialize(), fd, newline = True)
