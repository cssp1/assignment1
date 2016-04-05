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

if __name__ == '__main__':
    # test code
    test_path = [{'xy':[0,0],'eta':0},
                 {'xy':[1,1],'eta':1},
                 {'xy':[2,2],'eta':3},
                 {'xy':[3,3],'eta':4}]
    print '\n'.join(repr(x) for x in test_path)
    print '\n'.join(repr(x) for x in backtrack_path(test_path, 10))
