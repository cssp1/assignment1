#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for resolving raid outcomes
# used by both maptool (for offline resolution) and server (for online resolution)

import copy, random

def get_leveled_quantity(qty, level): # XXX duplicate
    if type(qty) == list:
        return qty[level-1]
    return qty

def is_scout_unit(unit, gamedata):
    if unit['spec'] not in gamedata['units']: return False # might be a building
    spec = gamedata['units'][unit['spec']]
    if 'raid_offense' in spec:
        val = get_leveled_quantity(spec['raid_offense'], unit.get('level',1))
        if val and 'scout' in val:
            return True
    return False

def army_unit_is_mobile(unit, gamedata):
    return unit['spec'] in gamedata['units']

# true if unit has a nonzero raid_offense stat other than scouting
def army_unit_is_raid_shooter(unit, gamedata):
    if unit['spec'] in gamedata['units']:
        spec = gamedata['units'][unit['spec']]
        if 'raid_offense' in spec:
            raid_offense = get_leveled_quantity(spec['raid_offense'], 1)
            for key in raid_offense:
                if key != 'scout':
                    return True
    return False

def army_unit_is_alive(unit, gamedata):
    if 'DELETED' in unit: return True # special case for these lists
    if 'hp' in unit and unit['hp'] <= 0: return False
    if 'hp_ratio' in unit and unit['hp_ratio'] <= 0: return False
    return True

def army_unit_hp(unit, gamedata):
    if 'DELETED' in unit: return 0
    if 'hp' in unit: return unit['hp']
    max_hp = get_leveled_quantity(gamedata['units'][unit['spec']]['max_hp'], unit.get('level',1))
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
        if subset[s]['obj_id'] == unit['obj_id']:
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
    spec = gamedata['units'][unit['spec']]

    old_hp = army_unit_hp(unit, gamedata)
    assert old_hp > 0

    new_hp = max(0, old_hp - dmg)
    if 'hp' in unit: del unit['hp']
    unit['hp_ratio'] = new_hp / (1.0*get_leveled_quantity(spec['max_hp'], level))

    if new_hp <= 0:
        if get_leveled_quantity(spec.get('resurrectable',False), level):
            pass # resurrectable
        else:
            unit['DELETED'] = 1

def resolve_raid_battle(attacking_units, defending_units, gamedata):
    # do not mutate attacking_units or defending_units. Return new unit lists instead.
    new_attacking_units = [copy.copy(x) for x in attacking_units]
    new_defending_units = [copy.copy(x) for x in defending_units]

    # list of just units that are still alive
    live_attacking_units = filter(lambda unit: army_unit_is_alive(unit, gamedata) and army_unit_is_raid_shooter(unit, gamedata),
                                  new_attacking_units)
    live_defending_units = filter(lambda unit: army_unit_is_alive(unit, gamedata) and army_unit_is_raid_shooter(unit, gamedata),
                                  new_defending_units)

    randgen = random.Random()

    sides = [live_attacking_units, live_defending_units]
    iter = 0
    winner = 1 # defender wins by default if there is a stalemate

    first_shooter = randgen.choice([0,1])
    randomness = 0.4
    random_streak = -1
    random_streak_side = -1

    while True:

        # pick side to shoot
        if random_streak > 0:
            i = random_streak_side
            random_streak -= 1
        else:
            i = first_shooter ^ (iter % 2) # alternate sides

            # to add randomness to battles, sometimes allow one side to shoot consecutively
            # a few times (just randomizing the shooter on each iteration doesn't disturb outcomes enough)
            if randomness > 0 and randgen.random() > randomness:
                random_streak = 5
                random_streak_side = i

        offense = sides[i]
        defense = sides[1-i]

        if len(defense) < 1:
            winner = i; break
        elif len(offense) < 1:
            winner = 1-i; break

        shooter = randgen.choice(offense)
        target = randgen.choice(defense)

        shooter_spec = gamedata['units'][shooter['spec']]
        shooter_level = shooter.get('level',1)
        target_spec = gamedata['units'][target['spec']]
        #target_level = target.get('level',1)

        #print shooter, 'shoots', target

        coeff = 1
        raid_offense = get_leveled_quantity(shooter_spec['raid_offense'], shooter_level)
        assert target_spec['manufacture_category'] in raid_offense
        coeff *= get_leveled_quantity(raid_offense[target_spec['manufacture_category']], shooter_level)
        coeff = int(coeff)
        assert coeff > 0

        hurt_army_unit(target, coeff, gamedata)

        if not army_unit_is_alive(target, gamedata):
            # remove from list of live targets
            defense.remove(target)

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

def resolve_raid(squad_feature, raid_feature, squad_units, raid_units, gamedata):
    # * assumes that you already have all the proper mutex locks on squad and raid!
    # returns (update_map_feature) mutations of squad, raid, loot
    assert squad_feature['base_type'] == 'squad' and squad_feature.get('raid')
    assert raid_feature['base_type'] == 'raid'

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

    attacking_units = squad_units[:]
    defending_units = raid_units[:]

    # scouting
    if raid_mode == 'scout':
        # add something here just to trigger a mutation
        squad_update['scouted'] = 1

        # filter out non-scout units
        attacking_units = filter(lambda unit: is_scout_unit(unit, gamedata), attacking_units)
        defending_units = filter(lambda unit: is_scout_unit(unit, gamedata), defending_units)

    if attacking_units: # there have to be attacking units for anything to happen

        if defending_units:
            is_win, new_squad_units, new_raid_units = \
                    resolve_raid_battle(attacking_units, defending_units, gamedata)

            if raid_mode == 'scout':
                # add back the non-scout units at their correct positions in the unit lists
                if new_squad_units is not None: new_squad_units = merge_unit_lists(new_squad_units, squad_units)
                if new_raid_units is not None: new_raid_units = merge_unit_lists(new_raid_units, raid_units)

            if new_squad_units is not None:
                # recalculate max_cargo here, and clip cargo to it
                max_cargo = calc_max_cargo(new_squad_units, gamedata)
                cur_cargo = dict((res, max(cur_cargo.get(res,0), max_cargo.get(res,0))) for res in cur_cargo)
                squad_update['max_cargo'] = max_cargo
                squad_update['cargo'] = cur_cargo

        else:
            is_win = True

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

# online function for resolving action at a map hex
# intended to be usable both by server and maptool
# intended to be self-contained with respect to locking and logging
# this assumes that the nosql_client you provide has been set up with hooks to properly broadcast map updates
def resolve_loc(gamedata, nosql_client, chat_mgr, lock_manager, region_id, loc, time_now, dry_run = False):
    features = nosql_client.get_map_features_by_loc(region_id, loc)
    # filter out not-arrived-yet moving features (use strict time comparison)
    features = filter(lambda feature: ('base_map_path' not in feature) or \
                      feature['base_map_path'][-1]['eta'] < time_now, features)
    raid_squads = filter(lambda feature: feature['base_type'] == 'squad' and feature.get('raid'), features)
    if not raid_squads: return # no raids to process

    targets = filter(lambda x: x['base_type'] == 'raid', features)
    if not targets: return # no targets to process
    raid = targets[0] # select first target

    resolve_target(gamedata, nosql_client, chat_mgr, lock_manager, region_id, raid, raid_squads, time_now, dry_run = dry_run)

# resolve action of a list of raid squads vs. a single raid target
# *mutates raid_squads* on the way out
def resolve_target(gamedata, nosql_client, chat_mgr, lock_manager, region_id, raid, raid_squads, time_now, recall_squads = True, dry_run = False):
    # for proper resolution ordering, sort by arrival time, earliest first
    raid_squads.sort(key = lambda squad: squad['base_map_path'][-1]['eta'] if 'base_map_path' in squad else -1)

    for squad in raid_squads:
        owner_id, squad_id = map(int, squad['base_id'][1:].split('_'))
        assert squad['base_landlord_id'] == owner_id
        if not raid: break # target doesn't exist anymore

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
                attacker_pcinfo, defender_pcinfo = nosql_client.player_cache_lookup_batch([owner_id, raid['base_landlord_id']], reason = 'Raid.resolve_loc')

                summary = make_battle_summary(gamedata, nosql_client, time_now, region_id, squad, raid,
                                              squad['base_landlord_id'], raid['base_landlord_id'],
                                              attacker_pcinfo, defender_pcinfo,
                                              'victory' if is_win else 'defeat', 'defeat' if is_win else 'victory',
                                              squad_units, raid_units,
                                              new_squad_units, new_raid_units,
                                              loot, raid_mode = squad['raid'])
                if not dry_run:
                    nosql_client.battle_record(summary, reason = 'Raid.resolve_loc')

                    # broadcast map attack for GUI and battle history jewel purposes
                    if chat_mgr:
                        chat_mgr.send('CONTROL', None, {'secret':SpinConfig.config['proxy_api_secret'],
                                                        'server':'Raid.py',
                                                        'method':'broadcast_map_attack',
                                                        'args': { 'msg': "REGION_MAP_ATTACK_COMPLETE",
                                                                  'region_id': region_id, 'feature': raid,
                                                                  'attacker_id': owner_id, 'defender_id': raid['base_landlord_id'],
                                                                  'summary': summary, 'pcache_info': [attacker_pcinfo, defender_pcinfo],
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

                for unit in mobile_deletions: nosql_client.drop_mobile_object_by_id(region_id, unit['obj_id'], reason = 'resolve_loc')
                for unit in fixed_deletions: nosql_client.drop_fixed_object_by_id(region_id, unit['obj_id'], reason = 'resolve_loc')
                if fixed_updates: nosql_client.save_fixed_objects(region_id, fixed_updates, reason = 'resolve_loc')
                if mobile_updates: nosql_client.save_mobile_objects(region_id, mobile_updates, reason = 'resolve_loc')

            if recall_squads:
                # send the squad towards home
                home = nosql_client.get_map_feature_by_base_id(region_id, 'h'+str(owner_id))
                if not home:
                    continue # XXX squad's home base not found on map

                if 'base_map_path' in squad and squad['base_map_path'][0]['xy'] == home['base_map_loc']:
                    # good backtrack path
                    path_update = backtrack(squad, time_now)
                else:
                    continue # XXX no path found to home base
                if not dry_run:
                    nosql_client.move_map_feature(region_id, squad['base_id'], path_update,
                                                  old_loc = squad['base_map_loc'], old_path=squad.get('base_map_path',None),
                                                  exclusive = -1, reason = 'resolve_loc')

        finally:
            if squad_lock: lock_manager.release(region_id, squad['base_id'])
            if raid_lock: lock_manager.release(region_id, raid['base_id'])

    return raid # return updated target (possibly None)

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
                        attacker_outcome, defender_outcome,
                        # object state lists
                        attacker_units_before, defender_units_before,
                        attacker_units_after, defender_units_after,
                        loot, raid_mode = None):
    ret = {'time' : time_now,
           'base_region' : region_id,
           'base_map_loc' : base['base_map_loc'],
           'base_type' : base['base_type'],
           'base_template' : base.get('base_template'),
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
           'home_base' : True if base['base_id'][0] == 'h' else False,
           'attacker_outcome': attacker_outcome,
           'defender_outcome': defender_outcome,
           }

    ret['deployed_units'] = {}
    for obj in attacker_units_before:
        if raid_mode == 'scout' and is_scout_unit(obj, gamedata): continue
        ret['deployed_units'][obj['spec']] = ret['deployed_units'].get(obj['spec'],0) + 1

    # record remaining strength of defender
    # unless you lost a scout attempt
    if (raid_mode != 'scout' or attacker_outcome == 'victory') and (defender_units_after is not None) and (raid_mode != 'pickup'):
        ret['new_raid_offense'] = {}
        ret['new_raid_defense'] = {}

        for obj in defender_units_after:
            if obj['spec'] in gamedata['units']:
                spec = gamedata['units'][obj['spec']]
            elif obj['spec'] in gamedata['buildings']:
                spec = gamedata['buildings'][obj['spec']]
            else:
                continue
            stack = obj.get('stack', 1)
            level = obj.get('level', 1)
            hp_ratio = obj.get('hp_ratio', 1)
            for kind in ('raid_offense', 'raid_defense'):
                if kind in spec:
                    val = get_leveled_quantity(spec[kind], level)
                    for k, v in val.iteritems():
                        v = get_leveled_quantity(v, level)
                        v = stack * hp_ratio * v # ??
                        if v > 0:
                            if ('new_'+kind) not in ret: ret['new_'+kind] = {}
                            ret['new_'+kind][k] = ret['new_'+kind].get(k,0) + v

    ret['loot'] = copy.copy(loot) # don't mutate caller's loot

    # add damage stats to loot
    for role, user_id, before, after in (('attacker', attacker_id, attacker_units_before, attacker_units_after),
                                         ('defender', defender_id, defender_units_before, defender_units_after)):
        if after is None: continue # no delta
        assert len(before) == len(after)

        ret['loot']['xp'] = 0 # no XP
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

                if spec['kind'] == 'mobile':
                    full_cost = dict((res, int((gamedata['unit_repair_resources'] if spec.get('resurrectable') else 1) * get_leveled_quantity(spec.get('build_cost_'+res,0), level))) for res in gamedata['resources'])
                    full_time = int((gamedata['unit_repair_time'] if spec.get('resurrectable') else 1) * get_leveled_quantity(spec.get('build_time',0), level))
                else:
                    full_cost = {} # buildings do not cost resources to repair
                    full_time = int(spec.get('repair_time',0))

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
                if after_hp <= 0 and spec['kind'] == 'mobile':
                    adj = 'lost' if role == 'attacker' else 'killed'
                    if 'units_'+adj not in ret['loot']:
                        ret['loot']['units_'+adj] = {}
                    ret['loot']['units_'+adj][b['spec']] = ret['loot']['units_'+adj].get(b['spec'],0) + 1

                    for res in full_cost:
                        if full_cost[res] > 0:
                            ret['loot']['units_'+adj+'_'+res] = ret['loot'].get('units_'+adj+'_'+res,0) + full_cost[res]

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
