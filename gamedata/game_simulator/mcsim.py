#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Builder gameplay simulator
# Simulates player progression along the building upgrade/tech path by enumerating
# all possible actions at any given time and randomly choosing one.

# Run in gameserver/ directory as:

# PYTHONPATH=. ../gamedata/game_simulator/mcsim.py --to-cc-level 5 --heuristic=discounted-coolness -v -g tr --take-breaks -f

import SpinJSON
import SpinConfig
import ResPrice
import Predicates # share code with gameserver!
import sys, getopt, copy, time, random, math

verbose = 0
gamedata = None # will be loaded below
time_now = int(time.time())

constrain_resources = True # enable resource system
constrain_power = True # enable power system
constrain_foremen = True # foreman accounting
constrain_harvester_capacity = True

is_payer = False # if true, player is willing to spend gamebucks where possible
free_resources = False # if true, assume player can get unlimited amounts of iron/water for free (via alts or battle)
take_breaks = False # if true, waits above 15m turn into longer breaks
collect_quests = False # if true, player always immediately collects quest rewards XXX buggy since we don't support all predicates
min_foremen = 1 # minimum number of foremen available - useful for "what if" scenarios with multiple builders
discount_tau = 0.25 # coolness decays by tau/e per hour

COOLNESS = {
    # CONSTANT
    'fix_low_power': 10000000.0,
    'harvester_new': 1000.0,
    'factory_new': 1000.0,
    'lab_new': 1000.0,
    'generator': 0.001,

    # VARIABLE
    'townhall': 20.0,
    'tech_unlock': 1000.0,

    'harvester': 4.0,
    'storage': 10.0, 'storage_res3': 1.0,
    'lab': 2.0, 'factory': 2.0,
    'tech_upgrade': 0.5,

    'turret': 0.5, 'turret_new': 1.1,
    'warehouse': 0.1,

    'default': 1.0,
    }

def pretty_print_priority(p): return 'P%.9g' % p

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
    def foreman_is_free(self):
        total = 0
        in_use = 0
        for obj in self.home_base_iter():
            if obj.spec.provides_foremen:
                total += obj.get_leveled_quantity(obj.spec.provides_foremen)
            if obj.is_under_construction() or obj.is_upgrading():
                in_use += 1
        total = max(total, min_foremen)
        return in_use < total

class MockSpec(object):
    DEFAULTS = {'research_credit_cost': -1,
                'research_speedup_cost_factor':1,
                'upgrade_credit_cost':-1,
                'upgrade_speedup_cost_factor':1}
    def __init__(self, json_spec):
        self.json_spec = json_spec
    def __getattr__(self, name):
        return self.json_spec.get(name, self.DEFAULTS.get(name, 0))

    def get_building_coolness(self, level):
        if self.name == gamedata['townhall']:
            return COOLNESS['townhall']
        elif any(getattr(self, 'produces_'+res, 0) for res in gamedata['resources']):
            for res in gamedata['resources']:
                if getattr(self, 'produces_'+res, 0):
                    return COOLNESS['harvester_new'] if level == 1 else COOLNESS['harvester']

        elif any(getattr(self, 'storage_'+res, 0) for res in gamedata['resources']):
            for res in gamedata['resources']:
                if getattr(self, 'storage_'+res, 0):
                    return COOLNESS.get('storage_'+res, COOLNESS['storage'])

        elif self.research_categories:
            return COOLNESS['lab_new'] if level == 1 else COOLNESS['lab']
        elif self.manufacture_category:
            return COOLNESS['factory_new'] if level == 1 else COOLNESS['factory']
        elif self.spells and self.spells[0].endswith('SHOOT'):
            return COOLNESS['turret_new'] if level == 1 else COOLNESS['turret']
        elif self.provides_power:
            return COOLNESS['generator']
        elif self.provides_inventory:
            return COOLNESS['warehouse']
        else:
            return COOLNESS.get('default', 1.0)

    def get_tech_coolness(self, level):
        if level == 1:
            return COOLNESS['tech_unlock'] # higher priority for first unlock of something
        else:
            return COOLNESS['tech_upgrade']

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

        # special-case hack for tutorial rewards
        elif game_id in ('tr','dv'):
            self.player.resources['iron'] = 51000
            self.player.resources['water'] = 51000

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
        wait_reason = None

        for obj in self.player.my_base:
            if obj.research_finish_time > 0:
                togo = max(obj.research_finish_time - self.t, 0)
                if min_wait < 0 or togo < min_wait:
                    min_wait = togo
                    wait_reason = 'Research "%s" L%d' % (obj.research_item, self.player.tech.get(obj.research_item,0)+1)
            if obj.upgrade_finish_time > 0:
                togo = max(obj.upgrade_finish_time - self.t, 0)
                if min_wait < 0 or togo < min_wait:
                    min_wait = togo
                    wait_reason = 'Upgrade "%s" L%d' % (obj.spec.name, obj.level+1)

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

                                    # cap this at ~2 hours though
                                    togo = min(togo, 7200)

                                    if min_wait < 0 or togo < min_wait:
                                        min_wait = togo
                                        wait_reason = 'Harvest resources'

        return min_wait, wait_reason

    def get_time_to_reach_resources(self, target):
        rates = dict((res,0) for res in gamedata['resources'])

        max_wait = -1

        for obj in self.player.home_base_iter():
            if not obj.is_busy():
                for res in gamedata['resources']:
                    if getattr(obj.spec, 'produces_'+res, 0):
                        my_rate = obj.get_leveled_quantity(getattr(obj.spec, 'produces_'+res))
                        rates[res] += my_rate
                        if constrain_harvester_capacity:
                            togo = obj.get_leveled_quantity(obj.spec.production_capacity) * (3600.0/my_rate)
                            if max_wait < 0:
                                max_wait = togo
                            else:
                                max_wait = min(max_wait, togo)

        min_wait = 0
        to_harvest = dict((res, max(target[res] - self.player.resources[res], 0)) for res in target)
        for res in to_harvest:
            if to_harvest[res] > 0:
                togo = max(to_harvest[res] * (3600.0/rates[res]), 60)
                min_wait = max(min_wait, togo)
        assert min_wait > 0

        if max_wait >= 0:
            min_wait = min(min_wait, max_wait)

        return min_wait

    def spend_resources(self, amounts):
        new = self.clone()
        new.player = new.player.clone()
        new.player.resources = copy.copy(new.player.resources)
        for res, qty in amounts.iteritems():
            assert new.player.resources[res] >= qty
            new.player.resources[res] -= qty
        return new

    def advance_time(self, min_dt, actual_dt, reason = None):
        # min_dt is the optimal "speedup-able" wait time
        # acutal_dt is how long the player actually waits

        if verbose >= 2:
            if True:
                lines = int(actual_dt) // 3600
            elif actual_dt >= 86400: # 1day+
                lines = 4
            elif actual_dt >= 8*3600: # 8 hours+
                lines = 2
            elif actual_dt >= 15*60: # 15min+
                lines = 1
            else:
                lines = 0
            for i in xrange(lines):
                print '.'*6, reason or ''

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
                            if constrain_harvester_capacity:
                                amount = min(amount, obj.get_leveled_quantity(obj.spec.production_capacity))
                            #print obj.spec.name, obj.level, amount
                            new.player.resources[res] = min(cap[res], new.player.resources[res] + amount)

        # update building states
        new_base = []
        m_and_m = None

        for obj in new.player.my_base:
            if obj.research_finish_time > 0 and new.t >= obj.research_finish_time:
                obj = obj.clone()
                techname, obj.research_item, obj.research_finish_time = obj.research_item, None, -1
                new.player.tech = copy.copy(new.player.tech)
                new.player.tech[techname] = new.player.tech.get(techname,0) + 1
                reward = ResearchTechAction(techname, new.player.tech[techname], 0)
                if (not m_and_m) or (reward.coolness > m_and_m.coolness):
                    m_and_m = reward

            if obj.upgrade_finish_time > 0 and new.t >= obj.upgrade_finish_time:
                obj = obj.clone()
                obj.upgrade_finish_time = -1
                obj.level += 1
                reward = UpgradeBuildingAction(obj.spec.name, obj.level, 0)
                if (not m_and_m) or (reward.coolness > m_and_m.coolness):
                    m_and_m = reward

            new_base.append(obj)

        new.player.my_base = new_base

        if verbose and m_and_m and m_and_m.coolness >= 1:
            print '*'*min(10, int(m_and_m.coolness)), m_and_m.coolness, m_and_m

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

class Action(object):
    def __init__(self, implied_wait, coolness):
        # for strategy choice only - how long this action takes, for comparison vs. other possible actions
        self.implied_wait = implied_wait
        self.coolness = coolness
    def priority(self):
        #print self.coolness, self.implied_wait, self.implied_wait/3600.0, -((self.implied_wait/3600.0) * discount_tau)
        return self.coolness * math.exp(-((self.implied_wait/3600.0) * discount_tau))

class WaitAction(Action):
    def __init__(self, duration, reason, override_coolness = None):
        Action.__init__(self,
                        duration,
                        override_coolness or float('-inf')) # just waiting is the worst choice

        self.min_duration = duration

        # if simulating human attention span, turn any 29m+ wait
        # into a random number of hours
        if take_breaks and duration > 29*60 and (duration > 6*60 or random.random() < 0.25):
            self.actual_duration = max(duration, random.randint(0,24)* 3600)
        else:
            self.actual_duration = self.min_duration

        self.reason = reason

    def __repr__(self):
        if take_breaks:
            return 'Wait %s (actual %s) (%s) %s' % (SpinConfig.pretty_print_time(self.min_duration),
                                                    SpinConfig.pretty_print_time(self.actual_duration),
                                                    self.reason, pretty_print_priority(self.priority()))
        else:
            return 'Wait %s (%s) %s' % (SpinConfig.pretty_print_time(self.min_duration), self.reason, pretty_print_priority(self.priority()))

    def apply(self, state):
        return state.advance_time(self.min_duration, self.actual_duration, reason = self.reason)

class ConstructBuildingAction(Action):
    def __init__(self, specname, override_coolness = None):
        spec = MockSpec(gamedata['buildings'][specname])
        build_time = get_leveled_quantity(spec.build_time, 1)

        if override_coolness:
            coolness = override_coolness
        else:
            coolness = spec.get_building_coolness(1)

        Action.__init__(self, build_time, coolness)
        self.specname = specname

    def __repr__(self): return 'Construct "%s" L%d %s' % (self.specname, 1, pretty_print_priority(self.priority()))
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
    def __init__(self, specname, newlevel, idx, override_coolness = None):
        spec = MockSpec(gamedata['buildings'][specname])
        build_time = get_leveled_quantity(spec.build_time, newlevel)

        if override_coolness:
            coolness = override_coolness
        else:
            coolness = spec.get_building_coolness(newlevel)

        Action.__init__(self, build_time, coolness)
        self.specname = specname
        self.newlevel = newlevel
        self.idx = idx

    def __repr__(self): return 'Upgrade "%s" L%d #%d %s' % (self.specname, self.newlevel, self.idx, pretty_print_priority(self.priority()))
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
        spec = MockSpec(gamedata['tech'][specname])
        research_time = get_leveled_quantity(spec.research_time, newlevel)

        coolness = spec.get_tech_coolness(newlevel)

        Action.__init__(self, research_time, coolness)
        self.specname = specname
        self.newlevel = newlevel
        self.lab_idx = lab_idx

    def __repr__(self): return 'Research "%s" L%d %s' % (self.specname, self.newlevel, pretty_print_priority(self.priority()))
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

def get_possible_actions(state, strategy):
    player = state.player
    current_power = state.player.get_power_state()
    is_low_power = current_power[0] < current_power[1]
    cc_level = state.player.get_townhall_level()
    storage_cap = state.player.get_resource_storage_cap()

    ret_construct = []
    ret_upgrade = []
    ret_tech = []
    ret_wait = []

    if (not constrain_foremen) or player.foreman_is_free():

        # building construction
        for specname, json_spec in gamedata['buildings'].iteritems():
            if specname in ('barrier', 'minefield'): continue # skip these for now
            spec = MockSpec(json_spec)
            if spec.developer_only: continue

            if constrain_power and \
               (not spec.provides_power) and is_low_power: continue

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

            ret_construct.append(ConstructBuildingAction(specname, override_coolness = COOLNESS['fix_low_power'] if is_low_power and spec.provides_power else None))

        # building upgrade
        if (not strategy) or (not ret_construct): # if strategy is enabled, always construct before upgrade

            for i, obj in enumerate(player.home_base_iter()):
                if obj.is_busy(): continue
                if obj.spec.name == 'barrier': continue # skip for now
                if obj.level >= len(obj.spec.build_time): continue # maxed level
                newlevel = obj.level + 1
                spec = obj.spec
                if any(pred and (not Predicates.read_predicate(get_leveled_quantity(pred, newlevel)).is_satisfied(player, None)) \
                       for pred in (spec.show_if, spec.requires, spec.activation)):
                    continue # predicate failed

                cost = dict((res, get_leveled_quantity(getattr(spec, 'build_cost_'+res, 0), newlevel)) \
                             for res in gamedata['resources'])

                if (not is_payer) and any(amount < 0 for amount in cost.itervalues()):
                    continue # not allowed to Use Resources

                action = UpgradeBuildingAction(spec.name, newlevel, i,
                                               override_coolness = COOLNESS['fix_low_power'] if is_low_power and spec.provides_power else None)

                if constrain_resources and \
                   any(cost[res] > player.resources[res] for res in gamedata['resources']):
                    # resource cost failed
                    if action.coolness > COOLNESS.get('default',1.0):
                        # but, it might be important enough to wait for...
                        if not any(cost[res] > storage_cap[res] for res in gamedata['resources']):
                            action = WaitAction(state.get_time_to_reach_resources(cost),
                                                'for resources for '+str(action),
                                                # note: discount by action time PLUS wait time
                                                override_coolness = action.priority())
                            ret_wait.append(action)
                            continue
                        else:
                            continue # storage cap not high enough
                    else:
                        continue # not important enough to wait for resources

                ret_upgrade.append(action)

    # tech research
    # if strategy is enabled, don't research if there is construction available
    if (not strategy) or ((not ret_construct)): #  and (not ret_upgrade)):
        for techname, json_spec in gamedata['tech'].iteritems():
            spec = MockSpec(json_spec)
            if spec.developer_only: continue
            newlevel = player.tech.get(spec.name,0)+1
            if newlevel > len(spec.research_time): continue # already at max level

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

            ret_tech.append(ResearchTechAction(techname, newlevel, lab_idx))

    if True: # (not strategy) or (not (ret_tech or ret_construct or ret_upgrade)):
        # do nothing for a while
        min_wait, wait_reason = state.get_min_wait()
        if min_wait >= 0:
            ret_wait.append(WaitAction(min_wait, wait_reason))

    return ret_tech + ret_construct + ret_upgrade + ret_wait

def apply_gamedata_hacks(gamedata):
    if game_id in ('tr','dv'):

        for specname in ('fuel_depot', 'supply_depot'):
            # depots L8 are not necessary to reach CC5
            gamedata['buildings'][specname]['requires'][8-1] = { "predicate": "BUILDING_LEVEL", "building_type": "toc", "trigger_level": 5 }

        for specname in ('fuel_yard', 'supply_yard'):
            # yards L4 slow down progress to CC3
            gamedata['buildings'][specname]['requires'][4-1] = { "predicate": "BUILDING_LEVEL", "building_type": "toc", "trigger_level": 3 }
            # yards L6 (L4 if free resources) slow down progress to CC4
            gamedata['buildings'][specname]['requires'][6-1] = { "predicate": "BUILDING_LEVEL", "building_type": "toc", "trigger_level": 4 }
            # yards L7 slow down progress to CC5
            gamedata['buildings'][specname]['requires'][7-1] = { "predicate": "BUILDING_LEVEL", "building_type": "toc", "trigger_level": 5 }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    to_cc_level = None
    max_iter = 9999999
    heuristic = 'random'
    strategy = None
    output_filename = None

    opts, args = getopt.gnu_getopt(sys.argv, 'g:vpf', ['verbose','payer','free-resources','take-breaks',
                                                       'to-cc-level=','heuristic=','strategy=','output=',
                                                       'max-iter=',
                                                       'constrain-resources=','constrain-power=','constrain-foremen='])
    for key,val in opts:
        if key == '-g': game_id = val
        elif key == '-v' or key == '--verbose': verbose += 1
        elif key == '-p' or key == '--payer': is_payer = True
        elif key == '-f' or key == '--free-resources': free_resources = True
        elif key == '--take-breaks': take_breaks = True
        elif key == '--to-cc-level': to_cc_level = int(val)
        elif key == '--heuristic':
            assert val in ('random', 'first', 'fastest', 'discounted-coolness')
            heuristic = val
        elif key == '--strategy':
            strategy = val
        elif key == '--output': output_filename = val
        elif key == '--max-iter': max_iter = int(val)
        elif key.startswith('--constrain-'):
            val = True if val in ('1','yes') else False
            if key == '--constrain-resources': constrain_resources = val
            elif key == '--constrain-power': constrain_power = val
            elif key == '--constrain-foremen': constrain_foremen = val

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    apply_gamedata_hacks(gamedata)

    if 0:
        print ResearchTechAction('m109_production', 6, 0).priority()
        print ResearchTechAction('m2bradley_production', 1, 0).priority()
        sys.exit(0)

    state = State()
    state.init_starting_conditions()

    i = 0

    while i < max_iter:

        cc_level = state.player.get_townhall_level()

        storage_cap = state.player.get_resource_storage_cap()

        if verbose:
            #print '-'*80
            print '%4d CC%2d %13s %52s' % \
                  (i, cc_level, SpinConfig.pretty_print_time(state.t), ', '.join('%s: %8d/%8d' % (res, state.player.resources[res], storage_cap[res]) for res in gamedata['resources'] if res != 'res3')),

        if to_cc_level and cc_level >= to_cc_level:
            if verbose:
                print 'DONE!'
            break

        actions = get_possible_actions(state, strategy)
        if not actions:
            print 'no actions!'
            break

        # pick an action

        if heuristic == 'first':
            action = actions[0]
        elif heuristic == 'random':
            action = actions[random.randint(0, len(actions)-1)]
        elif heuristic == 'fastest':
            actions.sort(key = lambda a: a.implied_wait)
            action = actions[0]
        elif heuristic == 'discounted-coolness':
            actions.sort(key = lambda a: -a.priority())
            action = actions[0]

        if verbose >= 3:
            print
            print '\n'.join(map(str,actions))

        if verbose:
            print ' *', action

        new_state = action.apply(state)

        if collect_quests:
            new_state = new_state.collect_quests()

        deltaT = new_state.t - state.t

        state = new_state
        i += 1

    if verbose >= 2:

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
