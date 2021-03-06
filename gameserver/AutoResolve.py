#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library for use by the game server to calculate auto-resolve battle results

from Equipment import Equipment

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
    cooldown = shooter.get_leveled_quantity(spell.get('cooldown', 1))
    #range = shooter.get_leveled_quantity(spell.get('range', 0)) # include somehow?

    # incorporate DoT damage
    if 'impact_auras' in spell:
        for aura in spell['impact_auras']:
            aura_spec = session.player.get_abtest_aura(aura['spec'])
            aura_strength = shooter.get_leveled_quantity(aura.get('strength',1))
            # XXX note: this does not support duration_vs!
            aura_duration = shooter.get_leveled_quantity(aura.get('duration',1))
            uptime = 1
            if aura_duration < cooldown:
                uptime = aura_duration / cooldown
            for effect in aura_spec.get('effects',[]):
                if effect['code'] == 'on_fire':
                    damage += uptime * aura_strength

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
            # XXX note: this does not support compound keys - see main.js: get_damage_modifier()
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

def item_affects_dps(owner, item):
    spec = owner.get_abtest_item(item['spec'])
    if spec:
        if 'equip' in spec and 'effects' in spec['equip']:
            for effect in spec['equip']['effects']:
                if effect['code'] == 'modstat' and effect['stat'] in ('weapon','weapon_level'):
                    return True
    return False

def equipment_key(obj):
    if obj.is_building() and obj.equipment:
        item_names = '|'.join(sorted('%s_L%d' % (item['spec'], item.get('level',1)) \
                                     for item in Equipment.equip_iter(obj.equipment) \
                                     if item_affects_dps(obj.owner, item)))
        return item_names
    return ''

def make_dps_key(shooter, target):
    return '%d:%s:L%d:%s vs %d:%s:L%d:%s' % \
           (shooter.owner.user_id, shooter.spec.name, shooter.level, equipment_key(shooter),
            target.owner.user_id, target.spec.name, target.level, equipment_key(target))

def get_killer_info(session, killer):
    ret = {'team': 'player' if killer.owner is session.player else 'enemy',
           'spec': killer.spec.name, 'level': killer.level, 'id': killer.obj_id}
    if killer.is_building():
        if killer.is_minefield() and killer.is_minefield_armed():
            ret['mine'] = killer.minefield_item()
        elif killer.is_emplacement() and killer.turret_head_item():
            ret['turret_head'] = killer.turret_head_item()
    return ret

# returns list of actions, where each action is a list arguments to call the server functions
# destroy_object() and object_combat_updates().

def resolve(session, log_func = None):
    actions = []
    def objects_destroyed(arg):
        actions.append((arg, None))
    def combat_updates(arg):
        actions.append((None, arg))

    shooter_list = []
    target_list = []

    target_cur_hp = {} # track remaining HP on each target

    for obj in session.iter_objects():
        if (not obj.is_destroyed()):
            if obj.is_shooter():
                shooter_list.append(obj)
            if (not obj.is_inert()) and (not obj.spec.worth_less_xp): # it can/should be killed (note: ignore barriers)
                target_list.append(obj)
                target_cur_hp[obj.obj_id] = obj.hp

    if log_func:
        log_func('begin auto-resolve with shooters %r' % pretty_obj_list(shooter_list))

    # cache object vs object DPS to avoid recomputation
    dps_cache = {}

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
                            log_func('DPS of %r = %r' % (dps_key, dps))

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
            killer_info = get_killer_info(session, killer)
            killer_spell = killer.get_auto_spell()
            if killer_spell and killer_spell.get('kills_self', False):
                # suicide unit
                shooter_list.remove(killer)
                if killer in target_list:
                    target_list.remove(killer)
                kill_list = filter(lambda x: x[1] != killer.obj_id, kill_list) # remove it from kill_list
                if killer.is_mobile():
                    objects_destroyed([killer.obj_id, [killer.x, killer.y], killer_info])
                elif killer.is_building():
                    combat_updates([killer.obj_id, killer.spec.name, None, 0, None, killer_info, None])
        else:
            killer_info = None

        if next.is_mobile():
            objects_destroyed([next.obj_id, [next.x, next.y], killer_info])
        elif next.is_building():
            combat_updates([next.obj_id, next.spec.name, None, 0, None, killer_info, None])

        # the opposing team doesn't suffer a death, but we need to
        # subtract HP from its most vulnerable target for the time taken during the kill
        for next_ttk, next_damaged_id, unused2 in kill_list[1:]:
            next_damaged = session.get_object(next_damaged_id)
            if next_damaged.owner is not next.owner:
                old_hp = target_cur_hp[next_damaged.obj_id]
                target_cur_hp[next_damaged.obj_id] = max(1, int((1.0 - ttk/next_ttk) * old_hp))
                if log_func:
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
            combat_updates([obj.obj_id, obj.spec.name, None, cur_hp, None, None, None])

    return actions
