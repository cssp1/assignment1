#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for use by the game server to calculate auto-resolve battle results

# pretty-print a list of GameObjects
def pretty_obj_list(ls):
    return '['+', '.join('%s L%d %d/%d' % (x.spec.name, x.level, x.hp, x.max_hp) for x in ls)+']'

# compute damage per second done by "shooter" against "target"
def compute_dps(shooter, target, session):
    if target.is_invisible(session): return 0

    spell = shooter.get_auto_spell()
    if not spell: return 0
    if not spell.get('targets_air', True) and target.spec.flying: return 0
    if not spell.get('targets_ground', True) and (not target.spec.flying): return 0

    # XXX crude approximation of the client-side calculation
    damage = shooter.get_leveled_quantity(spell.get('damage', 0))
    #cooldown = shooter.get_leveled_quantity(spell.get('cooldown', 1))
    #range = shooter.get_leveled_quantity(spell.get('range', 0)) # include somehow?

    damage_coeff_pre_armor = 1.0
    damage_coeff_post_armor = 1.0

    damage_coeff_pre_armor *= shooter.owner.stattab.get_unit_stat(shooter.spec.name, 'weapon_damage', 1)
    damage_coeff_post_armor *= target.owner.stattab.get_unit_stat(target.spec.name, 'damage_taken', 1)

    for key in target.spec.defense_types:
        damage_coeff_pre_armor *= shooter.owner.stattab.get_unit_stat(shooter.spec.name, 'weapon_damage_vs:%s' % key, 1)

    damage_vs_table = shooter.get_leveled_quantity(spell.get('damage_vs',{}))
    if damage_vs_table:
        if not target.spec.defense_types:
            damage_coeff_pre_armor *= damage_vs_table.get('default',1)
        else:
            for key in target.spec.defense_types:
                if key in damage_vs_table:
                    damage_coeff_pre_armor *= shooter.get_leveled_quantity(damage_vs_table[key])
                    damage_coeff_post_armor *= target.owner.stattab.get_unit_stat(target.spec.name, 'damage_taken_from:%s' % key, 1)

    damage *= damage_coeff_pre_armor

    armor = max(target.get_leveled_quantity(target.spec.armor), target.owner.stattab.get_unit_stat(target.spec.name, 'armor', 0))
    if armor > 0: damage = max(1, damage - armor)

    damage *= damage_coeff_post_armor

    damage = max(1, int(damage + 0.5))

    return damage

# return two lists of arguments to call the server functions destroy_object()
# and object_combat_updates(), respectively.

def resolve(session, log_func = None):
    objects_destroyed = []
    combat_updates = []

    shooter_list = []
    target_list = []

    target_cur_hp = {} # track remaining HP on each target

    for obj in session.iter_objects():
        if (not obj.is_destroyed()):
            if obj.is_shooter():
                shooter_list.append(obj)
            if (not obj.is_inert()): # it can be killed
                target_list.append(obj)
                target_cur_hp[obj.obj_id] = obj.hp

    if log_func:
        log_func('begin auto-resolve with shooters %r' % pretty_obj_list(shooter_list))

    # cache object vs object DPS to avoid recomputation
    dps_cache = {}
    def make_dps_key(shooter, target):
        return '%d:%s:L%d vs %d:%s:L%d' % \
               (shooter.owner.user_id, shooter.spec.name, shooter.level,
                target.owner.user_id, target.spec.name, target.level)

    # iterate until nothing that can shoot is left alive OR
    # nothing can be damaged by what's left.

    iter_max = 10000 # protect against infinite loop
    cur_iter = 0

    while shooter_list:

        # compute the time for the opposing army to kill each unit in target_list, if all the shooter units focus-fire on it
        kill_list = [] # (kill_time, obj_id, biggest_damager_object)

        for obj in target_list:
            biggest_damager = None
            biggest_dps = 0
            total_dps = 0

            for shot in shooter_list:
                if shot.owner is not obj.owner:
                    dps_key = make_dps_key(shot, obj)
                    if dps_key in dps_cache:
                        dps = dps_cache[dps_key]
                    else:
                        dps = compute_dps(shot, obj, session)
                        dps_cache[dps_key] = dps
                        if log_func:
                            log_func('DPS of %s %s L%d vs. %s %s L%d = %r' % \
                                     (('player' if shot.owner is session.player else 'enemy'),
                                      shot.spec.name, shot.level,
                                      ('player' if obj.owner is session.player else 'enemy'),
                                      obj.spec.name, obj.level,
                                      dps))

                    if dps > biggest_dps:
                        biggest_dps = dps
                        biggest_damager = shot
                    total_dps += dps

            if total_dps > 0:
                # reference current HP, not original HP here
                ttk = float(target_cur_hp[obj.obj_id]) / float(total_dps)
                kill_list.append((ttk, obj.obj_id, biggest_damager))

        if not kill_list: # nothing more is killable by anyone - stalemate
            break

        kill_list.sort() # note: uses kill_time as sort key

        # find next thing to die
        ttk, next_obj_id, killer = kill_list[0]
        next = session.get_object(next_obj_id)

        if log_func:
            log_func('next to die: %s %s L%d killed by %s after %.4f sec' % \
                     (('player' if next.owner is session.player else 'enemy'), next.spec.name, next.level,
                      killer.spec.name, ttk))
        target_list.remove(next)
        if next.is_shooter():
            shooter_list.remove(next)
        del target_cur_hp[next.obj_id]

        # destroy the thing
        # (note: no update sent to client - we assume an immediate session change follows)

        if killer:
            killer_info = {'team': 'player' if killer.owner is session.player else 'enemy',
                           'spec': killer.spec.name, 'level': killer.level, 'id': killer.obj_id}
            if killer.is_mobile():
                killer_spell = killer.get_auto_spell()
                if killer_spell and killer_spell.get('kills_self', False):
                    # suicide unit
                    shooter_list.remove(killer)
                    target_list.remove(killer)
                    kill_list = filter(lambda x: x[1] != killer.obj_id, kill_list) # remove it from kill_list
                    objects_destroyed.append([killer.obj_id, [killer.x, killer.y], killer_info])
        else:
            killer_info = None

        if next.is_mobile():
            objects_destroyed.append([next.obj_id, [next.x, next.y], killer_info])
        elif next.is_building():
            new_hp = 0
            combat_updates.append([next.obj_id, next.spec.name, None, new_hp, None, killer_info, None])

        # the opposing team doesn't suffer a death, but we need to
        # subtract HP from its most vulnerable target for the time taken during the kill
        for next_ttk, next_damaged_id, unused2 in kill_list[1:]:
            next_damaged = session.get_object(next_damaged_id)
            if next_damaged.owner is not next.owner:
                old_hp = target_cur_hp[next_damaged.obj_id]
                target_cur_hp[next_damaged.obj_id] = int((1.0 - ttk/next_ttk) * old_hp)
                log_func('opposition damage: %s %s L%d HP %d -> %d (ttk %f next_ttk %f)' % \
                         (('player' if next_damaged.owner is session.player else 'enemy'), next_damaged.spec.name, next_damaged.level,
                          old_hp, target_cur_hp[next_damaged.obj_id], ttk, next_ttk))
                break

        cur_iter += 1
        if cur_iter >= iter_max:
            raise Exception('runaway iteration, shooter_list %r target_list %r' % \
                            (pretty_obj_list(shooter_list), pretty_obj_list(target_list)))

    # update HP on damaged-but-not-destroyed objects
    for id, cur_hp in target_cur_hp.iteritems():
        obj = session.get_object(id)
        if cur_hp != obj.hp:
            if log_func:
                log_func('remaining damage: %s %s L%d HP %d -> %d' % \
                         (('player' if obj.owner is session.player else 'enemy'), obj.spec.name, obj.level,
                          obj.hp, cur_hp))
            combat_updates.append([obj.obj_id, obj.spec.name, None, cur_hp, None, None, None])

    return objects_destroyed, combat_updates
