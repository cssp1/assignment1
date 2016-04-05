#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for resolving raid outcomes
# used by both maptool (for offline resolution) and server (for online resolution)

def resolve_raid(squad_feature, raid_feature):
    # * assumes that you already have all the proper mutex locks on squad and raid!
    # returns (update_map_feature) mutations of squad, raid
    assert squad_feature['base_type'] == 'squad' and squad_feature.get('raid')
    assert raid_feature['base_type'] == 'raid'

    squad_update = {}
    raid_update = {}

    base_resource_loot = raid_feature.get('base_resource_loot', {})
    max_cargo = squad_feature.get('max_cargo', {})
    cur_cargo = squad_feature.get('cargo', {})

    for res in base_resource_loot:
        if (base_resource_loot[res] > 0) and (res in max_cargo) and (cur_cargo.get(res,0) < max_cargo[res]):
            amount = min(base_resource_loot[res], max_cargo[res] - cur_cargo.get(res,0))
            base_resource_loot[res] -= amount
            cur_cargo[res] = cur_cargo.get(res,0) + amount

            # apply mutated versions
            raid_update['base_resource_loot'] = base_resource_loot
            squad_update['cargo'] = cur_cargo
            squad_update['cargo_source'] = 'raid'

    if sum(base_resource_loot.itervalues(), 0) < 1:
        # nothing more to loot - delete the raid site
        raid_update = None

    return squad_update, raid_update

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

# below has dependencies on SpinNoSQL stuff; above does not
import SpinNoSQLLockManager

# online function for resolving action at a map hex
# intended to be usable both by server and maptool
# intended to be self-contained with respect to locking and logging
# this assumes that the nosql_client you provide has been set up with hooks to properly broadcast map updates
def resolve_loc(nosql_client, region_id, loc, time_now, dry_run = False):
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
            squad_update, raid_update = resolve_raid(squad, raid)
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

if __name__ == '__main__':
    # test code
    test_path = [{'xy':[0,0],'eta':0},
                 {'xy':[1,1],'eta':1},
                 {'xy':[2,2],'eta':3},
                 {'xy':[3,3],'eta':4}]
    print '\n'.join(repr(x) for x in test_path)
    print '\n'.join(repr(x) for x in backtrack_path(test_path, 10))
