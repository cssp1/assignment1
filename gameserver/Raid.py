#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for resolving raid outcomes
# used by both maptool (for offline resolution) and server (for online resolution)

def resolve(squad_feature, raid_feature):
    # * assumes that you already have all the proper mutex locks on squad and raid!
    # returns updated versions of squad, raid
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
