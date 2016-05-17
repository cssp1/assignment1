#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a library for use by the game server to perform looting of
# resources when a building explodes

import random, copy
import Predicates

# instantiate an appropriate looter for this (viewed) player and this base
def ResLoot(gamedata, session, attacker, defender, base):
    if defender.is_ai() and (base.base_type in ('home','hive')) and (base.base_resource_loot is not None):
        return SpecificPvEResLoot(gamedata, session, attacker, defender, base)
    elif defender.is_ai() or (base is not defender.my_home):
        return TablePvEResLoot(gamedata, session, attacker, defender, base)
    else: # PvP
        pvp_loot_method = gamedata.get('pvp_loot_method','hardcore')
        if defender.home_region and defender.home_region in gamedata['regions'] and 'pvp_loot_method' in gamedata['regions'][defender.home_region]:
            pvp_loot_method = gamedata['regions'][defender.home_region]['pvp_loot_method']
        pvp_loot_method = defender.get_any_abtest_value('pvp_loot_method', pvp_loot_method)
        if (base is not defender.my_home) and pvp_loot_method == 'specific': # XXX remove home_base condition for AI attacks?
            return SpecificPvPResLoot(gamedata, session, attacker, defender, base)
        else:
            return HardcorePvPResLoot(gamedata, session, attacker, defender, base)

class BaseResLoot(object):
    def __init__(self, gamedata, session, attacker, defender, base):
        self.attacker = attacker
        self.defender = defender
        self.base = base
        self.total_looted_uncapped = {} # total resource amounts looted, prior to capping to attacker's storage limit

    # tell client about updates to the resource loot state
    def send_update(self, retmsg): pass

    # called when creating the battle summary; return whatever fields we are responsible for injecting into the summary
    def battle_summary_props(self): return {}

    # compute and return (looted, looted_uncapped, lost) amounts (dictionaries like {"iron": 1234, "water": 500})
    # and also perform the actual resource transfers
    def loot_building(self, gamedata, session, obj, old_hp, new_hp,
                      owning_player, # usually obj.owner, but may be None for "virtual" owners like Rogue/Environment
                      attacker):
        if obj.spec.worth_less_xp or (not (obj.is_storage() or obj.is_producer())): return None, None, None # not lootable

        # call into subclass to determine amounts and to subtract lost resources
        looted, lost = self.do_loot_building(gamedata, session, obj, old_hp, new_hp, owning_player, attacker)

        for res, amount in looted.iteritems():
            self.total_looted_uncapped[res] = self.total_looted_uncapped.get(res,0) + amount

        looted_uncapped = copy.copy(looted) # save a copy of the uncapped amounts before modification below

        # now add gained resources
        if attacker and attacker.is_human():
            # check player's resource storage limit
            storage_limit_factor = attacker.get_any_abtest_value('loot_storage_limit', gamedata['loot_storage_limit'])
            excess = {}

            if storage_limit_factor > 0 and storage_limit_factor < 10:
                # reduce looted quantity to fit into the limit
                snapshot = attacker.resources.calc_snapshot()
                for res in looted:
                    max_loot = max(0, int(storage_limit_factor * snapshot.max_res(res)) - snapshot.cur_res(res))
                    if looted[res] > max_loot:
                        excess[res] = looted[res] - max_loot
                        looted[res] -= excess[res]

                    assert looted.get(res,0) >= 0

                    if snapshot.cur_res(res) <= snapshot.max_res(res):
                        # sanity check, but ignore cases when the limit was already broken
                        assert snapshot.cur_res(res) + looted[res] <= int(storage_limit_factor*snapshot.max_res(res))

            # award the resources to the player
            attacker.resources.gain_res(looted, reason = 'looted_from_ai' if ((not owning_player) or owning_player.is_ai()) else 'looted_from_human',
                                        break_limit = True, # skip calculation of snapshot since amounts are already capped
                                        metadata={'opponent_user_id': owning_player.user_id if owning_player else -1,
                                                  'opponent_level': owning_player.resources.player_level if owning_player else -1,
                                                  'opponent_type': owning_player.ai_or_human() if owning_player else 'ai'})
        return looted, looted_uncapped, lost


# utility for tracking specific amounts of loot attached to a building and dispensed in gradual "ticks"
class PerBuildingGradualLoot(object):
    def __init__(self, gamedata, obj, amount_by_res):

        # loot is divided into a "tick" for every N hitpoints of damage taken
        # we store only the unclaimed "ticks" in the self.ticks array (per-resource dictionary of amounts)

        self.tick_size = gamedata.get('gradual_loot', -1)
        if self.tick_size > 0:
            n_ticks = ((obj.hp-1) // self.tick_size) + 1 # number of claimable ticks this battle
            assert n_ticks > 0
        else:
            n_ticks = 1

        # divide the total amount_by_res into ticks
        self.ticks = []
        total_so_far = {}
        # XXX this might benefit from "dithering" if the loot amount is lower than n_ticks
        for t in xrange(0, n_ticks):
            tick = {}
            for res, amount in amount_by_res.iteritems():
                tick_amount = amount // n_ticks # might be zero
                if tick_amount > 0:
                    tick[res] = tick_amount
                    total_so_far[res] = total_so_far.get(res,0) + tick_amount
            self.ticks.append(tick)

        # add any left-over remainder into tick zero
        for res, amount in amount_by_res.iteritems():
            remainder = amount - total_so_far.get(res,0)
            if remainder > 0:
                self.ticks[0][res] = self.ticks[0].get(res,0) + remainder

    # perform the actual looting. Add looted amounts into "output" dictionary (resource -> amount)
    def grab(self, new_hp, output):

        # zero-based index of the lowest-numbered tick this amount of damage can claim
        if new_hp <= 0:
            this_tick = 0
        else:
            this_tick = ((new_hp-1) // self.tick_size) + 1

        while len(self.ticks) > this_tick:
            tick = self.ticks.pop() # pull the highest-numbered tick off the list

            for res, amount in tick.iteritems():
                output[res] = output.get(res,0) + amount

        return len(self.ticks) == 0 # return true if all loot is completely gone

    def scale_by(self, factors):
        for tick in self.ticks:
            for res, factor in factors.iteritems():
                if res in tick:
                    tick[res] = int(factor * tick[res] + 0.5)
    def total(self):
        ret = {}
        for tick in self.ticks:
            for res, amount in tick.iteritems():
                ret[res] = ret.get(res,0) + amount
        return ret

    def serialize(self):
        return copy.deepcopy(self.ticks)

# SG-style PvE looting: decrements a persistent base-wide specific total, deterministically
class SpecificPvEResLoot(BaseResLoot):
    def __init__(self, gamedata, session, attacker, defender, base):
        BaseResLoot.__init__(self, gamedata, session, attacker, defender, base)

        self.modifier = 1.0
        self.modifier *= attacker.get_any_abtest_value('ai_loot_scale', 1) # note: do NOT apply gamedata['ai_bases_server']['loot_scale']

        # ALSO NOTE: gamedata['ai_bases_server']['loot_randomness'] IS NOT APPLIED!
        # Doing this would be complicated since we need to "freeze"
        # its value upon first Spy of the base, meaning it'd have to
        # be stored in AIInstanceTable or in a cooldown or random
        # number seed on the player or something.

        self.modifier *= attacker.stattab.get_player_stat('loot_factor_pve')
        if self.base.base_type != 'quarry' and self.base.base_richness > 0:
            self.modifier *= self.base.base_richness
        if self.base.base_region and (self.base.base_region in gamedata['regions']):
            self.modifier *= gamedata['regions'][self.base.base_region].get('hive_yield', 1)

        # this is how much we'd give out if all non-destroyed buildings get destroyed
        self.starting_base_resource_loot = dict((res, int(self.modifier * base.base_resource_loot[res] + 0.5)) for res in base.base_resource_loot)

        # keep track of loot on a per-building basis
        self.by_building_id = None

    def assign_loot_to_buildings(self, gamedata):
        if self.by_building_id is not None: return # already assigned
        self.by_building_id = {}

        # compute total contribution coefficient of all buildings

        # for buildings that are capacity-weighted
        total_contribution = {} # {resource: total_amount}

        # for buildings that take a fraction of the total loot pool instead of being capacity-weighted
        fractions_taken = {} # {resource: total_fraction}

        last_ids = {} # keep track of last building seen (per resource), to deposit rounded-off amounts on

        for p in self.base.iter_objects():
            if p.is_building() and (not p.is_destroyed()):
                fraction = p.specific_pve_loot_fraction()
                contrib = p.resource_loot_contribution()
                if fraction or contrib:
                    for res in gamedata['resources']:
                        if fraction and res in fraction:
                            fractions_taken[res] = fractions_taken.get(res,0) + fraction[res]
                        elif contrib and res in contrib:
                            total_contribution[res] = total_contribution.get(res,0) + contrib[res]
                        else:
                            continue
                        last_ids[res] = p.obj_id

        # divide out starting loot among the buildings, weighted by each building's contribution coefficient
        if (fractions_taken or total_contribution) and last_ids:
            total_so_far = {} # keep track of how much resource loot was assigned so far
            # (we need to ensure it adds up to starting_base_resource_loot when all buildings are destroyed)

            for p in self.base.iter_objects():
                if p.is_building() and (not p.is_destroyed()):
                    fraction = p.specific_pve_loot_fraction()
                    contrib = p.resource_loot_contribution()
                    if fraction or contrib:
                        amount_by_res = {}
                        for res in gamedata['resources']:
                            if res in last_ids and p.obj_id == last_ids[res]:
                                # add any left-over amount from rounding remainders onto the last building for this resource type
                                amount = self.starting_base_resource_loot.get(res,0) - total_so_far.get(res,0)
                            else:
                                # note: this needs to multiply the base_loot the AI had at the *start* of the battle, not the current value

                                if fraction and res in fraction:
                                    amount = int( fraction[res] * self.starting_base_resource_loot.get(res, 0) + 0.5)
                                elif contrib and res in contrib:
                                    # take what's left after fractions_taken is removed from available loot
                                    amount = int( (contrib[res]/float(total_contribution[res])) * (1 - fractions_taken.get(res,0)) * self.starting_base_resource_loot.get(res, 0) + 0.5)
                                else:
                                    amount = 0

                                total_so_far[res] = total_so_far.get(res,0) + amount

                            if amount > 0:
                                amount_by_res[res] = amount
                        if amount_by_res:
                            self.by_building_id[p.obj_id] = PerBuildingGradualLoot(gamedata, p, amount_by_res)

    def send_update(self, retmsg):
        # return the starting and current amounts of loot the base has to offer the player
        retmsg.append(["RES_LOOTER_UPDATE", {'starting': self.starting_base_resource_loot,
                                             # 'by_id': copy.deepcopy(self.by_building_id), # for debugging only
                                             'cur': dict((res, int(self.modifier*amount+0.5)) for res, amount in self.base.base_resource_loot.iteritems()),
                                             'looted_uncapped': copy.deepcopy(self.total_looted_uncapped)}])

    def battle_summary_props(self):
        ret = BaseResLoot.battle_summary_props(self)
        ret['starting_base_resource_loot'] = self.starting_base_resource_loot
        return ret

    def do_loot_building(self, gamedata, session, obj, old_hp, new_hp, owning_player, attacker):
        # perform one-time setup, if necessary
        self.assign_loot_to_buildings(gamedata)

        lost = {}

        if obj.obj_id in self.by_building_id:
            if self.by_building_id[obj.obj_id].grab(new_hp, lost):
                del self.by_building_id[obj.obj_id] # all gone

            for res in lost:
                if lost[res] > 0:
                    # take the loot away from the base itself, so that less will be available next battle
                    self.base.base_resource_loot[res] = max(0, self.base.base_resource_loot.get(res,0) - int(lost[res]/self.modifier + 0.5))

        looted = copy.copy(lost)
        return looted, lost

# MF/TR-style PvE looting: based on a per-building "loot table" amount, with randomization
class TablePvEResLoot(BaseResLoot):
    def do_loot_building(self, gamedata, session, obj, old_hp, new_hp, owning_player, attacker):
        assert new_hp == 0
        looted = {}
        lost = {}

        loot_table = gamedata['ai_bases_server']['loot_table'].get(obj.spec.history_category, [0])

        # PvE-specific loot table modifiers
        loot_table_modifier = (1.0 + gamedata['ai_bases_server']['loot_randomness']*(2*random.random()-1))
        loot_table_modifier *= attacker.get_any_abtest_value('ai_loot_scale', gamedata['ai_bases_server']['loot_scale'])
        loot_table_modifier *= attacker.stattab.get_player_stat('loot_factor_pve')
        if self.base.base_type != 'quarry' and self.base.base_richness > 0:
            loot_table_modifier *= self.base.base_richness
        if self.base.base_region and (self.base.base_region in gamedata['regions']):
            loot_table_modifier *= gamedata['regions'][self.base.base_region].get('hive_yield', 1)

        # count how many buildings of this spec the owning player has, and divide loot equally between them
        nsame = 0
        found = False
        for p in self.base.iter_objects():
            if p.spec.name == obj.spec.name: nsame += 1 # check history_category instead ?
            if p is obj: found = True
        assert nsame > 0
        assert found

        for res in gamedata['resources']:
            qty = max(obj.get_leveled_quantity(getattr(obj.spec, 'storage_'+res)),
                      obj.get_leveled_quantity(getattr(obj.spec, 'produces_'+res)))
            if qty > 0:
                lost[res] = looted[res] = int(loot_table_modifier * loot_table[min(self.defender.resources.player_level-1,len(loot_table)-1)]/float(nsame))

        return looted, lost

# common code for PvP looting
class PvPResLoot(BaseResLoot):
    def compute_gain_loss_coeffs(self, gamedata, session, kind): # kind is "storage" or "producer"
        # note: this the per-region scaling code was written but never put into production (!)
        loot_attacker_gains_region_scale = 1
        loot_defender_loses_region_scale = 1

        if self.attacker.home_region and self.attacker.home_region in gamedata['regions']:
            loot_attacker_gains_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][self.attacker.home_region].get('loot_attacker_gains_scale_if_attacker',1), session, self.attacker)
            loot_defender_loses_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][self.attacker.home_region].get('loot_defender_loses_scale_if_attacker',1), session, self.attacker)
        if self.defender.home_region and self.defender.home_region in gamedata['regions']:
            loot_attacker_gains_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][self.defender.home_region].get('loot_attacker_gains_scale_if_defender',1), session, self.defender)
            loot_defender_loses_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][self.defender.home_region].get('loot_defender_loses_scale_if_defender',1), session, self.defender)

        base_loot_attacker_gains_table = gamedata['loot_attacker_gains']
        if self.defender.home_region and self.defender.home_region in gamedata['regions'] and 'loot_attacker_gains' in gamedata['regions'][self.defender.home_region]:
            base_loot_attacker_gains_table = gamedata['regions'][self.defender.home_region]['loot_attacker_gains']
        base_loot_attacker_gains_table = self.defender.get_any_abtest_value('loot_attacker_gains', base_loot_attacker_gains_table)

        if type(base_loot_attacker_gains_table) is dict:
            # note: predicates evaluated on defender, not attacker!
            base_loot_attacker_gains = dict((res, Predicates.eval_cond_or_literal(base_loot_attacker_gains_table[res][kind], session, self.defender)['ratio']) for res in gamedata['resources'])
        else: # one value for all kinds
            base_loot_attacker_gains = dict((res, base_loot_attacker_gains_table) for res in gamedata['resources'])

        base_loot_defender_loses_table = gamedata['loot_defender_loses']
        if self.defender.home_region and self.defender.home_region in gamedata['regions'] and 'loot_defender_loses' in gamedata['regions'][self.defender.home_region]:
            base_loot_defender_loses_table = gamedata['regions'][self.defender.home_region]['loot_defender_loses']
        base_loot_defender_loses_table = self.defender.get_any_abtest_value('loot_defender_loses', base_loot_defender_loses_table)

        if type(base_loot_defender_loses_table) is dict:
            # note: predicates evaluated on defender, not attacker!
            base_loot_defender_loses = dict((res, Predicates.eval_cond_or_literal(base_loot_defender_loses_table[res][kind], session, self.defender)['ratio']) for res in gamedata['resources'])
        else: # one value for all kinds
            base_loot_defender_loses = dict((res, base_loot_defender_loses_table) for res in gamedata['resources'])

        loot_attacker_gains = dict((res,
                                    base_loot_attacker_gains[res] * \
                                    self.attacker.stattab.get_player_stat('loot_factor_pvp') * \
                                    resdata.get('loot_attacker_gains',1),
                                    ) for res, resdata in gamedata['resources'].iteritems())

        loot_defender_loses = dict((res,
                                    base_loot_defender_loses[res] * \
                                    self.attacker.stattab.get_player_stat('loot_factor_pvp') * \
                                    resdata.get('loot_defender_loses',1),
                                    ) for res, resdata in gamedata['resources'].iteritems())

        for res in gamedata['resources']:
            loot_attacker_gains[res] = min(max(loot_attacker_gains[res],0),1)
            loot_defender_loses[res] = min(max(loot_defender_loses[res],0),1)
            if loot_attacker_gains[res] > loot_defender_loses[res]:
                raise Exception('%d vs %d: loot_attacker_gains[%s] %f > loot_defender_loses[%s] %f' % \
                                (self.attacker.user_id, self.defender.user_id,
                                 res, loot_attacker_gains[res], res, loot_defender_loses[res]))
                loot_attacker_gains[res] = loot_defender_loses[res]

        return loot_attacker_gains, loot_defender_loses

# MF/TR-style PvP looting: fractional, randomized amounts taken from harvesters/storages
class HardcorePvPResLoot(PvPResLoot):
    def do_loot_building(self, gamedata, session, obj, old_hp, new_hp, owning_player, attacker):
        assert new_hp == 0
        looted = {}
        lost = {}

        loot_attacker_gains, loot_defender_loses = self.compute_gain_loss_coeffs(gamedata, session, 'storage' if obj.is_storage() else 'producer')

        if obj.is_storage(): # loot a storage building (includes tonwhalls, if they have storage!)
            # count how many storage buildings the owning player has
            assert obj in self.base.iter_objects()

            # legacy note: previously, we used "nbuild" (total number of ALL storage buildings) as the
            # denominator in the loot distribution. This produces incorrect results (e.g. looting a single
            # res3 storage when 4 other iron/water storages are present will result in 1/5th the expected loot).

            # There is now an option to use a more proper calculation (dividing by the number of storage buildings
            # of THIS resource, weighted by capacity), but since this is very much incompatible with current JSON
            # numbers, we are enabling the "loot_storage_distribution_bug" in titles that haven't been updated yet.

            loot_storage_distribution_bug = gamedata.get('loot_storage_distribution_bug', False)
            if self.defender.home_region and self.defender.home_region in gamedata['regions'] and 'loot_storage_distribution_bug' in gamedata['regions'][self.defender.home_region]:
                loot_storage_distribution_bug = gamedata['regions'][self.defender.home_region]['loot_storage_distribution_bug']
            loot_storage_distribution_bug = self.defender.get_any_abtest_value('loot_storage_distribution_bug', loot_storage_distribution_bug)

            nbuild = 0
            weights = dict((res, 0) for res in gamedata['resources'])

            for p in self.base.iter_objects():
                if p.is_building() and p.is_storage():
                    # note: do not include building in weights if it was destroyed already
                    if not p.is_destroyed():
                        for res in gamedata['resources']:
                            weights[res] += p.get_leveled_quantity(getattr(p.spec, 'storage_'+res))
                    # but do include in nbuild even if destroyed, for legacy compatibility
                    nbuild += 1
            assert nbuild > 0


            if loot_storage_distribution_bug:
                # legacy method for backwards compatibility
                factors = dict((res, (1.0/nbuild)) for res in gamedata['resources'])
            else:
                factors = {}
                for res in gamedata['resources']:
                    if obj.get_leveled_quantity(getattr(obj.spec, 'storage_'+res)) > 0:
                        assert weights[res] > 0
                        factors[res] = (obj.get_leveled_quantity(getattr(obj.spec, 'storage_'+res))/float(weights[res]))
                    else:
                        factors[res] = 0

            for res in gamedata['resources']:
                if obj.get_leveled_quantity(getattr(obj.spec, 'storage_'+res)) > 0:
                    looted[res] = int(factors[res] * loot_attacker_gains[res] * getattr(owning_player.resources,res))
                    lost[res] = int(factors[res] * loot_defender_loses[res] * getattr(owning_player.resources,res))

            # loot is taken directly from the owner's stored resources
            owning_player.resources.gain_res(dict((res,-lost[res]) for res in lost), reason='looted_by_attacker')

        # loot a harvester
        elif obj.is_producer():
            for res in gamedata['resources']:
                if obj.get_leveled_quantity(getattr(obj.spec, 'produces_'+res)) > 0:
                    looted[res] = int(loot_attacker_gains[res] * obj.contents)
                    lost[res] = int(loot_defender_loses[res] * obj.contents)

                    # take from the uncollected resources inside the harvester
                    obj.contents -= lost[res]
        return looted, lost

# SG-style PvP looting: more similar to the "specific" PvE loot code
class SpecificPvPResLoot(PvPResLoot):
    def __init__(self, gamedata, session, attacker, defender, base):
        BaseResLoot.__init__(self, gamedata, session, attacker, defender, base)

        if base.base_resource_loot is None:
            # we're going to persist this between logins to remember the amount of resources still "unexposed" to looting
            base.base_resource_loot = dict((res, getattr(self.defender.resources, res)) for res in gamedata['resources'])

        # precalculate the total loot available to the attacker
        self.starting_resource_loot = dict((res, 0) for res in gamedata['resources'])

        loot_attacker_gains_storage, loot_defender_loses_storage = self.compute_gain_loss_coeffs(gamedata, session, 'storage')
        loot_attacker_gains_producer, loot_defender_loses_producer = self.compute_gain_loss_coeffs(gamedata, session, 'producer')

        # dictionaries from kind -> res -> cap on absolute loot/loss amount
        attacker_caps = dict((kind, dict((res, -1) for res in gamedata['resources'])) for kind in ('storage', 'producer'))
        defender_caps = dict((kind, dict((res, -1) for res in gamedata['resources'])) for kind in ('storage', 'producer'))

        # get caps
        base_loot_attacker_gains_table = gamedata['loot_attacker_gains']
        if self.defender.home_region and self.defender.home_region in gamedata['regions'] and 'loot_attacker_gains' in gamedata['regions'][self.defender.home_region]:
            base_loot_attacker_gains_table = gamedata['regions'][self.defender.home_region]['loot_attacker_gains']
        base_loot_defender_loses_table = gamedata['loot_defender_loses']
        if self.defender.home_region and self.defender.home_region in gamedata['regions'] and 'loot_defender_loses' in gamedata['regions'][self.defender.home_region]:
            base_loot_defender_loses_table = gamedata['regions'][self.defender.home_region]['loot_defender_loses']
        base_loot_defender_loses_table = self.defender.get_any_abtest_value('loot_defender_loses', base_loot_defender_loses_table)

        if type(base_loot_attacker_gains_table) is dict:
            for kind in attacker_caps:
                for res in attacker_caps[kind]:
                    cap = Predicates.eval_cond_or_literal(base_loot_attacker_gains_table[res][kind], session, self.defender).get('cap',-1) # note: evaluated on defender, not attacker!
                    if cap >= 0:
                        attacker_caps[kind][res] = cap

        if type(base_loot_defender_loses_table) is dict:
            for kind in defender_caps:
                for res in defender_caps[kind]:
                    cap = Predicates.eval_cond_or_literal(base_loot_defender_loses_table[res][kind], session, self.defender).get('cap',-1) # note: evaluated on defender, not attacker!
                    if cap >= 0:
                        defender_caps[kind][res] = cap

        # count how much storage the owning player has for each resource
        total_storage_weight = dict((res, 0) for res in gamedata['resources'])
        # for buildings that take a fraction of the total loot pool instead of being capacity-weighted
        total_storage_fractions_taken = {} # {resource: total_fraction}

        for p in self.base.iter_objects():
            if p.is_building() and p.is_storage() and (not p.is_destroyed()):
                fraction = p.specific_pvp_loot_fraction()
                contrib = p.resource_loot_contribution()
                if fraction or contrib:
                    for res in gamedata['resources']:
                        if fraction and res in fraction:
                            total_storage_fractions_taken[res] = total_storage_fractions_taken.get(res,0) + fraction[res]
                        elif contrib and res in contrib:
                            total_storage_weight[res] += contrib[res]


        # mapping from obj_id to PerBuilding amounts remaining to be (looted, lost, original)
        self.storage_building_amounts = {}

        for p in self.base.iter_objects():
            if p.is_building() and p.is_storage() and (not p.is_destroyed()):
                loot_amounts = {}
                lost_amounts = {}
                orig_amounts = {}
                fraction = p.specific_pvp_loot_fraction()
                contrib = p.resource_loot_contribution()
                for res in gamedata['resources']:
                    # XXX might want to use the last_ids logic to ensure correct rounding as in SpecificPvEResLoot
                    if fraction and res in fraction:
                        weight = fraction[res]
                    elif contrib and res in contrib:
                        weight = contrib[res] / float(total_storage_weight[res])
                        weight *= (1 - total_storage_fractions_taken.get(res,0))
                    else:
                        continue
                    loot_amounts[res] = int(weight * loot_attacker_gains_storage[res] * base.base_resource_loot[res])
                    lost_amounts[res] = int(weight * loot_defender_loses_storage[res] * base.base_resource_loot[res])
                    orig_amounts[res] = int(weight * base.base_resource_loot[res])
                    self.starting_resource_loot[res] += loot_amounts[res]
                if loot_amounts or lost_amounts:
                    self.storage_building_amounts[p.obj_id] = (PerBuildingGradualLoot(gamedata, p, loot_amounts),
                                                               PerBuildingGradualLoot(gamedata, p, lost_amounts),
                                                               PerBuildingGradualLoot(gamedata, p, orig_amounts))

        # mapping from obj_id to PerBuilding amounts remaining to be (looted, lost)
        self.producer_building_amounts = {}

        # compute total contribution of all buildings of each kind
        for p in self.base.iter_objects():
            if p.is_building() and p.is_producer() and (not p.is_destroyed()):
                loot_amounts = {}
                lost_amounts = {}
                for res in gamedata['resources']:
                    if p.get_leveled_quantity(getattr(p.spec, 'produces_'+res)) > 0:
                        # XXX might need to halt and restart p to get contents up to date
                        loot_amounts[res] = min(max(int(loot_attacker_gains_producer[res] * p.contents), 0), p.contents)
                        lost_amounts[res] = min(max(int(loot_defender_loses_producer[res] * p.contents), 0), p.contents)
                        self.starting_resource_loot[res] += loot_amounts[res]
                if loot_amounts or lost_amounts:
                    self.producer_building_amounts[p.obj_id] = (PerBuildingGradualLoot(gamedata, p, loot_amounts),
                                                                PerBuildingGradualLoot(gamedata, p, lost_amounts),
                                                                None)

        # apply caps
        for kind, amounts in (('storage', self.storage_building_amounts), ('producer', self.producer_building_amounts)):
            for res in gamedata['resources']:
                factor = 1
                total_loot = sum((x[0].total().get(res,0) for x in amounts.itervalues()), 0)
                total_lost = sum((x[1].total().get(res,0) for x in amounts.itervalues()), 0)
                if attacker_caps[kind][res] >= 0 and total_loot > attacker_caps[kind][res]:
                    factor = min(factor, attacker_caps[kind][res] / float(total_loot))
                if defender_caps[kind][res] >= 0 and total_lost > defender_caps[kind][res]:
                    factor = min(factor, defender_caps[kind][res] / float(total_lost))
                if factor < 1:
                    # scale down all loot amounts to meet cap
                    for amt_loot, amt_lost, amt_orig_or_none in amounts.itervalues():
                        old_loot = amt_loot.total().get(res,0)
                        # old_lost = amt_lost.total().get(res,0)
                        amt_loot.scale_by({res: factor})
                        amt_lost.scale_by({res: factor})

                        # subtract delta from total lootable count
                        self.starting_resource_loot[res] -= (old_loot - amt_loot.total().get(res,0))

        # cur_resource_loot will be decremented as the attacker loots resources, leaving starting_resource_loot alone
        self.cur_resource_loot = copy.deepcopy(self.starting_resource_loot)

    def send_update(self, retmsg):
        retmsg.append(["RES_LOOTER_UPDATE", {'starting': self.starting_resource_loot,
                                             # these can be sent to the client for debugging only
                                             #'base_resource_loot': copy.deepcopy(self.base.base_resource_loot),
                                             #'producer_amounts': dict((k, [v[0].serialize(), v[1].serialize()]) for k, v in self.producer_building_amounts.iteritems()),
                                             #'storage_amounts': dict((k, [v[0].serialize(),v[1].serialize(),v[2].serialize()]) for k, v in self.storage_building_amounts.iteritems()),
                                             'cur': copy.deepcopy(self.cur_resource_loot),
                                             'looted_uncapped': copy.deepcopy(self.total_looted_uncapped)}])

    def battle_summary_props(self):
        ret = BaseResLoot.battle_summary_props(self)
        ret['starting_base_resource_loot'] = self.starting_resource_loot
        return ret

    def do_loot_building(self, gamedata, session, obj, old_hp, new_hp, owning_player, attacker):
        looted = {}
        lost = {}

        if obj.is_storage():
            if obj.obj_id in self.storage_building_amounts:
                self.storage_building_amounts[obj.obj_id][0].grab(new_hp, looted)
                self.storage_building_amounts[obj.obj_id][1].grab(new_hp, lost)
                original = {}
                self.storage_building_amounts[obj.obj_id][2].grab(new_hp, original)
                # delete?

                for res in looted:
                    self.cur_resource_loot[res] -= looted[res]

                # loot is taken directly from the owner's stored resources
                owning_player.resources.gain_res(dict((res,-lost[res]) for res in lost), reason='looted_by_attacker')

                # persist the fraction "seen" by the looting code, and only subject the remainder to future looting
                for res in original:
                    self.base.base_resource_loot[res] = max(0, self.base.base_resource_loot[res] - original[res])

        elif obj.is_producer():
            if obj.obj_id in self.producer_building_amounts:
                self.producer_building_amounts[obj.obj_id][0].grab(new_hp, looted)
                self.producer_building_amounts[obj.obj_id][1].grab(new_hp, lost)
                # delete?

                for res in looted:
                    self.cur_resource_loot[res] -= looted[res]

                for res in lost:
                    # take from the uncollected resources inside the harvester
                    obj.contents -= lost[res]

        return looted, lost
