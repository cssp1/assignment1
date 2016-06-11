#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for resolving raid outcomes
# used by both maptool (for offline resolution) and server (for online resolution)

import copy, random
import Equipment

def get_leveled_quantity(qty, level): # XXX duplicate
    if type(qty) == list:
        return qty[level-1]
    return qty

# the following is cribbed from AutoResolve.py - but instead of working with live Player/GameObjects, they work with JSON structures

def item_affects_dps(item, gamedata):
    spec = gamedata['items'].get(item['spec'])
    if spec:
        if 'equip' in spec and 'effects' in spec['equip']:
            for effect in spec['equip']['effects']:
                if effect['code'] == 'modstat' and effect['stat'] in ('weapon','weapon_level'):
                    return True
    return False

def army_unit_equipment_key(unit, gamedata):
    if 'equipment' in unit:
        return '|'.join(sorted('%s_L%d' % (item['spec'], item.get('level',1)) \
                               for item in Equipment.Equipment.equip_iter(unit['equipment']) \
                               if item_affects_dps(item, gamedata)))
    return ''

# unique identifier for the DPS relationship between a shooter and target
def army_unit_pair_dps_key(shooter_unit, target_unit, gamedata):
    return '%d:%s:L%d:%s vs %d:%s:L%d:%s' % \
           (shooter_unit['owner_id'], shooter_unit['spec'], shooter_unit.get('level',1), army_unit_equipment_key(shooter_unit, gamedata),
            target_unit['owner_id'], target_unit['spec'], target_unit.get('level',1), army_unit_equipment_key(target_unit, gamedata))

def army_unit_pair_dph(shooter, target, gamedata,
                       shooter_power_factor = 1):
    if not army_unit_is_visible_to_enemy(target, gamedata):
        return 0 # invisible

    shooter_spec = army_unit_spec(shooter, gamedata)
    shooter_level = shooter.get('level',1)
    target_spec = army_unit_spec(target, gamedata)
    target_level = target.get('level',1)

    # XXX should this iterate on defense_types instead?
    shooter_keys = shooter_spec['defense_types']
    target_keys = target_spec['defense_types']

    # XXX or some type of building stat override for turret heads (apply to summary as well!)
    raid_offense = get_leveled_quantity(shooter_spec['raid_offense'], shooter_level)
    damage = 1
    for k in target_keys:
        damage *= get_leveled_quantity(raid_offense.get(k,1), shooter_level)

    if shooter_spec['kind'] == 'building' and shooter_power_factor < 1 and gamedata.get('enable_power'):
        min_fac = gamedata['minimum_combat_power_factor']
        damage *= min_fac + (1-min_fac) * shooter_power_factor

    damage_coeff_pre_armor = 1
    damage_coeff_post_armor = 1

    #damage_coeff_pre_armor *= shooter.owner.stattab.get_unit_stat(shooter.spec.name, 'weapon_damage', 1)
    #damage_coeff_post_armor *= target.owner.stattab.get_unit_stat(target.spec.name, 'damage_taken', 1)

    for k in target_keys:
        pass # damage_coeff_pre_armor *= shooter.owner.stattab.get_unit_stat(shooter.spec.name, 'weapon_damage_vs:%s' % k, 1)
    for k in shooter_keys:
        pass # damage_coeff_post_armor *= target.owner.stattab.get_unit_stat(target.spec.name, 'damage_taken_from:%s' % k, 1)

    damage *= damage_coeff_pre_armor

    armor = max(get_leveled_quantity(target_spec.get('armor',0), target_level), 0) # target.owner.stattab.get_unit_stat(target['spec'], 'armor', 0)
    if armor > 0: damage = max(1, damage - armor)

    damage *= damage_coeff_post_armor

    damage = max(1, int(damage + 0.5))

    damage *= shooter.get('stack',1) # XXX not a good way to handle stacks
    return damage

# utility functions that operate on "army unit" instances
# for the purposes of the Raids code, this can include buildings as well as mobile units.

def army_unit_is_scout(unit, gamedata):
    if unit['spec'] not in gamedata['units']: return False # might be a building
    spec = gamedata['units'][unit['spec']]
    if ('defense_types' in spec and 'scout' in spec['defense_types']):
        assert army_unit_is_raid_shooter(unit, gamedata) # check assumption that scout is subset of shooter
        return True
    return False

def army_unit_is_mobile(unit, gamedata):
    return unit['spec'] in gamedata['units']

def army_unit_is_consumable(unit, gamedata):
    if unit['spec'] in gamedata['units']:
        spec = gamedata['units'][unit['spec']]
        return spec.get('consumable',False)
    return False

def army_unit_spec(unit, gamedata):
    if unit['spec'] in gamedata['units']:
        return gamedata['units'][unit['spec']]
    elif unit['spec'] in gamedata['buildings']:
        return gamedata['buildings'][unit['spec']]
    raise Exception('spec not found: '+unit['spec'])

# true if unit has a nonzero raid_offense stat
def army_unit_is_raid_shooter(unit, gamedata):
    spec = army_unit_spec(unit, gamedata)
    level = unit.get('level',1)
    if 'raid_offense' in spec:
        raid_offense = get_leveled_quantity(spec['raid_offense'], level)
        for key in raid_offense:
            val = get_leveled_quantity(raid_offense[key], level)
            if val > 0:
                return True
    return False

def army_unit_is_visible_to_enemy(unit, gamedata):
    spec = army_unit_spec(unit, gamedata)
    return not spec.get('invisible', False) # note: ignore invis_on_hold

def army_unit_is_worth_less_xp(unit, gamedata):
    spec = army_unit_spec(unit, gamedata)
    return spec.get('worth_less_xp', False)

def army_unit_is_alive(unit, gamedata):
    if 'DELETED' in unit: return True # special case for these lists
    if 'hp' in unit and unit['hp'] <= 0: return False
    if 'hp_ratio' in unit and unit['hp_ratio'] <= 0: return False
    return True

def army_unit_hp(unit, gamedata):
    if 'DELETED' in unit: return 0
    if 'hp' in unit: return unit['hp']
    spec = army_unit_spec(unit, gamedata)
    max_hp = get_leveled_quantity(spec['max_hp'], unit.get('level',1))
    if 'hp_ratio' in unit: return int(unit['hp_ratio']*max_hp)
    return max_hp

def calc_max_cargo(unit_list, gamedata):
    max_cargo = {}
    for unit in unit_list:
        if army_unit_is_mobile(unit, gamedata) and army_unit_is_alive(unit, gamedata):
            level = unit.get('level',1)
            spec = gamedata['units'][unit['spec']]
            for res in gamedata['resources']:
                amount = get_leveled_quantity(spec.get('cargo_'+res,0), level)
                if amount > 0:
                    max_cargo[res] = max_cargo.get(res,0) + unit.get('stack',1) * amount
    return max_cargo

# scouting operates on a subset of the main unit list. When resolution finishes, we need
# to merge the updates to that subset with the original list of units in their original list positions.
# assumes that units in subset are ordered the same as they were in master.
def merge_unit_lists(subset, master):
    assert len(subset) <= len(master)
    ret = []
    i = s = 0
    for i, unit in enumerate(master):
        if len(subset) >= s+1 and subset[s]['obj_id'] == unit['obj_id']:
            # use the subset version
            ret.append(subset[s])
            s += 1
        else:
            # not in subset, use the master version
            ret.append(unit)
    return ret

def hurt_army_unit(unit, dmg, gamedata):
    # note: uses special DELETED convention
    level = unit.get('level',1)
    spec = army_unit_spec(unit, gamedata)

    old_hp = army_unit_hp(unit, gamedata)
    assert old_hp > 0

    new_hp = max(0, old_hp - dmg)
    if 'hp' in unit: del unit['hp']
    if new_hp <= 0:
        unit['hp_ratio'] = 0
    else:
        unit['hp_ratio'] = (new_hp + 0.9) / (1.0*get_leveled_quantity(spec['max_hp'], level))

    if new_hp <= 0:
        if spec['kind'] == 'building' or get_leveled_quantity(spec.get('resurrectable',False), level):
            pass # resurrectable
        else:
            unit['DELETED'] = 1

def resolve_raid_battle(attacking_units, defending_units, gamedata,
                        defending_power_factor = 1):
    # do not mutate attacking_units or defending_units. Return new unit lists instead.
    new_attacking_units = [copy.copy(x) for x in attacking_units]
    new_defending_units = [copy.copy(x) for x in defending_units]

    # list of just units that are still alive
    live_attacking_units = filter(lambda unit: army_unit_is_alive(unit, gamedata) and army_unit_is_raid_shooter(unit, gamedata),
                                  new_attacking_units)
    live_defending_units = filter(lambda unit: army_unit_is_alive(unit, gamedata) and army_unit_is_raid_shooter(unit, gamedata),
                                  new_defending_units)

    sides = [live_attacking_units, live_defending_units]

    # pre-compute damage per hit between every pair of possible shooters/targets
    dph_cache = {}
    dph_matrix = [[], # for each attacking unit, list of dph against each defending unit
                  []] # for each defending unit, list of dph against each attacking unit
    # so the indexing is dph_matrix[0][index_into_live_attacking_units][index_into_live_defending_units]
    #                 or dph_matrix[1][index_into_live_defending_units][index_into_live_attacking_units]
    for i, side in enumerate(sides):
        other_side = sides[1-i]
        for a, attacker in enumerate(side):
            dph_matrix[i].append([])
            for defender in other_side:
                dph_key = army_unit_pair_dps_key(attacker, defender, gamedata)
                if dph_key not in dph_cache:
                    dph_cache[dph_key] = army_unit_pair_dph(attacker, defender, gamedata,
                                                            shooter_power_factor = defending_power_factor if i == 1 else 1)
                dph_matrix[i][a].append(dph_cache[dph_key])

    if 0:
        print dph_cache
        print 'dph attacker', dph_matrix[0]
        print 'dph defender', dph_matrix[1]

    randgen = random.Random()

    iter = 0
    winner = 1 # defender wins by default if there is a stalemate

    while True:

        # check for win condition
        done = False
        for i in (0,1):
            if len(sides[i]) < 1:
                winner = 1-i
                done = True
                break
        if done: break

        # choose next shooter/target pair with uniform random probability
        # from all *nonzero* entries of dph_matrix
        # (if dph_matrix is all zero, we have a stalemate)
        # later, we could add some kind of weighing to simulate targeting
        pairs = []
        for s in (0,1):
            for i, row in enumerate(dph_matrix[s]):
                for j, entry in enumerate(row):
                    if entry > 0:
                        pairs.append((s, i, j)) # (side, index of shooter, index of target)
        if len(pairs) < 1:
            # stalemate - defender wins
            break

        s, i, j = randgen.choice(pairs)
        shooter = sides[s][i]
        target = sides[1-s][j]

        damage_done = dph_cache[army_unit_pair_dps_key(shooter, target, gamedata)]
        assert damage_done > 0

        #print shooter, 'shoots', target, 'for', damage_done

        hurt_army_unit(target, damage_done, gamedata)

        if not army_unit_is_alive(target, gamedata):
            # remove from list of live targets
            del sides[1-s][j]
            # remove from dph_matrix
            del dph_matrix[1-s][j] # entry with target as attacker
            for row in dph_matrix[s]: # entries with target as defender
                del row[j]

        iter += 1
        if iter >= 9999:
            raise Exception('runaway iteration')

    # destroy all remaining units on the losing side (including non-shooters)
    if winner is 0:
        losing_side = new_defending_units
    else:
        losing_side = new_attacking_units
    for unit in losing_side:
        if army_unit_is_alive(unit, gamedata):
            hurt_army_unit(unit, 99999999, gamedata)

    return (winner is 0), new_attacking_units, new_defending_units

# XXXXXXRAIDGUARDS
def resolve_raid(squad_feature, raid_feature, squad_units, raid_units, gamedata,
                 raid_power_factor = 1):
    # * assumes that you already have all the proper mutex locks on squad and raid!
    # returns (update_map_feature) mutations of squad, raid, loot
    assert squad_feature['base_type'] == 'squad' and squad_feature.get('raid')
    assert raid_feature['base_type'] in ('raid','home')

    raid_mode = squad_feature['raid']
    assert raid_mode in ('pickup','attack','defend','scout')

    max_cargo = squad_feature.get('max_cargo', {})
    cur_cargo = squad_feature.get('cargo', {})

    squad_update = {}
    raid_update = {}
    loot = {}

    is_win = False

    # complete replacements for the input unit lists
    # any unit that dies should have 'hp_ratio':0 if resurrectable, or 'DELETED': 1 if not
    # if None, then there is no change
    new_squad_units = None
    new_raid_units = None

    attacking_units = filter(lambda unit: army_unit_is_alive(unit, gamedata), squad_units)
    defending_units = filter(lambda unit: army_unit_is_alive(unit, gamedata), raid_units)

    # scouting
    if raid_mode == 'scout':
        # add something here just to trigger a mutation
        squad_update['scouted'] = 1

        # filter out non-scout units
        attacking_units = filter(lambda unit: army_unit_is_scout(unit, gamedata), attacking_units)
        defending_units = filter(lambda unit: army_unit_is_scout(unit, gamedata), defending_units)

    if attacking_units: # there have to be attacking units for anything to happen

        if defending_units:
            is_win, new_squad_units, new_raid_units = \
                    resolve_raid_battle(attacking_units, defending_units, gamedata,
                                        defending_power_factor = raid_power_factor)

            # add back the pass-through units at their correct positions in the unit lists
            if new_squad_units is not None: new_squad_units = merge_unit_lists(new_squad_units, squad_units)
            if new_raid_units is not None: new_raid_units = merge_unit_lists(new_raid_units, raid_units)

        else:
            is_win = True

        # handle disposable units here
        if any(army_unit_is_consumable(unit, gamedata) for unit in attacking_units):
            if new_squad_units is None:
                new_squad_units = [copy.copy(x) for x in attacking_units]
            for unit in new_squad_units:
                if (raid_mode != 'scout' or army_unit_is_scout(unit, gamedata)) and army_unit_is_consumable(unit, gamedata):
                    unit['DELETED'] = 1

        # recalculate max_cargo here, and clip cargo to it
        if new_squad_units is not None:
            max_cargo = calc_max_cargo(new_squad_units, gamedata)
            cur_cargo = dict((res, max(cur_cargo.get(res,0), max_cargo.get(res,0))) for res in cur_cargo)
            squad_update['max_cargo'] = max_cargo
            squad_update['cargo'] = cur_cargo

        # looting
        if is_win and raid_mode != 'scout':
            base_resource_loot = raid_feature.get('base_resource_loot', {})

            for res in base_resource_loot:
                if (base_resource_loot[res] > 0) and (res in max_cargo) and (cur_cargo.get(res,0) < max_cargo[res]):
                    amount = min(base_resource_loot[res], max_cargo[res] - cur_cargo.get(res,0))
                    base_resource_loot[res] -= amount
                    cur_cargo[res] = cur_cargo.get(res,0) + amount
                    loot[res] = amount

                    # apply mutated versions
                    raid_update['base_resource_loot'] = base_resource_loot
                    if 'base_times_attacked' not in raid_update:
                        raid_update['base_times_attacked'] = raid_feature.get('base_times_attacked',0) + 1
                    squad_update['cargo'] = cur_cargo
                    squad_update['cargo_source'] = 'raid'

            if sum(base_resource_loot.itervalues(), 0) < 1:
                # nothing more to loot - delete the raid site
                raid_update = None

    return squad_update, raid_update, loot, is_win, new_squad_units, new_raid_units

# reverse a base_map_path with a new start time
def backtrack_path(path, time_now):
    cur_eta = time_now
    ret = []
    for i, step in enumerate(reversed(path)):
        ret.append({'xy': step['xy'], 'eta': cur_eta})
        if i < len(path) - 1:
            cur_eta += step['eta'] - path[-(i+2)]['eta']
    return ret

# return a (move_map_feature) mutation that sends a squad back along its current base_map_path
def backtrack(squad_feature, time_now):
    if 'base_map_path' not in squad_feature or \
       len(squad_feature['base_map_path']) < 1 or \
       squad_feature['base_map_path'][-1]['xy'] != squad_feature['base_map_loc']:
        raise Exception('missing or invalid base_map_path on squad %s' % squad_feature['base_id'])

    home_path = backtrack_path(squad_feature['base_map_path'], time_now)
    home_loc = home_path[-1]['xy']
    return {'base_map_loc': home_loc,
            'base_map_path': home_path}

# below has dependencies on SpinNoSQL and ChatChannels stuff; above does not
import SpinConfig

# online function to resolve action of a list of raid squads vs. a single raid target
# intended to be usable both by server and maptool
# intended to be self-contained with respect to locking and logging
# this assumes that the nosql_client you provide has been set up with hooks to properly broadcast map updates
# *mutates raid_squads* on the way out

def resolve_target(gamedata, nosql_client, chat_mgr, lock_manager, region_id, raid, raid_squads, time_now, recall_squads = True, dry_run = False):
    # for proper resolution ordering, sort by arrival time, earliest first
    raid_squads.sort(key = lambda squad: squad['base_map_path'][-1]['eta'] if 'base_map_path' in squad else -1)

    for squad in raid_squads:
        owner_id, squad_id = map(int, squad['base_id'][1:].split('_'))
        assert squad['base_landlord_id'] == owner_id
        if not raid: break # target doesn't exist anymore
        if raid['base_landlord_id'] == owner_id: break # target is actually owned by same player as squad - not eligible to raid it
        assert raid['base_type'] == 'raid' # home base attacks handled in a separate path

        squad_lock = lock_manager.acquire(region_id, squad['base_id'])
        raid_lock = lock_manager.acquire(region_id, raid['base_id'])
        if not (squad_lock and raid_lock):
            continue # XXX could not lock both squad and raid
        try:
            raid_units = nosql_client.get_mobile_objects_by_base(region_id, raid['base_id']) + \
                         nosql_client.get_fixed_objects_by_base(region_id, raid['base_id'])
            squad_units = nosql_client.get_mobile_objects_by_base(region_id, squad['base_id'])

            squad_update, raid_update, loot, is_win, new_squad_units, new_raid_units = \
                          resolve_raid(squad, raid, squad_units, raid_units, gamedata)

            if squad_update or raid_update or (raid_update is None):
                # metrics - keep in sync between Raid.py and maptool.py implementations!

                # query player_cache for metadata on the attacker and
                # defender. Not absolutely 100% guaranteed to be up to date with
                # online server data, but close enough.
                attacker_pcinfo, defender_pcinfo = nosql_client.player_cache_lookup_batch([owner_id, raid['base_landlord_id']], reason = 'resolve_target')

                summary = make_battle_summary(gamedata, nosql_client, time_now, region_id, squad, raid,
                                              squad['base_landlord_id'], raid['base_landlord_id'],
                                              attacker_pcinfo, defender_pcinfo,
                                              squad.get('player_auras',[]), [], # assume no defender auras
                                              squad.get('player_tech',{}), {}, # assume no defender tech
                                              'victory' if is_win else 'defeat', 'defeat' if is_win else 'victory',
                                              squad_units, raid_units,
                                              new_squad_units, new_raid_units,
                                              loot, raid_mode = squad['raid'])
                if not dry_run:
                    nosql_client.battle_record(summary, reason = 'resolve_target')

                    # broadcast map attack for GUI and battle history jewel purposes
                    if chat_mgr:
                        chat_mgr.send('CONTROL', None, {'secret':SpinConfig.config['proxy_api_secret'],
                                                        'server':'Raid.py',
                                                        'method':'broadcast_map_attack',
                                                        'args': { 'msg': "REGION_MAP_ATTACK_COMPLETE",
                                                                  'region_id': region_id, 'feature': raid,
                                                                  'attacker_id': owner_id, 'defender_id': raid['base_landlord_id'],
                                                                  'summary': {'battle_type':'raid', 'raid_mode': squad['raid'], 'defender_outcome': summary['defender_outcome']}, # not full summary,
                                                                  'pcache_info': [attacker_pcinfo, defender_pcinfo],
                                                                  # note: time is boxed here in "args" since it refers to the region map update time,
                                                                  # which could conceivably be on a different clock than the chat message time
                                                                  'map_time': time_now,
                                                                  'server': 'Raid.py' },
                                                        }, '', log = False)
            if raid_update is None:
                # clear the raid
                if not dry_run:
                    nosql_client.drop_all_objects_by_base(region_id, raid['base_id'])
                    nosql_client.drop_map_feature(region_id, raid['base_id'])
                    lock_manager.forget(region_id, raid['base_id'])
                raid = raid_lock = None # target doesn't exist anymore
            elif raid_update:
                raid.update(raid_update)
                if not dry_run:
                    nosql_client.update_map_feature(region_id, raid['base_id'], raid_update)

            if squad_update:
                squad.update(squad_update)
                if not dry_run:
                    nosql_client.update_map_feature(region_id, squad['base_id'], squad_update)

            # XXX snap dead raids back to home?

            # handle unit damage updates
            # note: client should ping squads to get the army update
            for new_units in (new_squad_units, new_raid_units):
                if new_units is None: continue # no update
                mobile_deletions = [unit for unit in new_units if army_unit_is_mobile(unit, gamedata) and unit.get('DELETED')]
                mobile_updates = [unit for unit in new_units if army_unit_is_mobile(unit, gamedata) and not unit.get('DELETED')]
                fixed_deletions = [unit for unit in new_units if not army_unit_is_mobile(unit, gamedata) and unit.get('DELETED')]
                fixed_updates = [unit for unit in new_units if not army_unit_is_mobile(unit, gamedata) and not unit.get('DELETED')]

                for unit in mobile_deletions: nosql_client.drop_mobile_object_by_id(region_id, unit['obj_id'], reason = 'resolve_target')
                for unit in fixed_deletions: nosql_client.drop_fixed_object_by_id(region_id, unit['obj_id'], reason = 'resolve_target')
                if fixed_updates: nosql_client.save_fixed_objects(region_id, fixed_updates, reason = 'resolve_target')
                if mobile_updates: nosql_client.save_mobile_objects(region_id, mobile_updates, reason = 'resolve_target')

            if recall_squads:
                # send the squad towards home
                try:
                    recall_squad(nosql_client, region_id, squad, time_now, dry_run = dry_run)
                except RecallSquadException:
                    continue

        finally:
            if squad_lock: lock_manager.release(region_id, squad['base_id'])
            if raid_lock: lock_manager.release(region_id, raid['base_id'])

    return raid # return updated target (possibly None)

class RecallSquadException(Exception): pass

# send a squad back towards home
# *ASSUMES LOCK IS HELD*
def recall_squad(nosql_client, region_id, squad, time_now, dry_run = False):
    home = nosql_client.get_map_feature_by_base_id(region_id, 'h'+str(squad['base_landlord_id']))
    if not home:
        raise RecallSquadException('in %s, cannot recall squad squad %s - home base not found' % (region_id, squad['base_id']))

    if 'base_map_path' in squad and squad['base_map_path'][0]['xy'] == home['base_map_loc']:
        # good backtrack path
        path_update = backtrack(squad, time_now)
    else:
        raise RecallSquadException('in %s, cannot recall squad squad %s - path not back-trackable to home base' % (region_id, squad['base_id']))

    if not dry_run:
        nosql_client.move_map_feature(region_id, squad['base_id'], path_update,
                                      old_loc = squad['base_map_loc'], old_path=squad.get('base_map_path',None),
                                      exclusive = -1, reason = 'resolve_target')

def get_denormalized_summary_props_from_pcache(gamedata, pcinfo):
    ret = {'cc': pcinfo.get(gamedata['townhall']+'_level',1),
           'plat' : pcinfo.get('social_id','fb')[0:2],
           'rcpt': pcinfo.get('money_spent', 0),
           'ct': pcinfo.get('country','unknown'),
           'tier': pcinfo.get('country_tier', SpinConfig.country_tier_map.get(pcinfo.get('country','unknown'), 4))}
    if pcinfo.get('developer', False):
        ret['developer'] = 1
    return ret

# construct a battle summary for a raid resolution, compatible with the format
# expected by RTS battle logging.
def make_battle_summary(gamedata, nosql_client,
                        time_now, region_id, squad, base,
                        attacker_id, defender_id,
                        attacker_pcinfo, defender_pcinfo,
                        attacker_player_auras, defender_player_auras,
                        attacker_tech, defender_tech,
                        attacker_outcome, defender_outcome,
                        # object state lists
                        attacker_units_before, defender_units_before,
                        attacker_units_after, defender_units_after,
                        loot, raid_mode = None, base_damage = None, is_revenge = False):
    ret = {'time' : time_now,
           'base_region' : region_id,
           'base_map_loc' : base['base_map_loc'],
           'base_type' : base['base_type'],
           'base_ui_name' : base.get('base_ui_name','Unknown'),
           'base_id' : base['base_id'],
           'base_creation_time' : base.get('base_creation_time',-1),
           'base_expire_time' : base.get('base_expire_time',-1),
           'base_times_attacked' : base.get('base_times_attacked',0)+1, # not updated yet
           #'starting_base_damage': 0, 'base_damage': 0,

           'involved_players' : [ attacker_id, defender_id ],
           'deployable_squads' : [ squad['base_id'], ],

           'battle_type' : 'raid',
           'raid_mode': raid_mode,
           'home_base' : 1 if base['base_id'][0] == 'h' else 0,
           'attacker_outcome': attacker_outcome,
           'defender_outcome': defender_outcome,
           }
    if base_damage is not None:
        ret['base_damage'] = base_damage
    if is_revenge:
        ret['is_revenge'] = is_revenge
    if base.get('base_template'):
        ret['base_template'] = base['base_template']

    if attacker_player_auras: ret['attacker_auras'] = attacker_player_auras
    if defender_player_auras: ret['defender_auras'] = defender_player_auras
    if attacker_tech: ret['attacker_tech'] = attacker_tech
    if defender_tech: ret['defender_tech'] = defender_tech

    for dic_name, unit_list in (('deployed_units', attacker_units_before),
                                ('defending_units', defender_units_before)):
        live_unit_list = filter(lambda unit: (raid_mode != 'scout' or army_unit_is_scout(unit, gamedata)) and \
                                army_unit_is_raid_shooter(unit, gamedata) and \
                                army_unit_is_alive(unit, gamedata) and \
                                not army_unit_is_worth_less_xp(unit, gamedata), unit_list)
        if live_unit_list:
            ret[dic_name] = {}
            for unit in live_unit_list:
                ret[dic_name][unit['spec']] = ret[dic_name].get(unit['spec'],0) + unit.get('stack',1)

    # record remaining strength of defender
    # unless you lost a scout attempt
    defender_units_now = defender_units_after if (defender_units_after is not None) else defender_units_before
    if (raid_mode != 'scout' or attacker_outcome == 'victory') and (defender_units_now is not None) and (raid_mode != 'pickup'):
        ret['new_raid_offense'] = {}
        ret['new_raid_defense'] = {}
        ret['new_raid_hp'] = {}
        ret['new_raid_space'] = {}

        for obj in defender_units_now:
            if obj['spec'] in gamedata['units']:
                spec = gamedata['units'][obj['spec']]
            elif obj['spec'] in gamedata['buildings']:
                spec = gamedata['buildings'][obj['spec']]
            else:
                continue
            stack = obj.get('stack', 1)
            level = obj.get('level', 1)
            hp = army_unit_hp(obj, gamedata)
            hp_ratio = hp / get_leveled_quantity(spec['max_hp'], level)

            if 'raid_offense' in spec or 'raid_defense' in spec:
                for key in spec['defense_types']:
                    total_hp = hp * stack
                    if total_hp > 0:
                        ret['new_raid_hp'][key] = ret['new_raid_hp'].get(key,0) + total_hp
                    if 'consumes_space' in spec:
                        total_space = stack * get_leveled_quantity(spec['consumes_space'], level)
                        total_space *= hp_ratio # ??
                        if total_space > 0:
                            ret['new_raid_space'][key] = ret['new_raid_space'].get(key,0) + total_space

            for kind in ('raid_offense', 'raid_defense'):
                if kind in spec:
                    val = get_leveled_quantity(spec[kind], level)
                    for k, v in val.iteritems():
                        v = get_leveled_quantity(v, level)
                        v = stack * hp_ratio * v # ??
                        if v > 0:
                            ret['new_'+kind][k] = ret['new_'+kind].get(k,0) + v

    ret['loot'] = copy.copy(loot) # don't mutate caller's loot
    if 'xp' not in ret['loot']:
        ret['loot']['xp'] = 0

    # add damage stats to loot
    for role, user_id, before, after in (('attacker', attacker_id, attacker_units_before, attacker_units_after),
                                         ('defender', defender_id, defender_units_before, defender_units_after)):
        if after is None: continue # no delta
        assert len(before) == len(after)

        if 'damage' not in ret: ret['damage'] = {}
        my_damage = ret['damage'][str(user_id)] = {}

        for b, a in zip(before, after):
            if b['spec'] in gamedata['units']:
                spec = gamedata['units'][b['spec']]
            elif b['spec'] in gamedata['buildings']:
                spec = gamedata['buildings'][b['spec']]
            else:
                continue
            if b.get('DELETED'): continue # unit was dead at start of battle

            level = b.get('level',1)
            max_hp = get_leveled_quantity(spec['max_hp'], level)
            before_hp = b['hp'] if 'hp' in b else int(b.get('hp_ratio',1)*max_hp)
            after_hp = 0 if a.get('DELETED') else (a['hp'] if 'hp' in a else int(a.get('hp_ratio',1)*max_hp))

            if after_hp < before_hp:
                if role == 'defender':
                    ret['loot']['damage_inflicted'] = ret['loot'].get('damage_inflicted',0) + (before_hp - after_hp)

                    # evaluate havoc
                    if spec['kind'] == 'building' and before_hp >= max_hp and (not spec.get('worth_less_xp')):
                        if b.get('build_start_time',-1) > 0 or \
                           b.get('research_start_time',-1) > 0 or \
                           b.get('upgrade_start_time',-1) > 0 or \
                           b.get('enhance_start_time',-1) > 0 or \
                           b.get('manuf_start_time',-1) > 0 or \
                           ('crafting' in b and 'queue' in b['crafting'] and any(bus.get('start_time',-1) > 0 for bus in b['crafting']['queue'])):
                           ret['loot']['havoc_caused'] = ret['loot'].get('havoc_caused',0) + 1

                if spec['kind'] == 'mobile':
                    full_cost = dict((res, int((gamedata['unit_repair_resources'] if spec.get('resurrectable') else 1) * get_leveled_quantity(spec.get('build_cost_'+res,0), level))) for res in gamedata['resources'])
                    full_time = int((gamedata['unit_repair_time'] if spec.get('resurrectable') else 1) * get_leveled_quantity(spec.get('build_time',0), level))
                elif spec['kind'] == 'building':
                    full_cost = {} # buildings do not cost resources to repair
                    full_time = int(get_leveled_quantity(spec.get('repair_time',0), level))

                # 'damage' accounting for ROI metrics
                damage_key = b['spec']+(':L%d' % level)
                if damage_key not in my_damage: my_damage[damage_key] = {}
                my_damage[damage_key]['count'] = my_damage[damage_key].get('count',0) + 1

                for res in full_cost:
                    part_cost = int((before_hp - after_hp)/(1.0*max_hp) * full_cost[res])
                    if part_cost > 0:
                        my_damage[damage_key][res] = my_damage[damage_key].get(res,0) + part_cost

                part_time = int((before_hp - after_hp)/(1.0*max_hp) * full_time)
                if part_time > 0:
                    my_damage[damage_key]['time'] = my_damage[damage_key].get('time',0) + part_time

                # units_lost_* accounting for destroyed units (not buildings)
                if after_hp <= 0 and spec['kind'] in ('mobile', 'building'):
                    adj = 'lost' if role == 'attacker' else 'killed'
                    key = {'mobile': 'units', 'building': 'buildings'}[spec['kind']] + '_' + adj
                    if key not in ret['loot']:
                        ret['loot'][key] = {}
                    ret['loot'][key][b['spec']] = ret['loot'][key].get(b['spec'],0) + 1

                    if full_cost:
                        for res in full_cost:
                            if full_cost[res] > 0:
                                ret['loot'][key+'_'+res] = ret['loot'].get(key+'_'+res,0) + full_cost[res]

    for role, user_id, pcinfo in (('attacker', attacker_id, attacker_pcinfo), ('defender', defender_id, defender_pcinfo)):
        is_ai = 0 if user_id > 1100 else 1 # XXX really need to fix this sometime
        ret.update({role+'_id': user_id,
                    role+'_type': 'ai' if is_ai else 'human',
                    role+'_is_ai': is_ai,
                    role+'_level': pcinfo.get('player_level', 1),
                    role+'_townhall_level': pcinfo.get(gamedata['townhall']+'_level', 1),
                    role+'_name': pcinfo.get('ui_name', 'Unknown'),
                    role+'_social_id': pcinfo.get('social_id', '-1')})
        if not is_ai:
            ret.update({role+'_home_base_loc': pcinfo.get('home_base_loc', None),
                        role+'_summary': get_denormalized_summary_props_from_pcache(gamedata, pcinfo)
                        })
            if pcinfo.get('alliance_id',-1) >= 0:
                alliance_id = pcinfo['alliance_id']
                alinfo = nosql_client.get_alliance_info(alliance_id, reason = 'Raid.make_battle_summary')
                if alinfo:
                    ret.update({role+'_alliance_id': alliance_id,
                                role+'_alliance_ui_name': alinfo['ui_name'],
                                role+'_alliance_chat_tag': alinfo.get('chat_tag')})
    return ret

if __name__ == '__main__':
    # test code
    test_path = [{'xy':[0,0],'eta':0},
                 {'xy':[1,1],'eta':1},
                 {'xy':[2,2],'eta':3},
                 {'xy':[3,3],'eta':4}]
    print '\n'.join(repr(x) for x in test_path)
    print '\n'.join(repr(x) for x in backtrack_path(test_path, 10))
