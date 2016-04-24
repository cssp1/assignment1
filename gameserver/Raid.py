#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for resolving raid outcomes
# used by both maptool (for offline resolution) and server (for online resolution)

def get_leveled_quantity(qty, level): # XXX duplicate
    if type(qty) == list:
        return qty[level-1]
    return qty

def resolve_raid(squad_feature, raid_feature, squad_units, raid_units):
    # * assumes that you already have all the proper mutex locks on squad and raid!
    # returns (update_map_feature) mutations of squad, raid, loot
    assert squad_feature['base_type'] == 'squad' and squad_feature.get('raid')
    assert raid_feature['base_type'] == 'raid'

    raid_mode = squad_feature['raid']
    assert raid_mode in ('pickup','attack','defend','scout')

    squad_update = {}
    raid_update = {}
    loot = {}

    # scouting
    if raid_mode == 'scout':
        # add something here just to trigger a mutation
        squad_update['scouted'] = 1

    # looting
    if raid_mode != 'scout':
        base_resource_loot = raid_feature.get('base_resource_loot', {})
        max_cargo = squad_feature.get('max_cargo', {})
        cur_cargo = squad_feature.get('cargo', {})

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

    return squad_update, raid_update, loot

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
import SpinNoSQLLockManager

# online function for resolving action at a map hex
# intended to be usable both by server and maptool
# intended to be self-contained with respect to locking and logging
# this assumes that the nosql_client you provide has been set up with hooks to properly broadcast map updates
def resolve_loc(gamedata, nosql_client, chat_mgr, region_id, loc, time_now, dry_run = False):
    features = nosql_client.get_map_features_by_loc(region_id, loc)
    # filter out not-arrived-yet moving features (use strict time comparison)
    features = filter(lambda feature: ('base_map_path' not in feature) or \
                      feature['base_map_path'][-1]['eta'] < time_now, features)
    raid_squads = filter(lambda feature: feature['base_type'] == 'squad' and feature.get('raid'), features)
    if not raid_squads: return # no raids to process

    targets = filter(lambda x: x['base_type'] == 'raid', features)
    if not targets: return # no targets to process
    raid = targets[0] # select first target

    # for proper resolution ordering, sort by arrival time, earliest first
    raid_squads.sort(key = lambda squad: squad['base_map_path'][-1]['eta'] if 'base_map_path' in squad else -1)

    lock_manager = SpinNoSQLLockManager.LockManager(nosql_client, dry_run = dry_run)
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

            squad_update, raid_update, loot = resolve_raid(squad, raid, squad_units, raid_units)

            if squad_update or raid_update or (raid_update is None):
                # metrics - keep in sync between Raid.py and maptool.py implementations!

                # query player_cache for metadata on the attacker and
                # defender. Not absolutely 100% guaranteed to be up to date with
                # online server data, but close enough.
                attacker_pcinfo, defender_pcinfo = nosql_client.player_cache_lookup_batch([owner_id, raid['base_landlord_id']], reason = 'Raid.resolve_loc')

                summary = make_battle_summary(gamedata, nosql_client, time_now, region_id, squad, raid,
                                              squad['base_landlord_id'], raid['base_landlord_id'],
                                              attacker_pcinfo, defender_pcinfo,
                                              'victory', 'defeat',
                                              squad_units, raid_units, loot, raid_mode = squad['raid'])
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
                        attacker_units, defender_units, # object state list
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

    deployed_units = {}
    for obj in attacker_units:
        deployed_units[obj['spec']] = deployed_units.get(obj['spec'],0) + 1

    ret['deployed_units'] = deployed_units

    # record remaining strength of defender
    for obj in defender_units:
        spec = gamedata['units'][obj['spec']]
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

    ret['loot'] = loot
    # { 'damage_inflicted' : 5445,
        #'units_lost' : {'chaingunner' : 1, 'marine' : 6},
        #'units_lost_iron' : 3855,
        #'units_lost_water' : 7198,
        #'units_killed_water' : 77713,
        #'units_killed_iron' : 61308
        #'units_killed' : { 'elite_centurion' : 2 },
        #'xp' : 0, 'iron': 1000, 'water': 1000 }

    if 0: # XXX for later
        ret['damage'] = {
                str(attacker_id) : {
                'marine:L8' : {
                    'count' : 6,
                    'water' : 2172,
                    'iron' : 1020,
                    'time' : 42
                },
                'chaingunner:L8' : {
                    'water' : 5026,
                    'iron' : 2835,
                    'time' : 119
                }
            }
        }

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
