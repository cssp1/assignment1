#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for use by the game server to calculate auto-resolve battle results

# return two lists of arguments to call the server functions destroy_object()
# and object_combat_updates(), respectively.

def resolve(session):
    objects_destroyed = []
    combat_updates = []

    # XXXXXX insert real algorithm here
    player_unit_space = 0
    enemy_unit_space = 0
    for obj in session.iter_objects():
        if (not obj.is_destroyed()) and obj.is_mobile():
            space = int(float(obj.hp)/float(obj.max_hp) * obj.get_leveled_quantity(obj.spec.consumes_space))
            if obj.owner is session.player:
                player_unit_space += space
            else:
                enemy_unit_space += space

    winner = 'stalemate'

    if player_unit_space > 1: # XXXXXX enemy_unit_space:
        winner = 'player'
    else:
        winner = 'enemy'

    if winner != 'stalemate':
        for obj in session.iter_objects():
            if (not obj.is_destroyed()) and (not obj.is_inert()):
                if (obj.owner is session.player and winner != 'player') or \
                   (obj.owner is not session.player and winner != 'enemy'):
                    # destroy the thing
                    # (note: no update sent to client - we assume an immediate session change follows)

                    #killer_info = {'team': winner, 'spec': 'XXXXXX', 'level': 0, 'id': 'XXXXXX'}
                    killer_info = None

                    if obj.is_mobile():
                        objects_destroyed.append([obj.obj_id, [obj.x, obj.y], killer_info])
                    elif obj.is_building():
                        new_hp = 0
                        combat_updates.append([obj.obj_id, obj.spec.name, None, new_hp, None, killer_info, None])

    return objects_destroyed, combat_updates
