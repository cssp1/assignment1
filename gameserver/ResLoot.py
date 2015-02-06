#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a library for use by the game server to perform looting of
# resources when a building explodes

import random, copy
import Predicates

# instantiate an appropriate looter for this (viewed) player and this base
def ResLoot(gamedata, session, player, base):
    if (base.base_type in ('home','hive')) and (base.base_resource_loot is not None):
        return SpecificPvEResLoot(gamedata, session, player, base)
    elif player.is_ai() or (base is not player.my_home):
        return TablePvEResLoot(gamedata, session, player, base)
    else: # PvP
        if (not session.home_base) and gamedata.get('pvp_loot_method',None) == 'specific':
            return SpecificPvPResLoot(gamedata, session, player, base)
        else:
            return HardcorePvPResLoot(gamedata, session, player, base)

class BaseResLoot(object):
    def __init__(self, gamedata, session, player, base):
        self.base = base
        self.total_looted_uncapped = {} # total resource amounts looted, prior to capping to attacker's storage limit

    # tell client about updates to the resource loot state
    def send_update(self, retmsg): pass

    # called when creating the battle summary; return whatever fields we are responsible for injecting into the summary
    def battle_summary_props(self): return {}

    # compute and return (looted, looted_uncapped, lost) amounts (dictionaries like {"iron": 1234, "water": 500})
    # and also perform the actual resource transfers
    def loot_building(self, gamedata, session, obj,
                      owning_player, # usually obj.owner, but may be None for "virtual" owners like Rogue/Environment
                      attacker):
        if obj.spec.worth_less_xp or (not (obj.is_storage() or obj.is_producer())): return None, None, None # not lootable

        # call into subclass to determine amounts and to subtract lost resources
        looted, lost = self.do_loot_building(gamedata, session, obj, owning_player)

        for res, amount in looted.iteritems():
            self.total_looted_uncapped[res] = self.total_looted_uncapped.get(res,0) + amount

        looted_uncapped = copy.copy(looted) # save a copy of the uncapped amounts before modification below

        # now add gained resources
        if attacker is session.player:
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
                                        break_limit = True, # skip calculaton of snapshot since amounts are already capped
                                        metadata={'opponent_user_id': owning_player.user_id if owning_player else -1,
                                                  'opponent_level': owning_player.resources.player_level if owning_player else -1,
                                                  'opponent_type': owning_player.ai_or_human() if owning_player else 'ai'})
        return looted, looted_uncapped, lost

# SG-style PvE looting: decrements a persistent base-wide specific total, deterministically
class SpecificPvEResLoot(BaseResLoot):
    def __init__(self, gamedata, session, player, base):
        BaseResLoot.__init__(self, gamedata, session, player, base)

        self.modifier = 1.0
        self.modifier *= session.player.get_any_abtest_value('ai_loot_scale', 1) # note: do NOT apply gamedata['ai_bases']['loot_scale']

        # ALSO NOTE: gamedata['ai_bases']['loot_randomness'] IS NOT APPLIED!
        # Doing this would be complicated since we need to "freeze"
        # its value upon first Spy of the base, meaning it'd have to
        # be stored in AIInstanceTable or in a cooldown or random
        # number seed on the player or something.

        self.modifier *= session.player.stattab.get_player_stat('loot_factor_pve')
        if self.base.base_type != 'quarry' and self.base.base_richness > 0:
            self.modifier *= self.base.base_richness
        if self.base.base_region and (self.base.base_region in gamedata['regions']):
            self.modifier *= gamedata['regions'][self.base.base_region].get('hive_yield', 1)

        self.starting_base_resource_loot = dict((res, int(self.modifier * base.base_resource_loot[res] + 0.5)) for res in base.base_resource_loot)
        self.by_building_id = None

    def assign_loot_to_buildings(self):
        if self.by_building_id is not None: return
        self.by_building_id = {}

        # compute total contribution of all buildings
        total_contribution = {}
        last_ids = {} # keep track of last building seen (per resource), to deposit rounded-off amounts on
        for p in self.base.iter_objects():
            if p.is_building() and (not p.is_destroyed()):
                contrib = p.resource_loot_contribution()
                if contrib:
                    for res, amount in contrib.iteritems():
                        total_contribution[res] = total_contribution.get(res,0) + amount
                        last_ids[res] = p.obj_id

        if total_contribution and last_ids:
            total_so_far = {} # keep track of how much resource loot was assigned so far
            # we need to ensure it adds up to starting_base_resource_loot when all buildings are destroyed

            for p in self.base.iter_objects():
                if p.is_building() and (not p.is_destroyed()):
                    contrib = p.resource_loot_contribution()
                    if contrib:
                        self.by_building_id[p.obj_id] = {}
                        for res in contrib:
                            if p.obj_id is last_ids[res]:
                                # add any left-over amount from rounding onto the last building
                                self.by_building_id[p.obj_id][res] = self.starting_base_resource_loot.get(res,0) - total_so_far.get(res,0)
                            else:
                                # note: this needs to multiply the base_loot the AI had at the *start* of the battle, not the current value
                                amount = int( (contrib[res]/float(total_contribution[res])) * self.starting_base_resource_loot.get(res, 0) + 0.5)
                                self.by_building_id[p.obj_id][res] = amount
                                total_so_far[res] = total_so_far.get(res,0) + amount

    def send_update(self, retmsg):
        # return the starting and current amounts of loot the base has to offer the player
        retmsg.append(["RES_LOOTER_UPDATE", {'starting': self.starting_base_resource_loot,
                                             # 'by_id': copy.deepcopy(self.by_building_id), # for debugging only
                                             'cur': copy.deepcopy(self.base.base_resource_loot),
                                             'looted_uncapped': copy.deepcopy(self.total_looted_uncapped)}])

    def battle_summary_props(self):
        ret = BaseResLoot.battle_summary_props(self)
        ret['starting_base_resource_loot'] = self.starting_base_resource_loot
        return ret

    def do_loot_building(self, gamedata, session, obj, owning_player):
        looted = {}
        lost = {}

        self.assign_loot_to_buildings()

        if obj.obj_id in self.by_building_id:
            looted = lost = self.by_building_id[obj.obj_id]
            del self.by_building_id[obj.obj_id]

            for res in lost:
                if lost[res] > 0:
                    # take the loot away from the base itself, so that less will be available next battle
                    self.base.base_resource_loot[res] = max(0, self.base.base_resource_loot[res] - int(lost[res]/self.modifier + 0.5))

        return looted, lost

# MF/TR-style PvE looting: based on a per-building "loot table" amount, with randomization
class TablePvEResLoot(BaseResLoot):
    def do_loot_building(self, gamedata, session, obj, owning_player):
        looted = {}
        lost = {}

        loot_table = gamedata['ai_bases']['loot_table'].get(obj.spec.history_category, [0])

        # PvE-specific loot table modifiers
        loot_table_modifier = (1.0 + gamedata['ai_bases']['loot_randomness']*(2*random.random()-1))
        loot_table_modifier *= session.player.get_any_abtest_value('ai_loot_scale', gamedata['ai_bases']['loot_scale'])
        loot_table_modifier *= session.player.stattab.get_player_stat('loot_factor_pve')
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
                lost[res] = looted[res] = int(loot_table_modifier * loot_table[min(session.viewing_player.resources.player_level-1,len(loot_table)-1)]/float(nsame))

        return looted, lost

# common code for PvP looting
class PvPResLoot(BaseResLoot):
    def compute_gain_loss_coeffs(self, gamedata, session, kind): # kind is "storage" or "producer"
        # note: this the per-region scaling code was written but never put into production (!)
        loot_attacker_gains_region_scale = 1
        loot_defender_loses_region_scale = 1

        if session.player.home_region and session.player.home_region in gamedata['regions']:
            loot_attacker_gains_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][session.player.home_region].get('loot_attacker_gains_scale_if_attacker',1), session, session.player)
            loot_defender_loses_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][session.player.home_region].get('loot_defender_loses_scale_if_attacker',1), session, session.player)
        if session.viewing_player.home_region and session.viewing_player.home_region in gamedata['regions']:
            loot_attacker_gains_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][session.viewing_player.home_region].get('loot_attacker_gains_scale_if_defender',1), session, session.viewing_player)
            loot_defender_loses_region_scale *= Predicates.eval_cond_or_literal(gamedata['regions'][session.viewing_player.home_region].get('loot_defender_loses_scale_if_defender',1), session, session.viewing_player)

        base_loot_attacker_gains_table = session.viewing_player.get_any_abtest_value('loot_attacker_gains', gamedata['loot_attacker_gains'])

        if type(base_loot_attacker_gains_table) is dict:
            base_loot_attacker_gains = Predicates.eval_cond_or_literal(base_loot_attacker_gains_table[kind], session, session.viewing_player)['ratio'] # note: evaluated on viewing_player, not player!
        else: # one value for all kinds
            base_loot_attacker_gains = base_loot_attacker_gains_table

        base_loot_defender_loses_table = session.viewing_player.get_any_abtest_value('loot_defender_loses', gamedata['loot_defender_loses'])
        if type(base_loot_defender_loses_table) is dict:
            base_loot_defender_loses = Predicates.eval_cond_or_literal(base_loot_defender_loses_table[kind], session, session.viewing_player)['ratio'] # note: evaluated on viewing_player, not player!
        else: # one value for all kinds
            base_loot_defender_loses = base_loot_defender_loses_table

        loot_attacker_gains = dict((res,
                                    base_loot_attacker_gains * \
                                    session.player.stattab.get_player_stat('loot_factor_pvp') * \
                                    resdata.get('loot_attacker_gains',1),
                                    ) for res, resdata in gamedata['resources'].iteritems())

        loot_defender_loses = dict((res,
                                    base_loot_defender_loses * \
                                    session.player.stattab.get_player_stat('loot_factor_pvp') * \
                                    resdata.get('loot_defender_loses',1),
                                    ) for res, resdata in gamedata['resources'].iteritems())

        for res in gamedata['resources']:
            loot_attacker_gains[res] = min(max(loot_attacker_gains[res],0),1)
            loot_defender_loses[res] = min(max(loot_defender_loses[res],0),1)
            if loot_attacker_gains[res] > loot_defender_loses[res]:
                raise Exception('%d vs %d: loot_attacker_gains[%s] %f > loot_defender_loses[%s] %f' % \
                                (session.player.user_id, session.viewing_player.user_id,
                                 res, loot_attacker_gains[res], res, loot_defender_loses[res]))
                loot_attacker_gains[res] = loot_defender_loses[res]

        return loot_attacker_gains, loot_defender_loses

# MF/TR-style PvP looting: fractional, randomized amounts taken from harvesters/storages
class HardcorePvPResLoot(PvPResLoot):
    def do_loot_building(self, gamedata, session, obj, owning_player):
        looted = {}
        lost = {}

        loot_attacker_gains, loot_defender_loses = self.compute_gain_loss_coeffs(gamedata, session, 'storage' if obj.is_storage() else 'producer')

        if obj.is_storage(): # loot a storage building (includes tonwhalls, if they have storage!)
            # count how many storage buildings the owning player has
            assert obj in self.base.iter_objects()

            nbuild = 0
            nsame = 0
            for p in self.base.iter_objects():
                if p.is_building() and p.is_storage():
                    nbuild += 1
                if p.spec.name == obj.spec.name:
                    nsame += 1
            assert nbuild > 0
            assert nsame > 0

            factor = (1.0/nbuild)

            for res in gamedata['resources']:
                if obj.get_leveled_quantity(getattr(obj.spec, 'storage_'+res)) > 0:
                    looted[res] = int(factor * loot_attacker_gains[res] * getattr(owning_player.resources,res))
                    lost[res] = int(factor * loot_defender_loses[res] * getattr(owning_player.resources,res))

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
    def __init__(self, gamedata, session, player, base):
        BaseResLoot.__init__(self, gamedata, session, player, base)

        # precalculate the total loot available to the attacker
        self.starting_resource_loot = dict((res, 0) for res in gamedata['resources'])

        loot_attacker_gains_storage, loot_defender_loses_storage = self.compute_gain_loss_coeffs(gamedata, session, 'storage')
        loot_attacker_gains_producer, loot_defender_loses_producer = self.compute_gain_loss_coeffs(gamedata, session, 'producer')

        # dictionaries from kind -> res -> cap on absolute loot/loss amount
        attacker_caps = dict((kind, dict((res, -1) for res in gamedata['resources'])) for kind in ('storage', 'producer'))
        defender_caps = dict((kind, dict((res, -1) for res in gamedata['resources'])) for kind in ('storage', 'producer'))

        if type(gamedata['loot_attacker_gains'] is dict):
            for kind in attacker_caps:
                cap = Predicates.eval_cond_or_literal(gamedata['loot_attacker_gains'][kind], session, session.viewing_player).get('cap',-1) # note: evaluated on viewing_player, not player!
                if cap >= 0:
                    for res in attacker_caps[kind]:
                        attacker_caps[kind][res] = cap

        if type(gamedata['loot_defender_loses'] is dict):
            for kind in defender_caps:
                cap = Predicates.eval_cond_or_literal(gamedata['loot_defender_loses'][kind], session, session.viewing_player).get('cap',-1) # note: evaluated on viewing_player, not player!
                if cap >= 0:
                    for res in defender_caps[kind]:
                        defender_caps[kind][res] = cap

        # count how many storage buildings the owning player has for each resource
        n_storages = dict((res, 0) for res in gamedata['resources'])
        total_storage_weight = dict((res, 0) for res in gamedata['resources'])
        for p in self.base.iter_objects():
            if p.is_building() and p.is_storage():
                for res in gamedata['resources']:
                    qty = p.get_leveled_quantity(getattr(p.spec, 'storage_'+res))
                    if qty > 0:
                        n_storages[res] += 1
                        total_storage_weight[res] += qty


        # mapping from obj_id to amount remaining to be (looted, lost)
        self.storage_amounts = dict((res, {}) for res in gamedata['resources'])

        for p in self.base.iter_objects():
            if p.is_building() and p.is_storage():
                for res in gamedata['resources']:
                    qty = p.get_leveled_quantity(getattr(p.spec, 'storage_'+res))
                    if qty > 0:
                        weight = qty / float(total_storage_weight[res])
                        loot_amount = int(weight * loot_attacker_gains_storage[res] * getattr(player.resources, res))
                        lost_amount = int(weight * loot_defender_loses_storage[res] * getattr(player.resources, res))
                        self.storage_amounts[res][p.obj_id] = (loot_amount, lost_amount)
                        self.starting_resource_loot[res] += loot_amount

        # mapping from obj_id to amount remaining to be (looted, lost)
        self.producer_amounts = dict((res, {}) for res in gamedata['resources'])

        # compute total contribution of all buildings of each kind
        for p in self.base.iter_objects():
            if p.is_building() and p.is_producer():
                for res in gamedata['resources']:
                    if p.get_leveled_quantity(getattr(p.spec, 'produces_'+res)) > 0:
                        # XXX might need to halt and restart p to get contents up to date
                        loot_amount = min(max(int(loot_attacker_gains_producer[res] * p.contents), 0), p.contents)
                        lost_amount = min(max(int(loot_defender_loses_producer[res] * p.contents), 0), p.contents)
                        self.producer_amounts[res][p.obj_id] = (loot_amount, lost_amount)
                        self.starting_resource_loot[res] += loot_amount

        # apply caps
        for kind, amounts in (('storage', self.storage_amounts), ('producer', self.producer_amounts)):
            for res in gamedata['resources']:
                factor = 1
                total_loot = sum([x[0] for x in amounts[res].itervalues()],0)
                total_lost = sum([x[1] for x in amounts[res].itervalues()],0)
                if attacker_caps[kind][res] >= 0 and total_loot > attacker_caps[kind][res]:
                    factor = min(factor, attacker_caps[kind][res] / float(total_loot))
                if defender_caps[kind][res] >= 0 and total_lost > defender_caps[kind][res]:
                    factor = min(factor, defender_caps[kind][res] / float(total_lost))
                if factor < 1:
                    # scale down all loot amounts to meet cap
                    for obj_id in amounts[res]:
                        old_loot, old_lost = amounts[res][obj_id]
                        amounts[res][obj_id] = (int(factor * old_loot + 0.5), int(factor * old_lost + 0.5))
                        # subtract delta from total lootable count
                        self.starting_resource_loot[res] -= (old_loot - amounts[res][obj_id][0])

        # cur_resource_loot will be decremented as the attacker loots resources, leaving starting_resource_loot alone
        self.cur_resource_loot = copy.deepcopy(self.starting_resource_loot)

    def send_update(self, retmsg):
        retmsg.append(["RES_LOOTER_UPDATE", {'starting': self.starting_resource_loot,
                                             # these can be sent to the client for debugging only
                                             # 'producer_amounts': self.producer_amounts,
                                             # 'storage_amounts': self.storage_amounts,
                                             'cur': copy.deepcopy(self.cur_resource_loot),
                                             'looted_uncapped': copy.deepcopy(self.total_looted_uncapped)}])

    def battle_summary_props(self):
        ret = BaseResLoot.battle_summary_props(self)
        ret['starting_base_resource_loot'] = self.starting_resource_loot
        return ret

    def do_loot_building(self, gamedata, session, obj, owning_player):
        looted = {}
        lost = {}

        if obj.is_storage():
            for res in gamedata['resources']:
                if obj.obj_id in self.storage_amounts[res]:
                    looted[res], lost[res] = self.storage_amounts[res][obj.obj_id]
                    del self.storage_amounts[res][obj.obj_id]

                    self.cur_resource_loot[res] -= looted[res]

                    # loot is taken directly from the owner's stored resources
                    owning_player.resources.gain_res(dict((res,-lost[res]) for res in lost), reason='looted_by_attacker')

        elif obj.is_producer():
            for res in gamedata['resources']:
                if obj.obj_id in self.producer_amounts[res]:
                    looted[res], lost[res] = self.producer_amounts[res][obj.obj_id]
                    del self.producer_amounts[res][obj.obj_id]

                    self.cur_resource_loot[res] -= looted[res]

                    # take from the uncollected resources inside the harvester
                    obj.contents -= lost[res]

        return looted, lost
