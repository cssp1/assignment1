#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this script makes various procedurally-generated art asset permutations for inventory items
# needs units.json as input for unit names

import SpinConfig
import SpinJSON
import AtomicFileWrite
import sys, getopt, os

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['game-id='])
    game_id = SpinConfig.game()

    for key, val in opts:
        # allow override of game_id
        if key == '-g' or key == '--game-id': game_id = val

    units = SpinConfig.load(args[0], override_game_id = game_id)
    out_fd = AtomicFileWrite.AtomicFileWrite(args[1], 'w', ident=str(os.getpid()))

    print >>out_fd.fd, "// AUTO-GENERATED BY make_art_items.py"

    units = SpinConfig.load(args[0], override_game_id = game_id)

    out = {}
    outkeys = []

    # create unit inventory icons
    if game_id not in ('sg',):
        # (sg uses hand-painted images in art.json)

        EXTRA_UNITS = [] # units that are not included in units.json but whose icons are needed
        if game_id in ('tr','dv'):
            EXTRA_UNITS += [('ch47', {'art_asset': 'ch47'})]
            for extra_name in ('ah1x','ah64x','armyguy_javelinx','armyguy_m240x','armyguy_mortarx','armyguy_sapperx','armyguy_stingerx','armyguy_xm110x',
                               'armyguyx','bmp1x','brdm3x','dv_adlerkfz13x','dv_armyguyx','dv_armyguy_javelinx','dv_armyguy_m240x',
                               'dv_armyguy_mortarx','dv_m12x','dv_m26_pershingx','dv_m4a2_shermanx','dv_m4_halftrackx','dv_panzerwerferx','dv_panzer_ivx',
                               'dv_sdkfz234_pumax','f35x','gaz_tigrx','m109a6x','m1abramsx','mi24x','mq1cx','mq8bx','mstax','oh58x',
                               'strykerx','suicide_truckx','t90x','tos1ax','uh60x'):
                for extra_color in ('black','blue','brown','green','orange','purple','yellow'):
                    extra_val = '%s_t%s' % (extra_name, extra_color)
                    EXTRA_UNITS += [(extra_val, {'art_asset': extra_val})]
        if game_id in ('bfm','mf2'):
            for extra_name in ('bfm_centurionx','bfm_elevated_cannon_six_wheels_flamingx','bfm_hellhoundx','bfm_kitbashed_curiosityx','bfm_liberatorx','bfm_maulerx','bfm_mech_on_wheelsx','bfm_missile_carx','bfm_pencil_nosex','bfm_rainmakerx','bfm_two_thrusters_two_cannonsx','bfm_warbirdx','bfm_wombatx','bfm_wreckerx'):
                for extra_color in ('black','blue','brown','green','orange','purple','yellow'):
                    extra_val = '%s_t%s' % (extra_name, extra_color)
                    EXTRA_UNITS += [(extra_val, {'art_asset': extra_val})]
        for unit_name, unit_data in units.items() + EXTRA_UNITS:
            key = 'inventory_%s' % unit_name
            outkeys.append(key)
            DEFAULT_OFFSET = [0,-5]
            # special-case pixel offsets for units where the default offset does not look good
            SPECIAL_OFFSETS = {'rifleman': [0,0],
                               'mortarman': [0,0],
                               'stinger_gunner': [0,0],
                               'cyclone': [0,5],
                               'saber': [-2,1],
                               'ch47': [0,0],

                               # FS
                               'infantry_tier_1': [0,4],
                               'infantry_tier_5': [0,0],
                               'infantry_tier_10': [0,0],
                               'special_infantry_tier_4': [0,0],
                               'armor_tier_1': [0,2],
                               'armor_tier_2': [0,2],
                               'armor_tier_4': [0,2],
                               'armor_tier_5': [0,2],
                               'armor_tier_7': [0,2],
                               'armor_tier_9': [0,2],
                               'armor_tier_11': [0,2],
                               'armor_tier_13': [0,2],
                               'armor_tier_15': [2,2],
                               'special_armor_tier_7': [0,2],

                               'aircraft_tier_1': [0,1],
                               'aircraft_tier_3': [0,1],
                               'aircraft_tier_6': [0,1],
                               'aircraft_tier_8': [0,1],
                               'aircraft_tier_12': [0,1],
                               'aircraft_tier_14': [0,1],
                               'special_aircraft_tier_10': [0,1],
                               'special_aircraft_tier_15': [0,1],

                               # BFM
                               'marine': [0,0],
                               'grenadier': [0,0],
                               'chaingunner': [0,3],
                               'boomer': [0,0],
                               'marksman': [0,-4],
                               'rainmaker': [0,5], 'elite_rainmaker': [0,5],
                               'wrecker': [0,0], 'elite_wrecker': [0,0],
                               'centurion': [0,7],
                               'mauler': [0,6],
                               'outrider':[0,8],
                               'tornado': [0,3],
                               'voodoo': [0,8],
                               'hellhound': [0,8],

                               # SG
                               'swordsman': [0,6],
                               'thief': [0,6],
                               'orc': [0,6],
                               'archer': [0,6],
                               'paladin': [0,6],
                               'airship': [-2,-1],
                               'sorceress': [0,6],
                               'fire_phantom': [0,6],
                               'golem': [0,4],
                               'dragon': [5,-5],
                               }
            out[key] = {"states": { "normal": { "dimensions": [50,50], "subassets": [{"name": unit_data['art_asset'],
                                                                                      "state": "icon",
                                                                                      "centered": 1,
                                                                                      "offset": SPECIAL_OFFSETS.get(unit_name, DEFAULT_OFFSET),
                                                                                      "clip_to": [0,0,50,50]}]
                                                } } }

    # create icons for DPS/environ/armor boost/armor equip/range/speed mods for units
    if game_id in ('mf','tr','mf2','dv','bfm'):
        buff_kinds = ['damage', 'armor', 'range', 'speed']
        if game_id in ('tr','dv','sg','bfm','mf2'):
            buff_kinds += ['damage_resist_equip','damage_boost_equip','range_boost_equip','secteam_equip']
        if game_id != 'bfm':
            buff_kinds += ['radcold']
        if game_id in ('tr','dv'):
            buff_kinds += ['repair_speedup_equip']
        for kind in buff_kinds:
            for unit_name, unit_data in units.iteritems():
                if unit_name == 'repair_droid': continue
                if unit_data.get('activation',{}).get('predicate',None) == 'ALWAYS_FALSE': continue # skip disabled units

                for rarity_color in ('black','gray', 'green', 'blue', 'purple', 'orange'):

                    #if kind == 'radcold' and rarity_color != 'purple': continue

                    key = 'inventory_%s_%s_%s' % (kind, unit_name, rarity_color)
                    outkeys.append(key)
                    out[key] = \
                                             { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                                     "inventory_%s" % unit_name,
                                                                                     "inventory_%s" % kind] } } }

    # create icons for DPS/armor/range/speed mods for manufacture categories
    if game_id in ('mf','tr','mf2','dv','sg','bfm'):
        buff_kinds = ['damage', 'armor', 'range', 'speed']
        if game_id != 'bfm':
            buff_kinds += ['radcold']
        for kind in buff_kinds:
            for (unit_type, unit_type_plural) in {'rover': 'rovers', 'transport': 'transports', 'starcraft': 'starcraft'}.iteritems():
                for rarity_color in ('black','gray', 'green', 'blue', 'purple', 'orange'):

                    key = 'inventory_%s_%s_%s' % (kind, unit_type, rarity_color)
                    outkeys.append(key)
                    out[key] = { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                       "inventory_%s" % unit_type_plural,
                                                                       "inventory_%s" % kind] } } }
                    key_gift = key + '_gift'
                    outkeys.append(key_gift)
                    out[key_gift] = { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                       "inventory_%s" % unit_type_plural,
                                                                       "inventory_%s" % kind,
                                                                       "inventory_giftwrap"] } } }

    if game_id in ('tr','dv','sg','bfm'):
        # TR only - create icons for damage_vs mods for tr unit categories (infantry, armor, aircraft)
        for kind in ('damage_vs_rover', 'damage_vs_transport'):
            for unit_name, unit_data in units.iteritems():
                if unit_name == 'repair_droid': continue
                if unit_data.get('activation',{}).get('predicate',None) == 'ALWAYS_FALSE': continue # skip disabled units

                for rarity_color in ('black','gray', 'green', 'blue', 'purple', 'orange'):

                    key = 'inventory_%s_%s_%s' % (kind, unit_name, rarity_color)
                    outkeys.append(key)
                    out[key] = \
                                             { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                                     "inventory_%s" % unit_name,
                                                                                     "inventory_damage",
                                                                                     "inventory_%s" % kind] } } }

        # TR only - create icons for aoefire_shield mods for unit categories (infantry, armor, aircraft)
        for kind in ('aoefire_shield',):
            for unit_category_name in ('rovers', 'transports', 'starcraft'):
                for rarity_color in ('black','gray', 'green', 'blue', 'purple', 'orange'):
                    key = 'inventory_%s_%s_%s' % (kind, unit_category_name, rarity_color)
                    outkeys.append(key)
                    out[key] = \
                                             { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                                     "inventory_%s" % unit_category_name,
                                                                                     "inventory_%s" % kind] } } }

        # TR only - create icons for boosts that apply to individual units
        if game_id in ('tr','dv'):
            for kind in ('secteam','waterdrop'):
                for unit_name in ('gaz_tigr','humvee','btr90','stryker','brdm3','m109','m2bradley'):
                    for rarity_color in ('black','gray', 'green', 'blue', 'purple', 'orange'):
                        key = 'inventory_%s_%s_%s' % (kind, unit_name, rarity_color)
                        outkeys.append(key)
                        out[key] = \
                                 { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                         "inventory_%s" % unit_name,
                                                                         "inventory_%s" % kind] } } }

        # BFM only - create icons for boosts that apply to individual units
        if game_id == 'bfm':
            for kind in ('secteam','waterdrop'):
                for unit_name in ('outrider','saber','voodoo','curiosity','hellhound','gun_runner','punisher'):
                    for rarity_color in ('black','gray', 'green', 'blue', 'purple', 'orange'):
                        key = 'inventory_%s_%s_%s' % (kind, unit_name, rarity_color)
                        outkeys.append(key)
                        out[key] = \
                                 { "states": { "normal": { "subassets": ["inventory_bg_%s" % rarity_color,
                                                                         "inventory_%s" % unit_name,
                                                                         "inventory_%s" % kind] } } }

    count = 0
    for key in outkeys:
        val = out[key]
        print >>out_fd.fd, '"%s":' % key, SpinJSON.dumps(val),
        if count != len(outkeys)-1:
            print >>out_fd.fd, ','
        else:
            print >>out_fd.fd
        count += 1

    out_fd.complete()
