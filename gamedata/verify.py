#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# gamedata checker

import SpinJSON
import GameDataUtil
import sys, traceback, os, copy, time, re
import getopt

# optionally use the Damerau-Levenshtein string distance metric to check for mis-spelled JSON keys
has_damerau_levenshtein = False
try:
    from pyxdameraulevenshtein import damerau_levenshtein_distance
    has_damerau_levenshtein = True
except ImportError:
    print 'pyxadameraulevenshtein module not found - install this if you want typo-checking'
    pass

time_now = int(time.time())
gamedata = None
verbose = False

# check keys in a dictionary "d" for any key that is similar but not
# quite equal to a member of set "correct_keys", which is probably a typo.
def check_misspellings(d, correct_keys, reason):
    if not has_damerau_levenshtein: return 0
    assert type(correct_keys) is set
    error = 0
    for k in d:
        if k not in correct_keys:
            for key in correct_keys:
                if damerau_levenshtein_distance(k, key) < 3:
                    error |= 1
                    print 'probable typo in dictionary key %s "%s" (similar to correct key "%s")' % \
                          (reason, k, key)
    return error

# track all entries in art.json referenced by code and data
# note, this is separate from the tracking of whether the art pack actually contains what's needed by art.json
required_art_assets = set()
def require_art_asset(name, reason):
    error = 0
    if type(name) not in (str,unicode):
        error |= 1; print '%s bad asset "%s"' % (reason, repr(name))
    elif name not in gamedata['art']:
        error |= 1; print '%s references missing art asset "%s"' % (reason, name)
    else:
        required_art_assets.add(name)
    return error

# track raw art files referenced in places OTHER than art.json (e.g. loading screens)
required_art_files = set()
def require_art_file(name):
    required_art_files.add(name)

# never allow upgrades to cost more than this much resources, since the player cannot hold as much even with max storage!
# CC L6 = 4*L10 storage = 24400000
# CC L8 = 4*L12 storage = 34000000

MAX_RESOURCE_COST = 34000000
MAX_STORAGE = None

def check_url(url, reason):
    if not url: return 0

    error = 0
    if type(url) is list: # cond chain
        error |= check_cond_chain(url, reason = reason)
        for pred, u in url:
            error |= check_url(u, reason = reason)
        return error

    if not url.startswith('//'):
        if 'on.fb.me' in url:
            pass # XXX unfortuantely this breaks tons of links - we have to find an HTTPS substitute
        else:
            error |= 1; print '%s: URL "%s" needs to be protocol-relative (starts with // not http://)' % (reason, url)
    if 'on.fb.me' in url:
        if (not url.startswith('http://')):
            error |= 1; print '%s: URL "%s" to on.fb.me must use http:// because HTTPS is not supported' % (reason, url)
    if url.endswith(' ') or url.endswith('\t'):
        error |= 1; print '%s: URL "%s" has bad whitespace at the end' % (reason, url)
    return error

def check_unit_name(specname, context):
    error = 0
    if specname not in gamedata['units']:
        error |= 1; print '%s refers to missing unit "%s"' % (context, specname)
    elif gamedata['units'][specname].get('activation',{}).get('predicate',None)=='ALWAYS_FALSE':
        error |= 1; print '%s refers to disabled unit "%s"' % (context, specname)
    return error

def check_inert(specname, spec):
    error = 0
    if spec.get('auto_spawn',0):
        coll = spec.get('unit_collision_gridsize', [0,0])
        climates = spec.get('base_climates',[])
        if coll[0] > 0 or coll[1] > 0:
            # special exception for cave sprites
            if (len(climates) == 1 and climates[0] == 'cave'):
                pass
            else:
                error |= 1
                print specname, 'has auto_spawn:1 but is collidable - auto_spawn scenery should not have unit_collision_gridsize', spec['base_climates']
        if len(spec.get('base_types',[])) < 1:
            error |= 1
            print specname, 'has auto_spawn:1 but has no base_types, please add "base_types": ["home"] to the JSON'

    art_list = spec['art_asset'] if isinstance(spec['art_asset'], list) else [spec['art_asset'],]
    for art in art_list:
        error |= require_art_asset(art, specname)
    if 'continuous_cast' in spec and spec['continuous_cast'] not in gamedata['spells']:
        error |= 1; print specname, 'continuous_cast spell "%s" not found' % (spec['continuous_cast'])
    return error

def check_mandatory_fields(specname, spec, kind):
    fields = ['name', 'kind', 'gridsize', 'defense_types', 'art_asset']
    if kind == 'buildings':
        fields += ['unit_collision_gridsize']
    elif kind == 'units':
        fields += ['manufacture_category']
    error = 0
    for f in fields:
        if f not in spec:
            error |= 1
            print '%s missing mandatory field "%s"' % (specname, f)

    if spec['name'] != specname.split(':')[1]:
        error |= 1
        print '%s "name" mismatch' % specname

    for ART in ('art_asset', 'icon', 'splash_image'):
        if ART in spec:
            if isinstance(spec[ART], list):
                artlist = spec[ART]
            else:
                artlist = [spec[ART]]
            for asset in artlist:
                error |= require_art_asset(asset, specname+':'+ART)

    if 'icon' in spec:
        if spec['icon'] != 'inventory_'+spec['name']:
            error |= 1; print '%s "icon" should be inventory_%s' % (specname, specname)

    if 'shadow_asset' in spec:
        error |= require_art_asset(spec['shadow_asset'], specname+':shadow_asset')

    if 'destroyed_inert' in spec and (spec['destroyed_inert'] is not None):
        if spec['destroyed_inert'] not in gamedata['inert']:
            error |= 1; print 'object %s has invalid destroyed_inert %s' % (specname, spec['destroyed_inert'])

    if kind == 'buildings':
        # check that the under_construction and destroyed version exist at this gridsize
        misc_assets = {'under_construction_asset': spec.get('under_construction_asset', 'building_construction_%dx%d' % tuple(spec['gridsize'])),
                       'destroyed_asset': spec.get('destroyed_asset', 'building_crater_%dx%d' % tuple(spec['gridsize']))}
        for k, v in misc_assets.iteritems():
            error |= require_art_asset(v, specname+':'+k)

        if gamedata['game_id'] == 'sg':
            if spec.get('quantize_location',1) != 4:
                error |= 1; print 'building %s has invalid quantize_location setting. In SG, all buildings must have "quantize_location": 4' % specname
#            if spec['name'] != 'barrier' and spec.get('exclusion_zone',None) != [4,4]:
#                error |= 1; print 'building %s has invalid exclusion_zone setting. In SG, all buildings (except barriers) must have "exclusion_zone": [4,4]' % specname
    max_level = -1

    if kind in GameDataUtil.MAX_LEVEL_FIELD:
        field = GameDataUtil.MAX_LEVEL_FIELD[kind]
        if (field not in spec):
            error |= 1; print '%s missing mandatory field %s' % (specname, field)
        elif not isinstance(spec[field], list):
            error |= 1; print '%s:%s MUST be a per-level list because it is used to fix max level' % (specname, field)
        else:
            max_level = len(spec[field])

    # check that per-level array parameters have the right number of elements
    for check_field in ['max_hp','maxvel','turn_rate','consumes_space','armor',
                        'requires','remove_requires',
                        'remove_cost_gamebucks', 'remove_reward_gamebucks',
                        'provides_space','build_time','repair_time','consumes_power',
                        'consumes_power_while_building','upgrade_credit_cost','upgrade_speedup_cost_factor','upgrade_xp','proposed_upgrade_xp',
                        'metric_events',
                        'provides_inventory','provides_squads','provides_deployed_squads','provides_squad_space','provides_total_space'] + \
    ['build_cost_'+res for res in gamedata['resources']] + \
    ['remove_reward_'+res for res in gamedata['resources']] + \
    ['remove_cost_'+res for res in gamedata['resources']] + \
    ['produces_'+res for res in gamedata['resources']] + \
    ['storage_'+res for res in gamedata['resources']]:
        if (check_field in spec) and (type(spec[check_field]) is list) and (len(spec[check_field]) != max_level):
            error |= 1
            print '%s %s "%s" array length (%d) does not match max level (%d - as determined by length of %s array)' % (kind, specname, check_field, len(spec[check_field]), max_level, GameDataUtil.MAX_LEVEL_FIELD[kind])

    if 'upgrade_xp' in spec and kind == 'buildings' and spec['name'] not in gamedata['player_xp']['buildings']:
        error |= 1; print '%s %s has upgrade_xp but is not listed in player_xp.buildings (needs to be there, even if 0)' % (kind, specname)

    if 'consumes_space' in spec and spec['consumes_space'] == 0:
        if spec.get('donatable',True):
            error |= 1; print '%s %s consumes_space 0 but is donatable - probably not correct' % (kind, specname)

    if 'provides_limited_equipped' in spec:
        for provides_name, provides_array in spec['provides_limited_equipped'].iteritems():
            if type(provides_array) is list and len(provides_array) != max_level:
                error |= 1; print '%s %s "provides_limited_equipped": "%s" array length (%d) does not match max level (%d)' % (kind, specname, provides_name, len(provides_array), max_level)
            stat_key = 'provides_limited_equipped:'+provides_name
            if stat_key not in gamedata['strings']['modstats']['stats']:
                error |= 1; print 'gamedata.strings.modstats.stats is missing "%s"' % stat_key

    for lev in xrange(1,max_level+1):
        cc_requirement = GameDataUtil.get_cc_requirement(gamedata, spec['requires'], lev) if ('requires' in spec) else 0
        if spec['name'] == gamedata['townhall']:
            cc_requirement = max(cc_requirement, lev-1)
        for res in gamedata['resources']:
            cost_raw = spec.get('build_cost_'+res, 0)
            cost = cost_raw[lev-1] if isinstance(cost_raw, list) else cost_raw
            if cost > MAX_RESOURCE_COST:
                error |= 1
                print '%s %s level %d has %s cost exceeding global limit of %d' % (kind, specname, lev, res, MAX_RESOURCE_COST)
            if cc_requirement > 0 and cost > MAX_STORAGE[res][cc_requirement-1]:
                error |= 1
                print '%s %s level %d requires CC L%d but has %s cost of %d, which exceeds max storage capacity at that CC level of %d' % (kind, specname, lev, cc_requirement, res, cost, MAX_STORAGE[res][cc_requirement-1])

    for snd in ('sound_click', 'sound_destination', 'sound_attack'):
        if snd in spec:
            error |= require_art_asset(spec[snd], specname+':'+snd)

    if kind == 'units':
        level_tech = spec['level_determined_by_tech']
        if level_tech not in gamedata['tech']:
            error |= 1
            print '%s:level_determined_by_tech refers to a tech that does not exist (%s)' % (specname, level_tech)
        else:
            if gamedata['tech'][level_tech].get('associated_unit') != spec['name']:
                error |= 1; print 'tech:%s should have associated_unit %s' % (level_tech, spec['name'])
        if level_tech != spec['name']+'_production':
            error |= 1; print '%s:level_determined_by_tech is probably a typo' % (specname,)

        # games where all units should be resurrectable
        if (gamedata['game_id'] not in ('sg','fs')) and (not spec.get('resurrectable',False)) and (spec['name'] != 'repair_droid'):
            error |= 1
            print '%s is not resurrectable' % specname

        # games where all units should be NOT resurrectable, YES consumable
        elif gamedata['game_id'] == 'sg' and (spec.get('resurrectable',False) or (not spec.get('consumable',False))) and spec['manufacture_category'] != 'heroes':
            error |= 1; print '%s: units in SG must be "resurrectable":0, "consumable":1 (except for hero units).' % specname
        # games where all units should be NOT resurrectable, NOT consumable
        elif gamedata['game_id'] == 'fs' and (spec.get('resurrectable',False) or (spec.get('consumable',False))):
            error |= 1; print '%s: units in FS must be "resurrectable":0, "consumable":0' % specname

    # check predicate fields
    if 'requires' in spec:
        req = spec['requires'] if type(spec['requires']) is list else [spec['requires'],]
        for r in req:
            error |= check_predicate(r, reason = specname+':requires')
    for FIELD in ('activation','show_if'):
        if FIELD in spec:
            error |= check_predicate(spec[FIELD], reason = specname+':'+FIELD)

    # "activation" is deprecated
    if 'activation' in spec:
        error |= 1; print '%s "activation" is deprecated, change to "show_if"' % specname

    if 'research_categories' in spec:
        for cat in spec['research_categories']:
            found = False
            for entry in sum(gamedata['strings']['research_categories'].values(), []):
                if entry['name'] == cat:
                    found = True
                    break
            if not found:
                error |= 1; print '%s research category %s not found in gamedata.strings.research_categories.*.name' % (specname, cat)
    if 'manufacture_category' in spec:
        if spec['manufacture_category'] not in gamedata['strings']['manufacture_categories']:
            error |= 1; print '%s manufacture category %s not found in gamedata.strings.manufacture_categories' % (specname, spec['manufacture_category'])

    if spec.get('permanent_auras',None):
        for a in spec['permanent_auras']:
            if a['aura_name'] not in gamedata['auras']:
                error |= 1
                print '%s:permanent_auras refers to an aura that does not exist (%s)' % (specname, a['aura_name'])

    for EFFECT in ('pre_deploy_effect','post_deploy_effect','explosion_effect','damaged_effect','movement_effect','permanent_effect','upgrade_finish_effect'):
        if EFFECT in spec:
            vfx_list = spec[EFFECT] if type(spec[EFFECT]) is list else [spec[EFFECT],]
            for vfx in vfx_list:
                error |= check_visual_effect(specname+':'+EFFECT, vfx)

    if 'upgrade_completion' in spec:
        if kind != 'buildings':
            error |= 1; print '%s: upgrade_completion is only for buildings (use tech.completion for unit upgrades)' % (specname,)
        comp = spec['upgrade_completion'] if type(spec['upgrade_completion']) is list else [spec['upgrade_completion'],]
        for c in comp:
            if c is not None:
                error |= check_consequent(c, reason = specname+':upgrade_completion', context='building')

    if 'equip_slots' in spec:
        slot_dict_list = spec['equip_slots'] if type(spec['equip_slots']) is list else [spec['equip_slots'],]
        for slot_dict in slot_dict_list:
            for slot_name, qty in slot_dict.iteritems():
                if slot_name not in gamedata['strings']['equip_slots']:
                    error |= 1; print '%s: equip_slot type %s not found in strings.json' % (specname, slot_name)
    return error

def check_object_spells(specname, spec, maxlevel):
    if 'spells' not in spec:
        return 0
    error = 0

    for spellname in spec['spells']:
        if spellname not in gamedata['spells']:
            error |= 1
            print '%s refers to missing spell "%s"' % (specname, spellname)
            return error

    if len(spec['spells']) > 0:
        auto_spell_name = spec['spells'][0]
        auto_spell = gamedata['spells'][auto_spell_name]
        if auto_spell['activation'] == 'auto':
            # check levels on the attack spell
            for field in ['damage', 'range', 'splash_range', 'effective_range', 'accuracy'] + [f for f in auto_spell if f.startswith('projectile_') and (not f.endswith('color'))]:
                if field in auto_spell and isinstance(auto_spell[field], list):
                    if len(auto_spell[field]) != maxlevel:
                        error |= 1
                        print 'spell %s:%s has different number of levels (%d) from associated unit (%d)' % (auto_spell_name,field,len(auto_spell[field]),maxlevel)

            if 'effective_range' in auto_spell:
                if ('range' not in auto_spell):
                    error |= 1; print 'spell %s has effective_range but needs range too' % auto_spell_name
                elif ('splash_range' in auto_spell):
                    error |= 1; print 'spell %s has effective_range but this does not work with splash-damage weapons' % auto_spell_name
                else:
                    range_ls = auto_spell['range'] if type(auto_spell['range']) is list else [auto_spell['range'],]*maxlevel
                    eff_ls = auto_spell['effective_range'] if type(auto_spell['effective_range']) is list else [auto_spell['effective_range'],]*maxlevel
                    for level in xrange(max(len(range_ls), len(eff_ls))):
                        if eff_ls[level] < 0 or eff_ls[level] > range_ls[level]:
                            error |= 1; print 'spell %s effective_range at level %d needs to be between 0 and %d (the range at that level)' % (auto_spell_name, level+1, range_ls[level])
            if 'accuracy' in auto_spell:
                if ('splash_range' in auto_spell):
                    error |= 1; print 'spell %s has an "accuracy" setting but this does not work with splash-damage weapons' % auto_spell_name
                else:
                    ls = auto_spell['accuracy'] if type(auto_spell['accuracy']) is list else [auto_spell['accuracy'],]
                    for acc in ls:
                        if acc < 0 or acc > 1:
                            error |= 1; print 'spell %s has invalid accuracy %f (must be between 0 and 1 inclusive)' % (auto_spell_name, acc)

            # check mandatory fields on attack spell
            for field in ['damage', 'targets_air', 'targets_ground']:
                if field not in auto_spell:
                    error |= 1
                    print 'spell %s is missing mandatory field %s' % (auto_spell_name, field)

            # check that time values are multiples of COMBAT_TICK (0.25)
            for field in ['cooldown', 'deployment_arming_delay']: # note: 'prefire_delay' does NOT have to be a multiple of COMBAT_TICK
                if field in auto_spell:
                    cdlist = auto_spell[field]
                    if type(cdlist) is not list:
                        cdlist = [cdlist,]
                    for cd in cdlist:
                        int_cd = int(cd*100.0+0.5)
                        if (int_cd % 25) != 0:
                            error |= 1; print 'spell %s has bad %s value %f - it must be a multiple of 0.25' % (auto_spell_name, field, cd)
            if 'firing_arc' in auto_spell:
                arc = auto_spell['firing_arc']
                if type(arc) is not list:
                    arc = [arc,]
                for a in arc:
                    if a < 2 or a > 360:
                        error |= 1
                        print 'spell %s has bad firing_arc value %f - it must be between 2 and 360' % (auto_spell_name, a)
            if 'priority_vs' in auto_spell:
                if ('blocker' in auto_spell['priority_vs']) or ('inaccessible' in auto_spell['priority_vs']):
                    if not spec.get('enable_ai_threatlist', False):
                        error |= 1
                        print 'unit or building %s has a weapon spell with priority_vs on "blocker" or "inaccessible" - set "enable_ai_threatlist":1 on the unit or building for performance.' % specname
                if ('prev_target' in auto_spell['priority_vs']):
                    if not spec.get('enable_ai_threatlist', False):
                        error |= 1
                        print 'unit or building %s has a weapon spell with priority_vs "prev_target" - this does not work unless you set "enable_ai_threatlist":1 on the unit or building' % specname
            # detect melee weapons
            if ('projectile_color' in auto_spell) and (auto_spell['projectile_color'] is None) and \
               auto_spell.get('projectile_speed',1) < 0 and \
               ('priority_vs' in auto_spell) and ('inaccessible' in auto_spell['priority_vs']):
                range_ls = auto_spell['range'] if type(auto_spell['range']) is list else [auto_spell['range'],]*maxlevel
                MELEE_RANGE_LIMIT = 3.33
                for entry in range_ls:
                    if entry * gamedata['map']['range_conversion'] >= MELEE_RANGE_LIMIT:
                        error |= 1
                        print 'unit %s weapon spell is a melee attack, range should be less than %d, otherwise it can hit through barriers' % (specname, int(MELEE_RANGE_LIMIT/gamedata['map']['range_conversion']))
                        break

    return error

def get_num_levels(histogram, val):
    if isinstance(val, list):
        maxlevel = len(val)
        histogram[maxlevel] = 1 + histogram.get(maxlevel,0)

def check_levels(specname, spec):
    # list of fields that have array values that are NOT indexed by level
    # note: if you add something here, also update gameserver's Spec.compute_maxlevel() if the new field is also in GameObjectSpec
    ignore = ('limit', 'spells', 'gridsize', 'unit_collision_gridsize', 'exclusion_zone', 'equip_icon_offset', 'elite_marker_offset', 'equip_icon_delta', 'level_flag_offset', 'effects', 'click_bounds',
              # note: the 3D weapon_offset must be a per-level array, since there is no easy way to distinguish it from a 3-level scalar
              'max_ui_level',
              'defense_types', 'health_bar_dims', 'show_alliance_at', 'scan_counter_offset', 'research_categories', 'crafting_categories', 'enhancement_categories',
              'harvest_glow_pos', 'hero_icon_pos', 'muzzle_offset', 'limit_requires', 'permanent_auras',
              'upgrade_ingredients', 'remove_ingredients', 'research_ingredients')
    error = 0

    histogram = {}

    for name, val in spec.iteritems():
        if name == 'limit':
            # this one is indexed by CENTRAL COMPUTER level
            max_cc_level = len(gamedata['buildings'][gamedata['townhall']]['build_time'])
            if isinstance(val, list):
                if len(val) < max_cc_level:
                    error |= 1
                    print '%s "limit" array length does not have enough entries for all townhall levels! %d:%d' % (specname, len(val), max_cc_level)
            continue

        if name in ignore:
            continue

        if isinstance(val, list):
            get_num_levels(histogram, val)
        elif isinstance(val, dict) and name in ('applies_aura','equip_slots'):
            for n2, v2 in val.iteritems():
                get_num_levels(histogram, v2)

    popularity = 0
    maxlevel = 0
    for level in histogram.iterkeys():
        if histogram[level] > popularity:
            popularity = histogram[level]
            maxlevel = level

    for name, val in spec.iteritems():
        if name in ignore:
            continue
        if isinstance(val, list):
            if len(val) != maxlevel:
                error |= 1
                print 'spec array length mismatch! %s:%s' % (specname, name),
                print 'has %d entries but should probably have %d' % (len(val), maxlevel)
        elif isinstance(val, dict) and name in ('applies_aura','equip_slots'):
            for n2, v2 in val.iteritems():
                if isinstance(v2, list) and len(v2) != maxlevel:
                    error |= 1
                    print 'spec array length mismatch! %s:%s:%s' % (specname, name, n2),
                    print 'has %d entries but should probably have %d' % (len(v2), maxlevel)

    if spec.get('kind','') in ('mobile','building'):
        error |= check_level_progression(spec, maxlevel)

    if 'max_ui_level' in spec:
        if type(spec['max_ui_level']) is list:
            error |= check_cond_chain(spec['max_ui_level'], reason = '%s: max_ui_level' % specname)
            ls = [m for pred, m in spec['max_ui_level']]
        else:
            ls = [spec['max_ui_level'],]
        for entry in ls:
            if entry < 1 or entry > maxlevel:
                error |= 1; print '%s max_ui_level of %d is invalid - true max level is %d' % (specname, entry, maxlevel)

    return error, maxlevel

def resource_fields(name): return [name+'_'+resname for resname in gamedata['resources']]

def check_level_progression(spec, maxlevel):
    error = 0

    def make_array(stat):
        if type(stat) != list:
            return [abs(stat)]*maxlevel
        return map(abs, stat)

    tocheck = []

    LEVEL_PROGRESSION_FIELDS = \
                             resource_fields('storage') + resource_fields('provides') + resource_fields('produces') + [
        'provides_space', 'provides_donated_space', 'provides_total_space', 'provides_squad_space', 'provides_squads',
        'provides_inventory', 'provides_power', 'provides_foremen', 'manufacture_speed', 'max_hp'
        ]
    for FIELD in LEVEL_PROGRESSION_FIELDS:
        if FIELD in spec:
            tocheck.append([FIELD, make_array(spec[FIELD])])

    auto_spell_name = spec['spells'][0]
    spell = gamedata['spells'][auto_spell_name]
    if spell['activation'] == 'auto' or ('damage' in spell):
        for FIELD in ('damage','range','effective_range','accuracy','splash_range'):
            tocheck.append([auto_spell_name+':'+FIELD, make_array(spell.get(FIELD,0))])

    for i in xrange(maxlevel-1):
        improvement = False
        for name, stats in tocheck:
            if stats[i+1] > stats[i]:
                improvement = True
                break
        if not improvement and ('RESEARCH_FOR_FREE' not in spec['spells']) and ('CRAFT_FOR_FREE' not in spec['spells']):
            print '%s: no stat improvement from level %d->%d!' % (spec['name'], i+1, i+2)
            error |= 1

        for name, stats in tocheck:
            if stats[i] > stats[i+1]:
                print '%s: stat (%s) gets worse from level %d->%d!' % (spec['name'], name, i+1, i+2)
                error |= 1
    return error


def check_tech(specname, keyname, spec, maxlevel):
    error = 0
    if spec.get('name', None) != keyname:
        error |= 1
        print '%s:name must match the name outside the curly braces' % specname

    for ASSET in ('icon','splash_image'):
        if (ASSET in spec):
            asset_list = spec[ASSET] if type(spec[ASSET]) is list else [spec[ASSET],]
            for a in asset_list:
                error |= require_art_asset(a, specname+':'+ASSET)

    if ('associated_unit' not in spec) and ('splash_image' not in spec) and ('icon' not in spec):
        error |= 1; print '%s: needs either an associated_unit, splash_image, or icon for display purposes' % (specname)

    if not isinstance(spec['research_time'], list):
        error |= 1
        print '%s:research_time MUST be a per-level list' % specname

    if ('associated_item' in spec):
        itemlist = spec['associated_item'] if type(spec['associated_item']) is list else [spec['associated_item'],]*len(spec['research_time'])
        for item in itemlist:
            if item not in gamedata['items']:
                error |= 1; print '%s:associated_item "%s" not found in gamedata.items' % (specname, item)

    if 'applies_aura' in spec:
        error |= 1
        print '%s: uses obsolete applies_aura field, switch to new effects system' % specname

    if 'effects' in spec:
        for effect in spec['effects']:
            if effect['code'] != 'modstat':
                error |= 1
                print '%s: uses invalid effect code %s' % effect['code']
            error |= check_modstat(effect, specname)

    if specname.endswith('_production'):
        if 'associated_unit' in spec:
            if spec['associated_unit'] in gamedata['units']:
                unit_maxlevel = len(gamedata['units'][spec['associated_unit']]['max_hp'])
                if unit_maxlevel != maxlevel:
                    error |= 1
                    print '%s: number of levels (%d) does not match associated unit (%d)' % (specname, maxlevel, unit_maxlevel)
            else:
                print 'production tech %s is associated with missing unit %s' % (specname, spec['associated_unit'])
                error |= 1
        else:
            error |= 1
            print 'production tech %s is not associated with any unit' % specname

    # check resource requirement vs CC level
    if verbose:
        for lev in xrange(1,len(spec['research_time'])+1):
            cc_requirement = GameDataUtil.get_cc_requirement(gamedata, spec['requires'], lev) if ('requires' in spec) else 0
            for res in gamedata['resources']:
                cost = spec['cost_'+res][lev-1] if isinstance(spec['cost_'+res],list) else spec['cost_'+res]
                if cost > MAX_RESOURCE_COST:
                    error |= 1
                    print 'tech %s level %d has %s cost exceeding global limit of %d' % (specname, lev, res, MAX_RESOURCE_COST)
                if cc_requirement > 0 and cost > MAX_STORAGE[res][cc_requirement-1]:
                    error |= 1
                    print 'tech %s level %d requires CC L%d but has %s cost of %d, which exceeds max storage capacity at that CC level of %d' % (specname, lev, cc_requirement, res, cost, MAX_STORAGE[res][cc_requirement-1])

    if 'requires' in spec:
        req = spec['requires'] if type(spec['requires']) is list else [spec['requires'],]
        for r in req:
            error |= check_predicate(r, reason = specname+':requires')
    for FIELD in ('activation', 'show_if'):
        if FIELD in spec:
            error |= check_predicate(spec[FIELD], reason = specname+':'+FIELD)

    # "activation" is deprecated
    if 'activation' in spec:
        error |= 1; print '%s "activation" is deprecated, change to "show_if"' % specname

    if 'completion' in spec:
        comp = spec['completion'] if type(spec['completion']) is list else [spec['completion'],]
        for c in comp:
            error |= check_consequent(c, reason = specname+':completion', context='tech')

    if 'research_category' in spec:
        found = False
        for entry in sum(gamedata['strings']['research_categories'].values(), []):
            if entry['name'] == spec['research_category']:
                found = True
                break
        if not found:
            error |= 1; print '%s research category %s not found in gamedata.strings.research_categories.*.name' % (specname, spec['research_category'])

    return error

def check_enhancement(specname, keyname, spec, maxlevel):
    error = 0
    if spec.get('name', None) != keyname:
        error |= 1
        print '%s:name must match the name outside the curly braces' % specname

    for ASSET in ('icon','splash_image'):
        if (ASSET in spec):
            asset_list = spec[ASSET] if type(spec[ASSET]) is list else [spec[ASSET],]
            for a in asset_list:
                error |= require_art_asset(a, specname+':'+ASSET)

    if 0 and ('associated_building' not in spec) and ('splash_image' not in spec) and ('icon' not in spec):
        error |= 1; print '%s: needs either an associated_building, splash_image, or icon for display purposes' % (specname)

    if not isinstance(spec['enhance_time'], list):
        error |= 1
        print '%s:enhance_time MUST be a per-level list' % specname

    if 'effects' in spec:
        for effect in spec['effects']:
            if effect['code'] != 'modstat':
                error |= 1
                print '%s: uses invalid effect code %s' % effect['code']
            error |= check_modstat(effect, specname)

    # check resource requirement vs CC level
    if verbose:
        for lev in xrange(1,len(spec['enhance_time'])+1):
            cc_requirement = GameDataUtil.get_cc_requirement(gamedata, spec['requires'], lev) if ('requires' in spec) else 0
            for res in gamedata['resources']:
                cost = spec['cost_'+res][lev-1] if isinstance(spec['cost_'+res],list) else spec['cost_'+res]
                if cost > MAX_RESOURCE_COST:
                    error |= 1
                    print 'enhancement %s level %d has %s cost exceeding global limit of %d' % (specname, lev, res, MAX_RESOURCE_COST)
                if cc_requirement > 0 and cost > MAX_STORAGE[res][cc_requirement-1]:
                    error |= 1
                    print 'enhancement %s level %d requires CC L%d but has %s cost of %d, which exceeds max storage capacity at that CC level of %d' % (specname, lev, cc_requirement, res, cost, MAX_STORAGE[res][cc_requirement-1])

    for FIELD in ('requires', 'show_if'):
        if FIELD in spec:
            req = spec[FIELD] if type(spec[FIELD]) is list else [spec[FIELD],]
            for r in req:
                error |= check_predicate(r, reason = specname+':'+FIELD)

    if 'completion' in spec:
        comp = spec['completion'] if type(spec['completion']) is list else [spec['completion'],]
        for c in comp:
            error |= check_consequent(c, reason = specname+':completion', context='tech')

    return error

def check_aura(auraname, spec, maxlevel):
    error = 0
    if spec['name'] != ':'.join(auraname.split(':')[1:]):
        error |= 1
        print '%s:name mismatch' % auraname
    if ('icon' in spec) and spec['icon'] != 'gamebucks_inventory_icon':
        error |= require_art_asset(spec['icon'], auraname+':icon')
    if ('_sale' in spec['name']) or ('_contender' in spec['name']) or spec['name'] == 'damage_protection':
        if spec.get('limited', True):
            error |= 1
            print '%s: should have "limited": 0' % (auraname)
    if ('affects_manufacture_category' in spec) and (spec['affects_manufacture_category'] not in ('ALL','rovers','transports','starcraft')):
        error |= 1
        print '%s:affects_manufacture_category is invalid (must be ALL, rovers, transports, or starcraft)' % (auraname)
    if ('affects_kind' in spec) and (spec['affects_kind'] not in ('ALL','mobile','building')):
        error |= 1
        print '%s:affects_kind is invalid (must be ALL, mobile, or building)' % (auraname)
    if ('affects_unit' in spec) and (spec['affects_unit'] != 'ALL'):
        unit_list = spec['affects_unit'] if type(spec['affects_unit']) is list else [spec['affects_unit'],]
        for unit in unit_list:
            if unit not in gamedata['units']:
                error |= 1; print '%s:affects_unit (%s) is invalid' % (auraname, unit)
    if 'on_apply' in spec:
        if not spec.get('server',False):
            error |= 1; print '%s: has on_apply but server != 1' % auraname
        error |= check_consequent(spec['on_apply'], reason = 'aura %s: on_apply' % auraname, context='aura')

    if 'on_click' in spec:
        error |= check_consequent(spec['on_click'], reason = 'aura %s: on_click' % auraname, context='aura')

    if 'code' in spec:
        replacement = 'unknown (ask Dan)'
        print '%s: obsolete code "%s" - replace with: %s' % (auraname,spec['code'],SpinJSON.dumps(replacement))
    elif 'effects' in spec:
        for effect in spec['effects']:
            # server-side codes (implemented in server.py)
            if effect['code'] in ('modstat', 'hold_unit_space', 'trophy_pvp_decay',
                                  'sandstorm_max', 'base_damage_win_condition'):
                if not spec.get('server',False):
                    error |= 1; print '%s: uses a server-side effect code but server != 1' % auraname
                if spec.get('client',False):
                    error |= 1; print '%s: uses a server-side effect code but client != 0' % auraname

            # client-side codes (implemented in main.js)
            elif effect['code'] in ('speed_boosted', 'defense_boosted', 'defense_weakened', 'radiation_hardened',
                                    'frozen', 'ice_shielded', 'ice_encrusted', 'moving_in_swamp', 'swamp_shielded',
                                    'rate_of_fire_boosted', 'damage_boosted',
                                    'armor_boosted', 'damage_booster', 'defense_booster', 'stunned', 'disarmed', 'hacked', 'range_reduction', 'weak_zombie',
                                    'on_fire', 'projectile_speed_reduced', 'cast_spell_continuously'):
                if not spec.get('client',False):
                    error |= 1; print '%s: uses a client-side effect code but client != 1' % auraname
                if spec.get('server',False):
                    error |= 1; print '%s: uses a client-side effect code but server != 0' % auraname
            else:
                error |= 1; print '%s: uses invalid effect code %s' % (auraname, effect['code'])

            if effect['code'] == 'modstat':
                error |= check_modstat(effect, auraname, effect.get('affects', None))

            if 'apply_interval' in effect:
                int_cd = int(effect['apply_interval']*100.0+0.5)
                if (int_cd % 25) != 0:
                    error |= 1; print '%s: effect has bad apply_interval %f - it must be a multiple of 0.25' % (auraname, effect['apply_interval'])

    if 'ends_on' in spec:
        has_cons = False
        if spec['ends_on'] not in ('session_change', 'battle_end', 'recalc_stattab', 'damage_protection'):
            error |= 1; print '%s: invalid ends_on code' % auraname
        if spec['ends_on'] == 'battle_end':
            for outcome in ('defeat','victory'):
                key = 'on_battle_end_'+outcome
                if key in spec:
                    error |= check_consequent(spec[key], reason = 'aura %s: key' % auraname, context='aura')
                    has_cons = True

        if has_cons and (not spec.get('server',False)):
            error |= 1; print '%s: has ends_on with consequent but server != 1' % auraname

    if ('code' not in spec) and ('effects' not in spec) and ('ends_on' not in spec) and ('on_apply' not in spec):
        if spec.get('server',False) or spec.get('client',False):
            error |= 1; print '%s: has no effects but is set for client or server processing' % auraname

    return error

EFFECT_TYPES = set(['combine', 'explosion', 'sound', 'shockwave', 'particles', 'camera_shake', 'combat_text', 'phantom_unit', 'random', 'particle_magnet', 'drag_field','library'])
def check_visual_effect(name, effect):
    error = 0
    if effect is None: # "null" is valid here
        return error
    if effect['type'] not in EFFECT_TYPES:
        error |= 1; print '%s has bad "type" %s' % (name, effect['type'])
    elif effect['type'] in ('combine', 'random'):
        for subeffect in effect['effects']:
            error |= check_visual_effect(name, subeffect)
    elif effect['type'] == 'library':
        if effect.get('name','MISSING') not in gamedata['client']['vfx']:
            error |= 1; print '%s refers to "%s" not found in gamedata.client.vfx' % (name, effect.get('name','MISSING'))
    elif effect['type'] == 'combat_text':
        if 'ui_name' not in effect:
            error |= 1; print '%s needs a "ui_name"' % (name)
    elif effect['type'] == 'sound':
        if 'assets' in effect:
            assetlist = effect['assets']
        elif 'sprite' in effect:
            assetlist = [effect['sprite']]
        else:
            error |= 1; print '%s has type "sound" but no "assets" list' % (name)
            assetlist = []
        for assetname in assetlist:
            error |= require_art_asset(assetname, name+':sound')
            if not error:
                if 'audio' not in gamedata['art'][assetname]['states']['normal']:
                    error |= 1; print '%s calls for sound %s but art.json entry has no "audio" field' % (name, assetname)
    elif effect['type'] == 'explosion':
        if effect['sprite'] != '%OBJECT_SPRITE':
            error |= require_art_asset(effect['sprite'], name+':sprite')
    elif effect['type'] == 'phantom_unit':
        if effect['spec'] not in gamedata['units']:
            error |= 1; print '%s refers to bad spec %s' % (name, effect['spec'])

    if 'child' in effect:
        error |= check_visual_effect(name+':child', effect['child'])

    return error

def check_spell(spellname, spec):
    error = 0
    icon = spec.get('new_store_icon', spec.get('icon', None))
    if icon:
        error |= require_art_asset(icon, spellname+':icon')

    if 'new_store_tip_item' in spec and spec['new_store_tip_item'] not in gamedata['items']:
        error |= 1
        print '%s:new_store_tip_item ("%s") is missing from items.json' % (spellname, spec['new_store_tip_item'])

    if 'loot_table' in spec and spec['loot_table'] not in gamedata['loot_tables']:
        error |= 1; print '%s:loot_table ("%s") is missing from loot tables' % (spellname, spec['loot_table'])

    if 'give_units' in spec:
        for name, qty in spec['give_units'].iteritems():
            if name == 'level_by_cc': continue
            if name not in gamedata['units']:
                print '%s:give_units refers to invalid unit "%s"' % (spellname, name)

    if 'impact_aura' in spec:
        error |= 1
        print '%s: uses old impact_aura, needs to be changed to impact_auras array' % (spellname)
    if 'impact_auras' in spec:
        for aura in spec['impact_auras']:
            if aura['spec'] not in gamedata['auras']:
                error |= 1
                print '%s:impact_aura refers to missing aura %s' % (spellname, aura['spec'])

    if spellname.endswith('_SHOOT') and ('cooldown' not in spec):
        error |= 1
        print '%s is missing a "cooldown"' % (spellname)

    if ('cooldown_interval' in spec) != ('cooldown_origin' in spec):
        error |= 1; print '%s must have both cooldown_origin and cooldown_interval' % spellname

    if spec.get('activation',None) == 'auto' or spec.get('code',None) == 'pbaoe' or ('range' in spec) or ('splash_range' in spec):
        if spec.get('name',None) != spellname.split(':')[1]:
            error |= 1; print '%s: "name" needs to be set to "%s"' % (spellname, spellname.split(':')[1])

    for EFFECT in ('muzzle_flash_effect', 'impact_visual_effect'):
        if EFFECT in spec:
            error |= check_visual_effect(spellname+':'+EFFECT, spec[EFFECT])

    for n in ('cooldown', 'impact_aura_duration'):
        if n in spec:
            cdlist = spec[n]
            if type(cdlist) is not list:
                cdlist = [cdlist,]
            for cd in cdlist:
                int_cd = int(cd*100.0+0.5)
                if (int_cd % 25) != 0:
                    error |= 1
                    print 'spell %s has bad %s value %f - it must be a multiple of 0.25' % (spellname, n, cd)

    if 'projectile_asset' in spec:
        error |= require_art_asset(spec['projectile_asset'], spellname+':projectile_asset')

    for PRED in ('requires', 'show_if'):
        if PRED in spec:
            error |= check_predicate(spec[PRED], reason = spellname+':'+PRED)
    for CONS in ('pre_activation', 'consequent'):
        if CONS in spec:
            error |= check_consequent(spec[CONS], reason = spellname+':'+CONS)

    if 'price_currency' in spec:
        error |= 1; print 'spell %s has "price_currency" but this should just be "currency"' % spellname

    return error

def check_region(name, data):
    error = 0
    if data['id'] != name:
        error |= 1
        print '%s: id mismatch' % name
    if data['terrain'] not in gamedata['region_terrain']:
        error |= 1; print '%s: missing terrain %s' % (name, data['terrain'])

    error |= require_art_asset(data['bg_image'], name+':bg_image')

    if ('continent_id' not in data) or data['continent_id'] not in gamedata['continents']:
        error |= 1
        print '%s: missing or invalid continent_id' % name
    for PRED in ('auto_join_if', 'prefer_if', 'show_if', 'requires', 'enable_battle_protection_if', 'enable_pvp_level_gap_if', 'ladder_on_map_if', 'ladder_on_map_if_defender'):
        if PRED in data:
            error |= check_predicate(data[PRED], reason = 'region %s: %s' % (name, PRED))
    if 'on_enter' in data: error |= check_consequent(data['on_enter'], reason = 'region %s: on_enter' % name)
    for COND in ('ladder_point_minloss_scale',
                 'loot_attacker_gains_scale_if_defender', 'loot_attacker_gains_scale_if_attacker',
                 'loot_defender_loses_scale_if_defender', 'loot_defender_loses_scale_if_attacker'):
        if COND in data and type(COND) is list:
            error |= check_cond_chain(data[COND], reason = 'region %s: %s' % (name, COND))
    return error

def check_region_name(name, context=None):
    error = 0
    if name not in gamedata['regions']:
        error |= 1
        print '%s: %s is not a region' % (context, name)
    return error

def check_continent(name, data):
    error = 0
    if data['id'] != name:
        error |= 1
        print '%s: id mismatch' % name
    return error

def check_leaderboard(leaderboard):
    error = 0
    for cat_name, data in leaderboard['categories'].iteritems():
        if 'show_if' in data:
            error |= 1; print 'leaderboard: stat %s has obsolete "show_if" field, replace with "leaderboard_show_if"/"statistics_show_if"' % (cat_name)
        for PRED in ('leaderboard_show_if','statistics_show_if'):
            if PRED in data:
                error |= check_predicate(data[PRED], reason = 'leaderboard:categories:'+cat_name+':'+PRED)
        if 'statistics_show_if' in data and (not 'group' in data):
            error |= 1; print 'leaderboard: stat %s has "statistics_show_if" but also needs a "group"' % (cat_name)
        if 'group' in data and (not 'statistics_show_if' in data):
            error |= 1; print 'leaderboard: stat %s has "group" but no "statistics_show_if"' % (cat_name)
        if 'challenge_icon' in data:
            error |= require_art_asset(data['challenge_icon'], reason = 'leaderboard:categories:'+cat_name+':challenge_icon')
        if 'group' in data:
            if data['group'] not in leaderboard['stat_groups']:
                error |= 1; print 'leaderboard: stat %s has invalid group %s' % (cat_name, data['group'])
    return error

def check_scores2_stat(stat, reason):
    error = 0
    if stat['name'] not in gamedata['strings']['leaderboard']['categories']:
        error |= 1; print '%s: stat %s not found in gamedata.strings.leaderboard.categories' % (reason, stat['name'])
    if stat['time_scope'] not in ('week','season','ALL'):
        error |= 1; print '%s: bad stat time_scope %s' % (reason, stat['time_scope'])
    if stat['space_scope'] not in ('region','continent','ALL'):
        error |= 1; print '%s: bad stat space_scope %s' % (reason, stat['space_scope'])
    return error

def check_manufacture_category(path, spec):
    error = 0
    if 'show_if' in spec:
        error |= check_predicate(spec['show_if'], reason=path+':show_if')
    return error

def check_research_category(path, spec):
    error = 0
    if 'show_if' in spec:
        error |= check_predicate(spec['show_if'], reason=path+':show_if')
    return error

def check_crafting_category(catname, spec):
    error = 0
    for cat in spec.get('category_group',[]):
        if cat not in gamedata['crafting']['categories']:
            error |= 1; print '%s: category_group has invalid entry "%s"' % (catname, cat)
    for BLDG in ('unlock_building_for_ui', 'delivery_building_for_ui'):
        if BLDG in spec:
            if spec[BLDG] not in gamedata['buildings']:
                error |= 1; print '%s: %s "%s" not a valid building' % (catname, BLDG, spec[BLDG])
    if spec['delivery'] == 'building_slot':
        if spec['delivery_slot_type'] not in gamedata['strings']['equip_slots']:
            error |= 1; print '%s: invalid delivery_slot_type %s' % (catname, spec['delivery_slot_type'])
        if 'delivery_building_for_ui' not in spec:
            error |= 1; print '%s: delivery_building_For_ui is required' % (catname,)
    return error

def check_crafting_recipe(recname, spec):
    error = 0
    if spec['name'] != recname.split(':')[-1]:
        error |= 1; print '%s:name mismatch' % recname
    for FIELD in ('craft_time', 'cost', 'product','crafting_category'):
        if FIELD not in spec:
            error |= 1; print '%s: missing field %s' % (recname, FIELD)

    prod_list = spec['product'] if type(spec['product'][0]) is list else [spec['product'],]
    max_level = spec.get('max_level', 1)

    for FIELD in ('craft_time', 'cost'):
        if max_level > 1 and type(spec[FIELD]) is list and len(spec[FIELD]) != max_level:
            error |= 1; print '%s: list of %s does not match max_level %d' % (recname, FIELD, max_level)

    for FIELD in ('ingredients', 'product'):
        if FIELD in spec and max_level > 1 and type(spec[FIELD][0]) is list and len(spec[FIELD]) != max_level:
            error |= 1; print '%s: list of %s does not match max_level %d' % (recname, FIELD, max_level)

    if ('ui_name' not in spec):
        if spec['crafting_category'] == 'fishing':
            error |= 1; print '%s: ui_name is mandatory for fishing recipes' % recname
        if prod_list[0] and (not prod_list[0][0].get('spec',None)):
            error |= 1; print '%s: has no ui_name but product is not a single item' % recname

    if spec['crafting_category'] not in gamedata['crafting']['categories']:
        error |=1; print '%s: uses unknown crafting_category "%s"' % (recname, spec['crafting_category'])

    if spec['crafting_category'] == 'turret_heads':
        if 'consumes_power' not in spec:
            error |= 1; print '%s: missing consumes_power (while crafting)' % (recname,)

    if 'associated_item' in spec:
        if spec['associated_item'] not in gamedata['items']:
            error |=1; print '%s: associated_item % not found' % (recname, spec['associated_item'])
        else:
            item_spec = gamedata['items'][spec['associated_item']]
            if max_level != item_spec.get('max_level',1):
                error |=1; print '%s: max_level %d does not match associated_item %s max_level %d' % (recname, max_level, spec['associated_item'], item_spec.get('max_level',1))

    if ('associated_item_set' in spec):
        if spec['associated_item_set'] not in gamedata['item_sets']:
            error |=1; print '%s: has invalid associated_item_set "%s"' % (recname, spec['associated_item_set'])
        else:
            if prod_list[0] and prod_list[0][0].get('spec',None) not in gamedata['item_sets'][spec['associated_item_set']]['members'] and \
               len(gamedata['item_sets'][spec['associated_item_set']]['members']) > 0: # ignore empty item sets that are used only for crafting recipes
                error |=1; print '%s: has associated_item_set "%s" but its product is not a member of that set' % (recname, spec['associated_item_set'])

    if 'associated_tech' in spec and spec['associated_tech'] not in gamedata['tech']:
        error |= 1; print '%s: associated_tech "%s" not found in tech.json' % (recname, spec['associated_tech'])

    for level in xrange(max_level):
        cost = GameDataUtil.get_leveled_quantity(spec['cost'], level)
        if cost is None: continue # null cost -> not craftable
        for res, amount in cost.iteritems():
            if res not in gamedata['resources']:
                error |= 1; print '%s: cost uses unknown resource %s' % (recname, res)
        if 'ingredients' in spec:
            ingr_list = spec['ingredients'][level-1] if type(spec['ingredients'][0]) is list else spec['ingredients']
            for entry in ingr_list:
                if entry['spec'] not in gamedata['items']:
                    error |= 1; print '%s: ingredients uses unknown item %s' % (recname, entry['spec'])
                else:
                    ingr_spec = gamedata['items'][entry['spec']]
                    if entry.get('stack',1) > ingr_spec.get('max_stack',1):
                        error |= 1; print '%s: ingredient "%r" stack cannot be greater than item\'s max_stack' % (recname, entry)

        prod_table = spec['product'][level-1] if type(spec['product'][0]) is list else spec['product']
        error |= check_loot_table(prod_table, reason = recname+':product')

        for FIELD in ('show_if', 'requires'):
            if FIELD in spec:
                error |= check_predicate(GameDataUtil.get_leveled_quantity(spec[FIELD], level), reason = recname+':'+FIELD)

        for CONS in ('completion', 'on_start'):
            if CONS in spec:
                error |= check_consequent(GameDataUtil.get_leveled_quantity(spec[CONS], level), recname+':'+CONS, context='crafting_recipe')

        if 'start_effect' in spec:
            error |= check_visual_effect('%s:start_effect' % recname, GameDataUtil.get_leveled_quantity(spec['start_effect'], level))

    return error

def check_item_set(setname, spec):
    error = 0
    if spec['name'] != setname.split(':')[1]:
        error |= 1; print '%s:name mismatch' % setname
    for member in spec['members']:
        if member not in gamedata['items']:
            error |= 1; print '%s:member %s not in items' % (setname, member)
        if gamedata['items'][member].get('item_set',None) != spec['name']:
            error |= 1; print '%s:member %s does not list %s as its item_set' % (setname, member, setname)
    if 'bonus_aura' in spec:
        if len(spec['bonus_aura']) != len(spec['members']):
            error |= 1; print '%s:bonus_aura list length does not match # of members'
        for aura_name in spec['bonus_aura']:
            if (aura_name is not None):
                if (aura_name not in gamedata['auras']):
                    error |= 1; print '%s:bonus_aura refers to missing aura %s' % (setname, aura_name)
                elif gamedata['auras'][aura_name].get('ends_on', None) != 'recalc_stattab':
                    error |= 1; print '%s:bonus_aura %s needs to have "ends_on":"recalc_stattab"' % (setname, aura_name)
    if 'ui_description' not in spec and gamedata['game_id'] not in ('tr','dv','mf2'): # ignore legacy games
        error |= 1; print '%s needs to have a "ui_description". See other item sets for examples.' % (setname)
    if 'icon' in spec:
        error |= require_art_asset(spec['icon'], setname+':icon')

    return error

level_re = re.compile('(?P<root>.+)_L(?P<level>[0-9]+)(_SHOOT)?$')

def check_item(itemname, spec):
    error = 0
    if spec['name'] != itemname.split(':')[1]:
        error |= 1
        print '%s:name mismatch' % itemname

    max_level = spec.get('max_level', 1)

    if 'associated_crafting_recipes' in spec:
        for asc in spec['associated_crafting_recipes']:
            if asc not in gamedata['crafting']['recipes']:
                error |=1; print '%s: associated_crafting_recipe %s not found' % (itemname, asc)
            else:
                recipe_spec = gamedata['crafting']['recipes'][asc]
                if 'max_level' in recipe_spec and recipe_spec['max_level'] != max_level:
                    error |=1; print '%s: max_level %d does not match associated_crafting_recipe %s max_level %d' % (itemname, max_level, asc, recipe_spec.get('max_level',1))


    matches = level_re.match(itemname)
    if matches:
        level = int(matches.group('level'))
        if 'level' in spec and spec['level'] != level:
            error |= 1; print '%s: probably a typo: "level" number %d does not match item name suffix "%s"' % (itemname, level, itemname)

        for FIELD in ('ui_name', 'icon',):
            ui_matches = level_re.match(spec[FIELD])
            if ui_matches:
                ui_level = int(ui_matches.group('level'))
                if ui_level != level:
                    error |= 1; print '%s: probably a typo: "%s" Lxx number suffix does not match item name "%s"' % (itemname, FIELD, itemname)

    if 'unit_icon' in spec:
        error |= 1
        print '%s:unit_icon is obsolete, replace with "icon":"inventory_%s"' % (itemname, spec['unit_icon'])
#        if spec['unit_icon'] not in gamedata['units']:
#            error |= 1
#            print '%s:unit_icon is missing from units.json' % itemname
    elif spec['icon'] != 'gamebucks_inventory_icon':
        error |= require_art_asset(spec['icon'], itemname+':icon')

    if type(spec['ui_description']) is list:
        ui_descr_list = [val for pred, val in spec['ui_description']]
    else:
        ui_descr_list = [spec['ui_description']]

    if ('item_set' in spec):
        if (spec['item_set'] not in gamedata['item_sets']):
            error |= 1; print '%s:item_set ("%s") is missing from item_sets.json' % (itemname, spec['item_set'])

        set_spec = gamedata['item_sets'][spec['item_set']]
        if spec['name'] not in set_spec['members']:
            error |= 1; print '%s is not listed in item_set "%s" members' % (itemname, spec['item_set'])
        if 'ui_name' in set_spec:
            for ui_descr in ui_descr_list:
                if set_spec['ui_name'] not in ui_descr:
                    error |= 1; print '%s\'s ui_description does not mention the name of the set it belongs to ("%s")' % (itemname, set_spec['ui_name'])

    if 'limited_equipped' in spec:
        # note: while the engine can deal with provides_limited_equipped on any building,
        # the client currently assumes only the townhall has this stat
        thspec = gamedata['buildings'][gamedata['townhall']]
        if ('provides_limited_equipped' not in thspec) or (spec['limited_equipped'] not in thspec['provides_limited_equipped']):
            error |= 1; print '%s has limited_equipped "%s" but the townhall does not list it in provides_limited_equipped' % (itemname, spec['limited_equipped'])

        # this is also just a convention from TR, to avoid typos
        if spec['limited_equipped'] not in spec['name']:
            error |= 1; print '%s possible typo in limited_equipped, it looks different from the item name' % itemname

    if ('store_icon' in spec):
        error |= require_art_asset(spec['store_icon'], itemname+':store_icon')

    if spec.get('category') == 'token':
        if 'store_icon' not in spec:
            error |= 1; print '%s: token-like items should have a "store_icon" (for Region Map display)' % (itemname,)

    if 'requires' in spec:
        error |= check_predicate(spec['requires'], reason = 'item %s: requires' % itemname)

    if 'refundable_when' in spec:
        error |= check_predicate(spec['refundable_when'], reason = 'item %s: refundable_when' % itemname)

    if 'refund' in spec:
        error |= check_loot_table(spec['refund'], reason = 'refund')

    if 'pre_use' in spec:
        error |= check_consequent(spec['pre_use'], reason = 'item %s: pre_use')

    if 'use' in spec:
        uselist = spec['use'] if type(spec['use']) is list else [spec['use']]
        for use in uselist:
            if 'spellname' in use:
                spellname = use['spellname']

                if spellname == 'ALLIANCE_GIFT_ITEM':
                    spellarg = use['spellarg']
                    assert len(spellarg) == 1
                    error |= 1
                    replacement = {'spellname':'ALLIANCE_GIFT_LOOT', 'spellarg': [{'loot':[{'spec':spellarg[0]['spec']}]}]}
                    print '%s: ALLIANCE_GIFT_ITEM is obsolete, please replace the "use" value of this item with the following:\n\t"use": %s\n' % (itemname, SpinJSON.dumps(replacement))

                elif spellname not in gamedata['spells']:
                    error |= 1; print '%s: spell "%s" not in spells.json' % (itemname, spellname)

                if spellname == 'ALLIANCE_GIFT_LOOT':
                    spellarg = use['spellarg']
                    if len(spellarg) != 1 or type(spellarg[0]) is not dict or ('loot' not in spellarg[0]):
                        error |= 1; print '%s: bad ALLIANCE_GIFT_LOOT syntax - the "spellarg" list must have one element, which must have the form {"loot":[loot table], (OPTIONAL: "item_expire_at":12345/"item_duration":12345) }' % itemname
                    error |= check_loot_table(spellarg[0]['loot'], reason = '%s:ALLIANCE_GIFT_LOOT' % itemname,
                                              expire_time = spellarg[0].get('item_expire_at',-1), duration = spellarg[0].get('item_duration',-1))

                elif spellname == 'APPLY_AURA':
                    spellarg = use['spellarg']
                    if spellarg[1] not in gamedata['auras']:
                        error |= 1; print '%s: aura "%s" not in auras.json' % (itemname, spellarg[1])
                    aura = gamedata['auras'][spellarg[1]]

                    for effect in aura['effects']:
                        # some items override the effect strength of the aura - check these here
                        if effect['code'] == 'modstat' and ('strength' not in effect):
                            temp = copy.copy(effect)
                            temp['strength'] = spellarg[2]

                            # determining what the aura affects is pretty complicated :(
                            affects = spellarg[0]
                            if ('affects' in aura):
                                affects = aura['affects']
                            elif ('affects_unit' in aura) or ('affects_manufacture_category' in aura) or ('affects_kind' in aura) or ('affects_building' in aura):
                                affects = None

                            error |= check_modstat(temp, itemname, affects = affects)
                elif spellname == 'CLIENT_CONSEQUENT':
                    error |= check_consequent(use['spellarg'], reason = 'item %s: use' % itemname, context = 'item')

                # missiles
                elif spellname in gamedata['spells'] and gamedata['spells'][spellname]['activation'] == 'targeted_area':
                    if ('analytics_value' not in spec) and (gamedata['game_id'] in ('tr','dv')):
                        error |= 1; print '%s: missile needs an "analytics_value"' % (itemname,)

            if 'consequent' in use:
                error |= check_consequent(use, reason = 'item %s: use' % itemname, context = 'item')

    if 'equip' in spec:
        if ('boost_stat' in spec) or ('boost_type' in spec) or ('effects' not in spec['equip']):
            error |= 1; print '%s: old single effect item format. (boost_stat and boost_type entry, no "effects" list)' % (itemname,)
        if type(spec['equip']['effects']) is not list:
            error |= 1; print '%s: "effects" must be a list' % (itemname,)

        for effect in spec['equip']['effects']:
            if 'code' not in effect:
                error |= 1; print '%s: effect has no "code"' % (itemname,)
            if effect['code'] == 'apply_player_aura':
                if effect['aura_name'] not in gamedata['auras']:
                    error |= 1; print '%s: aura_name "%s" not found in auras.json' % (itemname, effect['aura_name'])
            elif effect['code'] != 'modstat':
                replacement = 'unknown (ask Dan)'
                if effect['code'] == 'resist_boosted':
                    replacement = {'code':'modstat', 'stat':'damage_taken', 'method': '*=(1-strength)', 'strength': effect['strength']}
                elif effect['code'] == 'rad_shielded':
                    replacement = {'code':'modstat', 'stat':'damage_taken_from:radiation', 'method': '*=(1-strength)', 'strength': effect['strength']}
                elif effect['code'] == 'ice_shielded':
                    replacement = {'code':'modstat', 'stat':'ice_effects', 'method': '*=(1-strength)', 'strength': effect['strength']}
                elif effect['code'] == 'anti_missile':
                    replacement = {'code':'modstat', 'stat':'anti_missile', 'method': '*=(1-strength)', 'strength': effect['strength']}
                elif effect['code'] == 'radice_shielded':
                    replacement = [{'code':'modstat', 'stat':'damage_taken_from:radiation', 'method': '*=(1-strength)', 'strength': effect['strength']},
                                   {'code':'modstat', 'stat':'ice_effects', 'method': '*=(1-strength)', 'strength': effect['strength']}]
                elif effect['code'] == 'damage_boosted':
                    replacement = {'code':'modstat', 'stat':'weapon_damage', 'method': '*=(1+strength)', 'strength': effect['strength']}
                elif effect['code'] == 'on_destroy':
                    replacement = {'code':'modstat', 'stat':'on_destroy', 'method':'concat', 'strength':[effect['consequent']]}
                print '%s: obsolete effect code "%s" - replace with: %s' % (itemname,effect['code'], SpinJSON.dumps(replacement))
            if effect['code'] == 'modstat':
                error |= check_modstat(effect, reason = 'item %s: effects' % itemname,
                                       expect_level = spec.get('level', None),
                                       expect_item_sets = set((spec['item_set'],)) if 'item_set' in spec else None)
                if effect['stat'] == 'permanent_auras' and not any(x['kind'] == 'building' for x in spec['equip'].get('compatible',[spec['equip']])):
                    error |= 1; print '%s: permanent_auras mods are not supported on mobile units (buildings only)' % itemname
                if effect['stat'] == 'on_destroy' and 'strength' in effect:
                    for cons in effect['strength']:
                        if cons['consequent'] == 'SPAWN_SECURITY_TEAM':
                            if cons.get('persist') and not all('ersist' in ui_descr for ui_descr in ui_descr_list):
                                error |= 1; print '%s\'s ui_description does not mention that its security team is persistent' % (itemname,)

            if 'consequent' in effect:
                error |= check_consequent(effect['consequent'], reason = 'item %s: effects' % itemname)

        equip = spec['equip']
        # check compatibility criteria
        if 'compatible' in equip:
            crit_list = equip['compatible']
        else:
            crit_list = [equip] # legacy raw outer JSON
        for crit in crit_list:
            if crit['kind'] in ('building','mobile') and ('name' in crit):
                source = {'building':'buildings', 'mobile':'units'}[crit['kind']]
                if crit['name'] not in gamedata[source]:
                    error |= 1; print '%s: invalid %s object name %s' % (itemname, crit['kind'], crit['name'])
                else:
                    host_spec = gamedata[source][crit['name']]
                    if 'slot_type' not in crit:
                        error |= 1;  print '%s: equip is missing a "slot_type"' % (itemname,)
                    elif (not crit.get('dev_only',False)) and (crit['slot_type'] not in host_spec.get('equip_slots',{})):
                        error |= 1; print '%s: equips to %s but %s.json is missing a "%s" slot for it' % (itemname, crit['name'], source, crit['slot_type'])
                    elif ('min_level' in crit):
                        level_list = crit['min_level'] if isinstance(crit['min_level'],list) else [crit['min_level'],]
                        if len(level_list) != 1 and len(level_list) != spec['max_level']:
                                error |= 1; print '%s: compatible min_level criteria has wrong length' % (itemname,)
                        for min_level in level_list:
                            if len(host_spec[GameDataUtil.MAX_LEVEL_FIELD[source]]) < min_level:
                                error |= 1; print '%s: equips to %s L%d+ but the unit/building does not actually upgrade that high' % (itemname, crit['name'], min_level)

            if crit.get('slot_type',None) == 'turret_head':
                if 'consumes_power' not in equip:
                    error |= 1; print '%s: equip is missing "consumes_power"' % (itemname,)

            if gamedata['game_id'] != 'fs': # FS uses leveled head items
                if crit.get('min_level',1) > 1:
                    if not any(('L%d or higher' % crit['min_level'] in ui_descr) or \
                               ('Level %d or higher' % crit['min_level'] in ui_descr) for ui_descr in ui_descr_list):
                        error |= 1; print '%s: requires min_level %d but the ui_description does not include the words "L%d or higher" or "Level %d or higher": "%s"' % (itemname, crit['min_level'], crit['min_level'], crit['min_level'], spec['ui_description'])

            for PRED in ('requires', 'unequip_requires'):
                if PRED in crit:
                    error |= check_predicate(crit[PRED], reason = 'item %s: equip %s' % (itemname,PRED))

        if ('name' in equip) and (gamedata['game_id'] in ('tr','dv')) and ('turret_heads' in gamedata['crafting']['categories']) and (equip['name'] in ('mg_tower', 'mortar_emplacement', 'tow_emplacement')):
            error |= 1; print '%s: needs migration to be "compatible" with turret heads' % itemname

        for CONS in ('on_equip', 'on_unequip'):
            if CONS in equip:
                error |= check_consequent(equip[CONS], reason = 'item %s: %s' % (itemname, CONS))

    if 'store_price' in spec or 'store_requires' in spec:
        error |= 1; print '%s: has obsolete store_price or store_requires fields - these need to be migrated to the store catalog in gamedata_main.json' % (itemname)

    if spec.get('remove_fragility',0) < 1 and (not spec.get('can_unequip', True)):
        error |= 1; print '%s: "can_unequip": 0 and "remove_fragility": 1 must be used together' % (itemname)

    for COND_CHAIN in ('force_expire_by', 'ui_description'):
        if COND_CHAIN in spec and type(spec[COND_CHAIN]) is list:
            expect_absolute_time_end = None
            if spec['name'] == 'token':
                # ensure that ABSOLUTE_TIME predicates, and actual expire times, end 2 days after a weekly multiple of the week origin
                expect_absolute_time_end = {'origin': gamedata['matchmaking']['week_origin'], 'offset': 2*86400, 'interval': 7*86400}
                if COND_CHAIN == 'force_expire_by':
                    for pred, val in spec[COND_CHAIN]:
                        if isinstance(val, int):
                            if val > 1 and ((val - expect_absolute_time_end['origin']) % expect_absolute_time_end['interval']) != expect_absolute_time_end['offset']:
                                error |= 1; print '%s: incorrect force_expire_by time %d, must agree with %r' % (itemname, val, expect_absolute_time_end)
                        else:
                            assert isinstance(val, dict)
                            if not (('event_name' in val) or ('event_kind' in val)):
                                error |= 1; print '%s: incorrect force_expire_by entry %r, missing event_name or event_kind' % (itemname, val)

            error |= check_cond_chain(spec[COND_CHAIN], reason = 'item %s: %s' % (itemname, COND_CHAIN), expect_absolute_time_end = expect_absolute_time_end)

    if 'associated_tech' in spec and spec['associated_tech'] not in gamedata['tech']:
        error |= 1; print '%s: associated_tech "%s" not found in tech.json' % (itemname, spec['associated_tech'])

    if 'use_effect' in spec:
        error |= check_visual_effect('%s:use_effect' % itemname, spec['use_effect'])

    return error

MODIFIABLE_STATS = {'unit/building': set(['max_hp', 'maxvel', 'weapon_damage', 'weapon_range', 'weapon_range_pvp', 'effective_weapon_range', 'ice_effects', 'rate_of_fire',
                                          'damage_taken', 'armor', 'unit_repair_speed', 'unit_repair_cost',
                                          'manufacture_speed', 'manufacture_cost', 'repair_speed', 'swamp_effects',
                                          'research_speed', 'crafting_speed', 'manufacture_speed', 'weapon', 'weapon_level', 'weapon_asset', 'permanent_auras', 'continuous_cast',
                                          'anti_air', 'anti_missile', 'resurrection', 'on_destroy', 'splash_range','effective_range','accuracy']),
                    'player': set(['foreman_speed', 'loot_factor_pvp', 'loot_factor_pve', 'loot_factor_tokens', 'travel_speed', 'deployable_unit_space',
                                   'chat_template', 'chat_gagged', 'quarry_yield_bonus', 'turf_quarry_yield_bonus',
                                   'combat_time_scale'])}

def check_item_name(specname, context):
    error = 0
    if specname not in gamedata['items']:
        error |= 1; print '%s refers to missing item "%s"' % (context, specname)
    return error

def check_modstat(effect, reason, affects = None, expect_level = None, expect_item_sets = None):
    error = 0
    if 'apply_if' in effect:
        error |= check_predicate(effect['apply_if'], reason = '%s:apply_if' % reason, expect_item_sets = expect_item_sets)
    if effect['method'] not in ('*=(1+strength)', '*=(1-strength)', '+=strength', '*=strength', 'max', 'min', 'replace', 'concat'):
        error |= 1; print '%s: bad method %s' % (reason, effect['method'])

    if not affects: affects = 'unit/building'

    if effect['stat'].startswith('produces_'):
        if effect['stat'][9:] not in gamedata['resources']:
            error |= 1; print '%s: bad %s produces_res stat %s' % (reason, affects, effect['stat'])
    elif effect['stat'] not in MODIFIABLE_STATS[affects] and (not (effect['stat'].startswith('damage_taken_from:') or effect['stat'].startswith('weapon_damage_vs:') or effect['stat'].startswith('research_speed'))):
        error |= 1; print '%s: bad %s stat %s' % (reason, affects, effect['stat'])

    # make sure that stats have strings entries to drive the GUI (not needed for player stats)
    if (effect['stat'] not in gamedata['strings']['modstats']['stats']) and (affects != 'player'):
        error |= 1; print '%s: stat %s is missing from gamedata.strings.modstats.stats' % (reason, effect['stat'])

    if effect['stat'] == 'on_destroy' and ('strength' in effect):
        for entry in effect['strength']:
            error |= check_consequent(entry, reason = '%s:strength' % reason)

    if effect['stat'] == 'weapon':
        if effect['strength'] not in gamedata['spells']:
            error |= 1; print '%s: weapon spell "%s" not found' % (reason, effect['strength'])
        # if this is a per-level item, and references a per-level weapon spell, make sure the level numbers match
        if expect_level is not None:
            matches = level_re.match(effect['strength'])
            if matches:
                level = int(matches.group('level'))
                if level != expect_level:
                    error |= 1; print '%s: leveled spell %s level number does not match item name' % (reason, effect['strength'])
    elif effect['stat'] == 'weapon_level':
        if expect_level is not None and expect_level != effect['strength']:
            error |= 1; print '%s: probably a typo, weapon_level "strength" should be %d' % (reason, expect_level)
    elif effect['stat'] == 'weapon_asset':
        asset_list = effect['strength'] if isinstance(effect['strength'], list) else [effect['strength'],]
        for asset in asset_list:
            error |= require_art_asset(asset, reason+':weapon_asset')
            if expect_level is not None:
                matches = level_re.match(asset)
                if matches:
                    level = int(matches.group('level'))
                    if level != expect_level:
                        # special case for high-level TR/DV turret heads that don't have custom assets yet
                        if gamedata['game_id'] in ('tr','dv') and level < expect_level and expect_level >= 17 and \
                           'turret_head_' in matches.group('root'):
                            pass
                        else:
                            error |= 1; print '%s: leveled weapon_asset %s level number does not match item name' % (reason, asset)
    return error

def check_loot_table(table, reason = '', expire_time = -1, duration = -1, max_slots = -1, is_toplevel = True):
    error = 0

    if type(table) is not list:
        if is_toplevel:
            error |= 1
            print '%s: loot table (%s) needs to be a list' % (reason, repr(table))

        table = [table]

    for entry in table:
        for key, val in entry.iteritems():
            if 'expire' in key:
                if key not in ('item_expire_at',):
                    error |= 1
                    print '%s: loot table entry (%s) looks like you are trying to make it expire, but you need to use "item_expire_at": or "item_duration": instead.' % (reason, repr(entry))

        if 'spec' in entry:
            if entry['spec'] not in gamedata['items']:
                error |= 1
                print '%s: loot table entry (%s) refers to invalid item "%s"' % (reason, repr(entry), entry['spec'])
            else:
                spec = gamedata['items'][entry['spec']]

                if 'token' in entry['spec']:
                    if ('item_expire_at' not in entry) and (expire_time < 0) and ('item_duration' not in entry) and (duration < 0) and ('force_expire_by' not in spec) and ('force_duration' not in spec):
                        error |= 1
                        print '%s: loot table entry (%s) drops tokens, but without an "item_expire_at" or "item_duration" expiration time' % (reason, repr(entry))

                if (not spec.get('fungible',False)):
                    # check stack size
                    if 'stack' in entry:
                        stack = entry['stack']
                    elif 'random_stack' in entry:
                        if entry['random_stack'][1] < entry['random_stack'][0]:
                            error |= 1
                            print '%s: loot table entry (%s) has bad random_stack values' % (reason, repr(entry))
                        stack = entry['random_stack'][1]
                    else:
                        stack = 1

                    if stack > spec.get('max_stack',1):
                        error |= 1
                        print '%s: loot table entry (%s) gives more than the max stack size (%d) of item "%s"\n -> reduce loot amount or break this into multiple stacks of <= %d each' % (reason, repr(entry), spec.get('max_stack',1), entry['spec'], spec.get('max_stack',1))

                if ('use' in spec) and ('spellname' in spec['use']) and spec['use']['spellname'] == 'GIVE_UNITS' and ('sexy_unlocked' not in reason) and \
                   (not entry.get('resurrection_ok',False)) and any(gamedata['units'][u].get('resurrectable',False) for u in spec['use']['spellarg'].iterkeys()):
                    error |= 1
                    print '%s: loot table gives resurrectable packaged units (%s), this is not compatible with permanent resurrection. Please replace this loot entry with something other than a packaged unit.' % (reason, entry['spec'])
        elif 'multi' in entry:
            if max_slots >= 0 and len(entry['multi']) > max_slots:
                error |= 1; print '%s: loot table entry (%s) can yield %d slots worth of items but limit here is %d' % (reason, repr(entry), len(entry['multi']), max_slots)
            for item in entry['multi']:
                error |= check_loot_table(item, reason = reason, expire_time = expire_time, duration = duration, is_toplevel = False)
        elif 'cond' in entry:
            for pred, loot in entry['cond']:
                error |= check_predicate(pred, reason = reason + ':cond')
                error |= check_loot_table(loot, reason = reason + ':' + repr(pred), expire_time = expire_time, duration = duration, is_toplevel = False)
        elif 'table' in entry:
            if entry['table'] not in gamedata['loot_tables']:
                error |= 1
                print '%s: loot table entry (%s) refers to missing global loot table "%s" - check make_loot_tables.py' % (reason, repr(entry), entry['table'])
        elif 'nothing' in entry:
            pass
        else:
            error |= 1
            print '%s: bad loot table entry - missing "spec", "multi", "cond", "table", or "nothing": %s' % (reason, repr(entry))
    return error

def check_cond_or_literal(chain, **kwargs):
    if type(chain) is list:
        return check_cond_chain(chain, **kwargs)
    return 0
def check_cond_chain(chain, **kwargs):
    error = 0
    for pred, val in chain:
        error |= check_predicate(pred, **kwargs)
    return error

PREDICATE_TYPES = set(['AND', 'OR', 'NOT', 'ALWAYS_TRUE', 'ALWAYS_FALSE', 'TUTORIAL_COMPLETE', 'ACCOUNT_CREATION_TIME',
                   'ALL_BUILDINGS_UNDAMAGED', 'OBJECT_UNDAMAGED', 'OBJECT_UNBUSY', 'BUILDING_DESTROYED', 'BUILDING_QUANTITY',
                   'BUILDING_LEVEL', 'UNIT_QUANTITY', 'TECH_LEVEL', 'QUEST_COMPLETED', 'COOLDOWN_ACTIVE', 'COOLDOWN_INACTIVE',
                   'ABTEST', 'ANY_ABTEST', 'RANDOM', 'LIBRARY', 'AI_BASE_ACTIVE', 'AI_BASE_SHOWN', 'PLAYER_HISTORY', 'GAMEDATA_VAR',
                   'RETAINED', 'TIME_IN_GAME',
                   'ATTACKS_LAUNCHED', 'ATTACKS_VICTORY', 'CONQUESTS', 'UNITS_MANUFACTURED', 'LOGGED_IN_TIMES',
                   'RESOURCE_STORAGE_CAPACITY',
                   'RESOURCES_HARVESTED_TOTAL', 'RESOURCES_HARVESTED_AT_ONCE', 'FRIENDS_JOINED', 'FACEBOOK_APP_NAMESPACE', 'FACEBOOK_LIKES_SERVER',
                   'FACEBOOK_LIKES_CLIENT', 'PRICE_REGION', 'COUNTRY', 'COUNTRY_TIER', 'EVENT_TIME', 'ABSOLUTE_TIME', 'TIME_OF_DAY', 'BROWSER_HARDWARE',
                   'BROWSER_OS', 'BROWSER_NAME', 'BROWSER_VERSION', 'SELECTED', 'UI_CLEAR', 'QUEST_CLAIMABLE', 'HOME_BASE', 'HAS_ATTACKED', 'HAS_DEPLOYED',
                   'PRE_DEPLOY_UNITS', 'DIALOG_OPEN', 'FOREMAN_IS_BUSY', 'GAMEBUCKS_BALANCE', 'INVENTORY', 'HAS_ITEM', 'HAS_ITEM_SET', 'HOME_REGION', 'REGION_PROPERTY', 'LADDER_PLAYER',
                   'HOSTILE_UNIT_NEAR', 'HOSTILE_UNIT_EXISTS',
                   'MAIL_ATTACHMENTS_WAITING', 'AURA_ACTIVE', 'AURA_INACTIVE', 'AI_INSTANCE_GENERATION', 'USER_ID', 'LOGGED_IN_RECENTLY', 'PVP_AGGRESSED_RECENTLY', 'IS_IN_ALLIANCE', 'FRAME_PLATFORM', 'NEW_BIRTHDAY', 'HAS_ALIAS', 'HAS_TITLE', 'USING_TITLE', 'PLAYER_LEVEL',
                   'PURCHASED_RECENTLY', 'SESSION_LENGTH_TREND', 'ARMY_SIZE',
                   'VIEWING_BASE_DAMAGE', 'VIEWING_BASE_OBJECT_DESTROYED', 'BASE_SIZE', 'QUERY_STRING',
                   'HAS_MENTOR'
                   ])

# context: 'ai_base', 'ai_attack', etc - describes the general environment of the predicate
# context_data: for AI bases, it's the base JSON itself (used to check for typos)
# expect_library_preds: for LIBRARY predicates, expect that it will be a member of this list/set
# expect_player_history_keys: for PLAYER_HISTORY predicates, expect that it will refer to a key in this list/set
# expect_items: for HAS_ITEM predicates, expect that items named will be a member of this list/set
# expect_items_unique_equipped: for HAS_ITEM predicates, expect that items named will be members of a unique_equipped set in this list/set
# expect_item_sets: for HAS_ITEM_SET predicates, expect that item_sets named will be a member of this list/set
# expect_absolute_time_end: for ABSOLUTE_TIME predicates, expect specific end time ({'origin': xxx, 'offset': yyy})
def check_predicate(pred, reason = '', context = None, context_data = None,
                    expect_items = None, expect_items_unique_equipped = None, expect_library_preds = None, expect_player_history_keys = None, expect_item_sets = None, expect_absolute_time_end = None):
    error = 0

    if ('predicate' not in pred) or (pred['predicate'] not in PREDICATE_TYPES):
        print '%s: bad predicate type "%s": %s' % (reason, pred.get('predicate','MISSING'), repr(pred))
        error |= 1

    if 'help_predicate' in pred:
        error |= check_predicate(pred['help_predicate'], reason=reason, context=context, context_data=context_data, expect_items=expect_items, expect_items_unique_equipped=expect_items_unique_equipped, expect_library_preds=expect_library_preds, expect_player_history_keys=expect_player_history_keys)

    if pred['predicate'] in ('AND','OR','NOT'):
        if 'subconsequents' in pred:
            error |= 1; print '%s: %s predicate includes subconsequents: %s' % (reason, pred['predicate'], repr(pred))

        if 'subpredicates' in pred:
            for subpred in pred['subpredicates']:
                error |= check_predicate(subpred, reason = reason, context=context, context_data=context_data, expect_items=expect_items, expect_items_unique_equipped=expect_items_unique_equipped, expect_library_preds=expect_library_preds, expect_player_history_keys=expect_player_history_keys, expect_item_sets=expect_item_sets)
        else:
            error |= 1; print '%s: %s predicate is missing subpredicates: %s' % (reason, pred['predicate'], repr(pred))

    if pred['predicate'] == 'EVENT_TIME':
        if ('event_name' in pred) and (pred['event_name'] not in gamedata['events']):
            error |= 1
            print '%s: EVENT_TIME predicate refers to missing event "%s" - check gamedata_main.json/events' % (reason, pred['event_name'])
        if ('event_kind' in pred):
            pass
        # not sure why we added this - does it break something?
#            if 'trophy_pvp' in pred['event_kind']:
#                error |= 1
#                print '%s: EVENT_TIME predicate uses incorrect kind "%s" - it should be pvp not pve' % (reason, pred['event_kind'])
    elif pred['predicate'] == 'TECH_LEVEL':
        if pred.get('tech',None) not in gamedata['tech']:
            error |= 1
            print '%s: %s predicate refers to nonexistent tech "%s"' % (reason, pred['predicate'], pred.get('tech','MISSING'))
        elif gamedata['tech'][pred['tech']].get('activation',{}).get('predicate',None) == "ALWAYS_FALSE":
            if not reason.startswith('units:'):
                error |= 1
                print '%s: %s predicate refers to disabled tech "%s"' % (reason, pred['predicate'], pred['tech'])
    elif pred['predicate'] in ('BUILDING_LEVEL','BUILDING_QUANTITY'):
        if pred['building_type'] not in gamedata['buildings']:
            error |= 1
            print '%s: %s predicate refers to nonexistent building "%s"' % (reason, pred['predicate'], pred['building_type'])
        elif 'trigger_level' in pred:
            if pred['trigger_level'] > len(gamedata['buildings'][pred['building_type']]['build_time']):
                error |= 1
                print '%s: %s predicate requires building "%s" level %d (beyond its max)' % (reason, pred['predicate'], pred['building_type'], pred['trigger_level'])
    elif pred['predicate'] == 'OBJECT_UNDAMAGED':
        if pred['spec'] not in gamedata['buildings']:
            error |= 1
            print '%s: %s predicate refers to nonexistent building "%s"' % (reason, pred['predicate'], pred['spec'])
    elif pred['predicate'] == 'BUILDING_DESTROYED':
        if pred['spec'] not in gamedata['buildings']:
            error |= 1
            print '%s: %s predicate refers to nonexistent building "%s"' % (reason, pred['predicate'], pred['spec'])
    elif pred['predicate'] == 'QUEST_COMPLETED':
        if pred['quest_name'] not in gamedata['quests']:
            error |= 1
            print '%s: %s predicate refers to nonexistent quest "%s"' % (reason, pred['predicate'], pred['quest_name'])
    elif pred['predicate'] == 'PRE_DEPLOY_UNITS':
        if pred['spec'] not in gamedata['units']:
            error |= 1
            print '%s: %s predicate refers to nonexistent unit "%s"' % (reason, pred['predicate'], pred['spec'])
        error |= check_unit_name(pred['spec'], reason)

    elif pred['predicate'] in ('AURA_ACTIVE', 'AURA_INACTIVE'):
        if pred['aura_name'] not in gamedata['auras']:
            error |= 1; print '%s: %s predicate refers to unknown aura "%s"' % (reason, pred['predicate'], pred['aura_name'])

    elif pred['predicate'] == 'GAMEBUCKS_BALANCE':
        if 'value' not in pred:
            error |= 1; print '%s: %s predicate missing "value"' % (reason, pred['predicate'])
    elif pred['predicate'] == 'HAS_ITEM':
        if pred['item_name'] not in gamedata['items']:
            error |= 1; print '%s: %s predicate refers to nonexistent item "%s"' % (reason, pred['predicate'], pred['item_name'])
        else:
            spec = gamedata['items'][pred['item_name']]
            if expect_items is not None and pred['item_name'] not in expect_items:
                error |= 1; print '%s: %s predicate refers to item "%s" but is only allowed to refer to one of %s' % (reason, pred['predicate'], pred['item_name'], repr(expect_items))
            if expect_items_unique_equipped is not None and spec.get('unique_equipped','NONE') not in expect_items_unique_equipped:
                error |= 1; print '%s: %s predicate refers to item "%s" but is only allowed to refer to items with a unique_equipped value in %s' % (reason, pred['predicate'], pred['item_name'], repr(expect_items_unique_equipped))

    elif pred['predicate'] == 'HAS_ITEM_SET':
        if pred['item_set'] not in gamedata['item_sets']:
            error |= 1
            print '%s: %s predicate refers to nonexistent item set "%s"' % (reason, pred['predicate'], pred['item_set'])
        if pred.get('min',-1) > len(gamedata['item_sets'][pred['item_set']]['members']):
            error |= 1
            print '%s: %s predicate has "min" more than number of members in set "%s"' % (reason, pred['predicate'], pred['item_set'])
        if expect_item_sets and pred['item_set'] not in expect_item_sets:
            error |= 1
            print '%s: %s predicate refers to item set "%s" when one of %s is expected instead' % (reason, pred['predicate'], pred['item_set'], repr(expect_item_sets))
    elif pred['predicate'] == 'LIBRARY':
        if pred['name'] not in gamedata['predicate_library']:
            error |= 1
            print '%s: %s predicate refers to nonexistent library predicate "%s"' % (reason, pred['predicate'], pred['name'])
        if (expect_library_preds) is not None and (pred['name'] not in expect_library_preds) and (not pred['name'].endswith('_event_store_open')):
            error |= 1; print '%s: %s predicate refers to LIBRARY "%s" but is only allowed to refer to one of %s' % (reason, pred['predicate'], pred['name'], repr(expect_library_preds))

    elif pred['predicate'] == 'SELECTED':
        if (pred['type'] not in ('ANY','CURSOR')) and (pred['type'] not in gamedata['units']) and (pred['type'] not in gamedata['buildings']):
            error |= 1
            print '%s: %s predicate refers to nonexistent unit or building "%s"' % (reason, pred['predicate'], pred['type'])
    elif pred['predicate'] == 'TUTORIAL_ARROW':
        if (pred['arrow_type'] == 'landscape') and ('target_name' in pred):
            if (pred['target_name'] not in gamedata['units']) and (pred['target_name'] not in gamedata['buildings']):
                error |= 1
                print '%s: %s predicate refers to nonexistent unit or building "%s"' % (reason, pred['predicate'], pred['target_name'])
    elif pred['predicate'] == 'RANDOM':
        if 'chance' not in pred:
            error |= 1; print '%s: RANDOM predicate needs a "chance" 0-1' % (reason)
    elif pred['predicate'] == 'FRAME_PLATFORM':
        VALID_PLATFORMS = ('fb','kg','ag','bh')
        if pred.get('platform',None) not in VALID_PLATFORMS:
            error |= 1; print '%s: FRAME_PLATFORM predicate needs a "platform" in %r' % (reason, VALID_PLATFORMS)
    elif pred['predicate'] == 'GAMEDATA_VAR':
        for mandatory in ('name', 'value'):
            if mandatory not in pred: error |= 1; print '%s: %s predicate missing "%s"' % (reason, pred['predicate'], mandatory)
        if 'method' in pred and pred['method'] not in ('==', 'in'):
            error |= 1; print '%s: %s predicate has bad "method" %s' % (reason, pred['predicate'], pred['method'])
        path = pred['name'].split('.')
        v = gamedata
        for elem in path:
            if elem not in v:
                error |= 1; print '%s: %s predicate has looks up undefined value "%s"' % (reason, pred['predicate'], pred['name'])
                break
            v = v[elem]
    elif pred['predicate'] == 'PLAYER_HISTORY':
        if 'key' not in pred: error |= 1; print '%s: %s predicate missing "key"' % (reason, pred['predicate'])
        else:
            # check for typos in townhall level checks
            for TH in ('central_computer', 'toc', 'castle'):
                if pred['key'] == TH+'_level' and gamedata['townhall'] != TH:
                    error |= 1; print '%s: %s predicate refers to wrong town hall building (%s should be %s)' % (reason, pred['predicate'], pred['key'], gamedata['townhall']+'_level')
        if 'value' not in pred: error |= 1; print '%s: %s predicate missing "value"' % (reason, pred['predicate'])
        if expect_player_history_keys is not None and pred['key'] not in expect_player_history_keys:
            error |= 1; print '%s: %s predicate refers to key %s but is only allowed to use keys in %s' % (reason, pred['predicate'], pred['key'], repr(expect_player_history_keys))
        method = pred.get('method','MISSING')
        if method not in ('==', '>=', '<', 'count_samples'):
                error |= 1; print '%s: PLAYER_HISTORY predicate has bad "method" %s' % (reason, method)
    elif pred['predicate'] == 'RETAINED':
        if ('age_range' not in pred) and ('duration' not in pred): # note: duration is obsolete since it is not time-windowed
            error |= 1; print '%s: %s predicate missing "age_range"' % (reason, pred['predicate'])
    elif pred['predicate'] == 'VIEWING_BASE_OBJECT_DESTROYED':
        if pred['spec'] not in gamedata['buildings']:
            error |= 1; print '%s: %s predicate with invalid spec %s' % (reason, pred['predicate'], pred['spec'])
    elif pred['predicate'] == 'FACEBOOK_APP_NAMESPACE':
        if 'namespace' not in pred:
            error |= 1; print '%s: %s predicate missing a "namespace"' % (reason, pred['predicate'])
    elif pred['predicate'] in ('HAS_TITLE','USING_TITLE'):
        if ((pred['predicate'] == 'HAS_TITLE') or ('name' in pred)) and (pred['name'] not in gamedata['titles']):
            error |= 1; print '%s: %s predicate name %r not found in gamedata.titles' % (reason, pred['predicate'], pred.get('name'))
    elif pred['predicate'] == 'PLAYER_LEVEL':
        if pred['level'] > len(gamedata['player_xp']['level_xp'])-1:
            error |= 1; print '%s: %s predicate "level" %d is greater than the max level (%d)' % (reason, pred['predicate'], pred['level'],
                                                                                                  len(gamedata['player_xp']['level_xp'])-1)
    elif pred['predicate'] == 'ABSOLUTE_TIME':
        if expect_absolute_time_end is not None:
            if ((pred['range'][1] - expect_absolute_time_end['origin']) % expect_absolute_time_end['interval']) != expect_absolute_time_end['offset']:
                error |= 1; print '%s: %s predicate has incorrect end time (%d). Must agree with %r' % (reason, pred['predicate'], pred['range'][1], expect_absolute_time_end)
    elif pred['predicate'] == 'QUERY_STRING':
        if ('key' not in pred) or ('value' not in pred) or not isinstance(pred['value'], basestring):
            error |= 1; print '%s: %s predicate needs a key and string value' % (reason, pred['predicate'])
    return error

# check old-style "logic" blocks which are if/then/else compositions of predicates and consequents (used for quest tips)
def check_logic(log, reason = '', context = None):
    if 'consequent' in log:
        return check_consequent(log, reason=reason, context=context)
    if 'null' in log:
        return 0
    error = 0
    if 'if' in log:
        error |= check_predicate(log['if'], reason=reason, context=context)
    for CONS in ('then','else'):
        if CONS in log:
            error |= check_logic(log[CONS], reason=reason, context=context)
    return error

CONSEQUENT_TYPES = set(['NULL', 'AND', 'RANDOM', 'IF', 'COND', 'LIBRARY',
                        'PLAYER_HISTORY', 'GIVE_LOOT', 'SESSION_LOOT', 'GIVE_TROPHIES', 'GIVE_TECH', 'APPLY_AURA', 'REMOVE_AURA', 'COOLDOWN_TRIGGER', 'COOLDOWN_TRIGGER', 'COOLDOWN_RESET',
                        'METRIC_EVENT', 'SPAWN_SECURITY_TEAM', 'CHAT_SEND', 'FIND_AND_REPLACE_ITEMS', 'FIND_AND_REPLACE_OBJECTS',
                        'VISIT_BASE', 'DISPLAY_MESSAGE', 'MESSAGE_BOX', 'TUTORIAL_ARROW', 'INVOKE_MAP_DIALOG', 'START_AI_ATTACK',
                        'INVOKE_CRAFTING_DIALOG', 'INVOKE_BUILD_DIALOG', 'INVOKE_MISSIONS_DIALOG', 'INVOKE_MAIL_DIALOG', 'INVOKE_STORE_DIALOG', 'INVOKE_UPGRADE_DIALOG', 'INVOKE_BUY_GAMEBUCKS_DIALOG', 'INVOKE_LOTTERY_DIALOG', 'INVOKE_MANUFACTURE_DIALOG',
                        'INVOKE_CHANGE_REGION_DIALOG', 'INVOKE_BLUEPRINT_CONGRATS', 'INVOKE_TOP_ALLIANCES_DIALOG', 'INVOKE_INVENTORY_DIALOG', 'MARK_BIRTHDAY',
                        'OPEN_URL', 'FOCUS_CHAT_GUI', 'FACEBOOK_PERMISSIONS_PROMPT', 'DAILY_TIP_UNDERSTOOD', 'RANDOM', 'FORCE_SCROLL',
                        'GIVE_UNITS', 'TAKE_UNITS', 'PRELOAD_ART_ASSET', 'HEAL_ALL_UNITS', 'HEAL_ALL_BUILDINGS',
                        'ENABLE_COMBAT_RESOURCE_BARS', 'ENABLE_DIALOG_COMPLETION', 'INVITE_FRIENDS_PROMPT', 'DISPLAY_DAILY_TIP', 'INVOKE_OFFER_CHOICE', 'TAKE_ITEMS',
                        'CLEAR_UI', 'CLEAR_NOTIFICATIONS', 'DEV_EDIT_MODE', 'GIVE_GAMEBUCKS', 'LOAD_AI_BASE', 'REPAIR_ALL', 'FPS_COUNTER',
                        'CHANGE_TITLE', 'INVITE_COMPLETE', 'SEND_MESSAGE',
                        'ALL_AGGRESSIVE',
                   ])

def check_consequent(cons, reason = '', context = None, context_data = None):
    error = 0

    kind = cons.get('consequent', 'MISSING')
    if kind not in CONSEQUENT_TYPES:
        error |= 1; print '%s: bad consequent type %s in %s' % (reason, kind, repr(cons))

    if cons['consequent'] == 'IF':
        error |= check_predicate(cons['if'], reason = reason, context = context, context_data = context_data)
        error |= check_consequent(cons['then'], reason = reason, context = context, context_data = context_data)
        if 'else' in cons:
            error |= check_consequent(cons['else'], reason = reason, context = context, context_data = context_data)
    elif cons['consequent'] == 'COND':
        for p, c in cons['cond']:
            error |= check_predicate(p, reason = reason, context = context, context_data = context_data)
            error |= check_consequent(c, reason = reason, context = context, context_data = context_data)
    elif cons['consequent'] == "GIVE_LOOT":
        error |= check_loot_table(cons['loot'], reason = reason, expire_time = cons.get('item_expire_at',-1), duration = cons.get('item_duration',-1))
        if cons.get('reason',None) != context and cons.get('reason',None) not in ('special', 'promo_code'):
            error |= 1
            print '%s: GIVE_LOOT consequent has bad "reason", it should be "%s"' % (reason, context)
        if 'mail_template' in cons:
            error |= check_mail_template(cons['mail_template'], reason = reason + ':mail_template')
    elif cons['consequent'] == "IF":
        error |= check_predicate(cons['if'], reason = reason, context = context, context_data = context_data)
        error |= check_consequent(cons['then'], reason = reason, context = context, context_data = context_data)
        if 'else' in cons:
            error |= check_consequent(cons['else'], reason = reason, context = context, context_data = context_data)
    elif cons['consequent'] == "DISPLAY_MESSAGE":
        for ASSET in ('picture', 'picture_asset', 'inset_picture', 'sound'):
            if ASSET in cons:
                error |= require_art_asset(cons[ASSET], reason+':'+ASSET)

        if 'frequency' in cons:
            if cons['frequency'] not in ('session', 'base_id'):
                error |= 1
                print '%s: DISPLAY_MESSAGE consequent with bad "frequency" value %s, should be "session" or "base_id"' % (reason, cons['frequency'])
            if cons['frequency'] == 'session' and ('tag' not in cons):
                error |= 1
                print '%s: DISPLAY_MESSAGE consequent with "session" frequency is missing a "tag"' % (reason,)
        if 'dialog' in cons:
            if cons['dialog'] == 'showcase':
                error |= check_showcase_hack(cons, reason)

    elif cons['consequent'] == 'DAILY_TIP_UNDERSTOOD':
        if (not (('name' in cons) or ('name_from_context' in cons))):
            error |= 1
            print '%s: %s consequent needs either "name" or "name_from_context"' % (reason, cons['consequent'])

    elif cons['consequent'] == "PLAYER_HISTORY":
        METHODS = ('max', 'set', 'increment')
        if cons['method'] not in METHODS:
            error |= 1; print '%s: %s consequent has bad "method", must be one of: %s' % (reason, cons['consequent'], METHODS)
        for FIELD in ('key','value'):
            if FIELD not in cons:
                error |= 1; print '%s: %s consequent missing "%s"' % (reason, cons['consequent'], FIELD)
        else:
            if type(cons['value']) in (str,unicode) and len(cons['value'])>=1 and cons['value'][0] == '$':
                # check for valid context variables
                if cons['value'] not in ('$n_battle_stars','$largest_purchase','$largest_purchase_gamebucks','$cur_gamebucks'):
                    error |= 1; print '%s: %s consequent has bad "value" context variable reference "%s"' % (reason, cons['consequent'], cons['value'])

        # try to catch common typos
        if cons['key'].endswith('_stars'):
            # check expected name of battle stars key, e.g. "ai_tutorial25_L12_stars"
            expect = '_L%d_stars' % context_data['resources']['player_level']
            if (not context_data) or (not cons['key'].endswith(expect)) or \
               (not (cons['key'] in context_data.get('ui_battle_stars_key','missing'))):
                error |= 1; print '%s: %s consequent suspect typo, check that "key": "%s" matches the player_level, and that "ui_battle_stars_key" is set to this value' % (reason, cons['consequent'], cons['key'])

    elif cons['consequent'] == "METRIC_EVENT":
        assert int(cons['event_name'][0:4])

    elif cons['consequent'] == "APPLY_AURA" or cons['consequent'] == "REMOVE_AURA":
        if cons['aura_name'] not in gamedata['auras']:
            error |= 1
            print '%s: APPLY/REMOVE_AURA consequent refers to missing aura "%s", check auras.json\n' % (reason, cons['aura_name'])
        if cons['aura_name'].startswith('trophy_reward_'):
            if (context == 'ai_base' and (not cons['aura_name'].startswith('trophy_reward_pve_away')) and (not cons['aura_name'].endswith('pvv_away'))) or \
               (context == 'ai_attack' and (not cons['aura_name'].startswith('trophy_reward_pve_home'))):
                error |= 1
                print '%s: APPLY/REMOVE_AURA consequent has inappropriate aura "%s" - it should be trophy_reward_pve_away for AI bases and trophy_reward_pve_home for AI attacks\n' % (reason, cons['aura_name'])
    elif cons['consequent'] == "FIND_AND_REPLACE_ITEMS":
        if 'item_map' in cons:
            for fr, to in cons['item_map'].iteritems():
                if ((not cons['item_map'].get('legacy',False)) and fr not in gamedata['items']):
                    error |= 1; print '%s: %s consequent refers to invalid item %s\n' % (reason, cons['consequent'], fr)
                if (to not in gamedata['items']):
                    error |= 1; print '%s: %s consequent refers to invalid item %s\n' % (reason, cons['consequent'], to)
        if 'recipe_map' in cons:
            for fr, to in cons['recipe_map'].iteritems():
                if ((not cons['recipe_map'].get('legacy',False)) and fr not in gamedata['crafting']['recipes']):
                    error |= 1; print '%s: %s consequent refers to invalid crafting recipe %s\n' % (reason, cons['consequent'], fr)
                if (to not in gamedata['crafting']['recipes']):
                    error |= 1; print '%s: %s consequent refers to invalid crafting recipe %s\n' % (reason, cons['consequent'], to)
    elif cons['consequent'] == "FIND_AND_REPLACE_OBJECTS":
        for find, replace in cons['replacements']:
            for sel in find, replace:
                spec = gamedata['buildings'].get(sel['spec'], None)
                if not spec:
                    error |= 1; print '%s: invalid spec "%s"' % (reason, sel['spec'])
                else:
                    if 'level' in sel and sel['level'] > len(spec[GameDataUtil.MAX_LEVEL_FIELD['buildings']]):
                        error |= 1; print '%s: spec "%s" level %d is beyond max' % (reason, sel['spec'], sel['level'])
                    if 'equipment' in sel:
                        for slot_type, name_list in sel['equipment'].iteritems():
                            if slot_type not in gamedata['strings']['equip_slots']:
                                error |= 1; print '%s: invalid slot_type %s' % (reason, slot_type)
                            for name in name_list:
                                if name not in gamedata['items']:
                                    error |= 1; print '%s: invalid item %s' % (reason, name)
    elif cons['consequent'] == "SPAWN_SECURITY_TEAM":
        for name, qty in cons['units'].iteritems():
            error |= check_unit_name(name, reason)
    elif cons['consequent'] == "START_AI_ATTACK":
        if str(cons['attack_id'])[0] == '$':
            pass # context variable
        elif (str(cons['attack_id']) not in gamedata['ai_bases']['bases']) and (str(cons['attack_id']) not in gamedata['ai_attacks']['attack_types']):
            error |= 1; print '%s: START_AI_ATTACK refers to invalid attack %s' % (reason, str(cons['attack_id']))
        elif (str(cons['attack_id']) not in gamedata['ai_attacks']['attack_types']) and (gamedata['ai_bases']['bases'][str(cons['attack_id'])].get('kind', 'ai_base') != 'ai_attack'):
            error |= 1; print '%s: START_AI_ATTACK refers to %s but %s is an AI base, not an attack - use VISIT_BASE with "user_id": %s instead' % (reason, cons['attack_id'], cons['attack_id'], cons['attack_id'])
    elif cons['consequent'] == "VISIT_BASE":
        if str(cons['user_id']) not in gamedata['ai_bases']['bases']:
            error |= 1; print '%s: VISIT_BASE refers to invalid user_id %s' % (reason, str(cons['user_id']))
        elif gamedata['ai_bases']['bases'][str(cons['user_id'])].get('kind', 'ai_base') != 'ai_base':
            error |= 1; print '%s: VISIT_BASE refers to base %s but base %s is an AI attack - use START_AI_ATTACK with "attack_id": %s instead' % (reason, cons['user_id'], cons['user_id'], cons['user_id'])
    elif cons['consequent'] == 'LIBRARY':
        if cons['name'] not in gamedata['consequent_library']:
            error |= 1
            print '%s: %s consequent refers to nonexistent library consequent "%s"' % (reason, cons['consequent'], cons['name'])
    elif cons['consequent'] == 'GIVE_TECH':
        if cons['tech_name'] not in gamedata['tech']:
            error |= 1; print '%s: %s consequent refers to nonexistent tech "%s"' % (reason, cons['consequent'], cons['tech_name'])
        else:
            level = cons.get('tech_level',1)
            if level < 1 or level > len(gamedata['tech'][cons['tech_name']][GameDataUtil.MAX_LEVEL_FIELD['tech']]):
                error |= 1; print '%s: %s consequent gives "%s" L%d which is greater than its max level' % (reason, cons['consequent'], cons['tech_name'], cons['tech_level'])
    elif cons['consequent'] == 'OPEN_URL':
        error |= check_url(cons['url'], reason = reason)
    elif cons['consequent'] == 'GIVE_TROPHIES':
        if cons.get('trophy_kind', None) not in ['pve','pvp','pvv']:
            error |= 1; print '%s: GIVE_TROPHIES refers to invalid trophy kind %s' % (reason, cons.get('trophy_kind', None))
        if cons.get('method', '+') not in ['+', '-']:
            error |= 1; print '%s: GIVE_TROPHIES refers to invalid method %s' % (reason, cons.get('method', '+'))
        if cons.get('scale_by', None) not in ['base_damage', 'deployed_unit_space', None]:
            error |= 1; print '%s: GIVE_TROPHIES refers to invalid scaling factor %s' % (reason, cons.get('scale_by', None))
    elif cons['consequent'] == 'CHAT_SEND':
        channels = cons.get('channels', ['GLOBAL'])
        for channel in channels:
            if channel not in ['GLOBAL', 'REGION', 'ALLIANCE', 'DEVELOPER']:
                error |= 1; print '%s: CHAT_SEND refers to invalid chat channel %s' % (reason, channel)
    elif cons['consequent'] == 'DISPLAY_DAILY_TIP':
        if not any(tip['name'] == cons.get('name', '') for tip in gamedata['daily_tips']):
            error |= 1; print '%s: DISPLAY_DAILY_TIP refers to invalid daily tip %s' % (reason, cons.get('name', ''))
    elif cons['consequent'] == 'INVOKE_OFFER_CHOICE':
        error |= check_consequent(cons['then'], reason = reason, context = context, context_data = context_data)
    elif cons['consequent'] in ('GIVE_UNITS','TAKE_UNITS'):
        units = cons['units']
        for name, data in units.iteritems():
            error |= check_unit_name(name, reason)
            if type(data) is dict:
                qty = data['qty']
                min_level = data.get('min_level', 1)
                if min_level > len(gamedata['units'][name][GameDataUtil.MAX_LEVEL_FIELD['units']]):
                    error |= 1; print '%s: GIVE_UNITS min_level is higher than max unit level' % reason
            else:
                qty = data
            if type(qty) is not int:
                error |= 1; print '%s: bad qty value %s' % (reason, repr(qty))

    elif cons['consequent'] == 'SEND_MESSAGE':
        if cons.get('to') != '%MENTOR':
            error |= 1; print '%s: SEND_MESSAGE invalid "to"' % reason
        error |= check_mail_template(cons['mail_template'], reason = reason + ':mail_template')

    elif cons['consequent'] == 'PRELOAD_ART_ASSET':
        if 'unit_name' in cons:
            error |= check_unit_name(cons['unit_name'], reason)
        else:
            if cons['asset'] not in gamedata['art']:
                error |= 1; print '%s: PRELOAD_ART_ASSET refers to missing asset %s' % (reason, cons['asset'])

    elif cons['consequent'] == 'INVOKE_MISSIONS_DIALOG':
        if ('select_mission' in cons) and (cons['select_mission'] not in gamedata['quests']):
            error |= 1; print '%s: select_mission "%s" not found' % (reason, cons['select_mission'])

    elif cons['consequent'] == 'INVOKE_UPGRADE_DIALOG':
        if ('building' in cons) and (cons['building'] not in gamedata['buildings']):
            error |= 1; print '%s: building "%s" not found' % (reason, cons['building'])
        if ('tech' in cons) and (cons['tech'] not in gamedata['tech']):
            error |= 1; print '%s: tech "%s" not found' % (reason, cons['tech'])

    elif cons['consequent'] == 'INVOKE_MANUFACTURE_DIALOG':
        if ('category' in cons) and (cons['category'] not in gamedata['strings']['manufacture_categories']):
            error |= 1; print '%s: category "%s" not found' % (reason, cons['category'])
        if ('specname' in cons) and (cons['specname'] not in gamedata['units']):
            error |= 1; print '%s: unit specname "%s" not found' % (reason, cons['specname'])

    elif cons['consequent'] in ('CHANGE_TITLE',):
        if cons['name'] not in gamedata['titles']:
            error |= 1; print '%s: invalid name "%s" not found in gamedata.titles' % (reason, cons['name'])

    elif cons['consequent'] in ['INVOKE_BLUEPRINT_CONGRATS', 'COOLDOWN_TRIGGER', 'COOLDOWN_RESET', 'SESSION_LOOT',
                                'INVOKE_TOP_ALLIANCES_DIALOG', 'INVOKE_INVENTORY_DIALOG', 'INVOKE_STORE_DIALOG', 'INVOKE_MAP_DIALOG', 'MESSAGE_BOX',
                                'INVOKE_CRAFTING_DIALOG', 'INVOKE_BUILD_DIALOG',
                                'TUTORIAL_ARROW', 'INVOKE_BUY_GAMEBUCKS_DIALOG', 'INVOKE_LOTTERY_DIALOG', 'INVOKE_CHANGE_REGION_DIALOG',
                                'FACEBOOK_PERMISSIONS_PROMPT', 'FORCE_SCROLL', 'HEAL_ALL_UNITS', 'HEAL_ALL_BUILDINGS',
                                'ENABLE_COMBAT_RESOURCE_BARS', 'ENABLE_DIALOG_COMPLETION', 'INVITE_FRIENDS_PROMPT', 'TAKE_ITEMS',
                                'CLEAR_UI', 'CLEAR_NOTIFICATIONS', 'DEV_EDIT_MODE', 'GIVE_GAMEBUCKS', 'LOAD_AI_BASE', 'REPAIR_ALL', 'FPS_COUNTER',
                                'FOCUS_CHAT_GUI', 'ALL_AGGRESSIVE', 'INVITE_COMPLETE',
                                'NULL']:
        # we recognize these ones, but they don't have detailed sanity checks written for them yet
        pass
    elif cons['consequent'] in ('AND', 'OR', 'NOT', 'RANDOM'):
        if 'subpredicates' in cons:
            error |= 1; print '%s: %s consequent includes subpredicates: %s' % (reason, cons['consequent'], repr(cons))

        if 'subconsequents' in cons:
            for subcons in cons['subconsequents']:
                error |= check_consequent(subcons, reason = reason, context = context, context_data = context_data)
        else:
            error |= 1; print '%s: %s consequent is missing subconsequents: %s' % (reason, cons['consequent'], repr(cons))
    else:
        error |= 1; print '%s: invalid consequent %s' % (reason, cons['consequent'])

    return error

def check_mail_template(data, reason = ''):
    error = 0
    for FIELD in ('ui_subject', 'ui_body'):
        if FIELD not in data:
            error |= 1; print '%s: missing "%s"' % (reason, FIELD)
    if 'attachments' in data:
        for entry in data['attachments']:
            error |= check_item_name(entry['spec'], reason + ':attachments')
    if 'on_receipt' in data:
        if data['on_receipt'] not in gamedata['consequent_library']:
            error |= 1; print '%s: invalid on_receipt LIBRARY consequent "%s"' % (reason, data['on_receipt'])
    return error

def check_showcase_hack(cons, reason = ''):
    error = 0
    if 'showcase_hack' in cons:
        sc = cons['showcase_hack']
        for UNIT_FIELD in ('final_reward_unit', 'token_reward_unit'):
            if UNIT_FIELD in sc:
                if isinstance(sc[UNIT_FIELD], dict):
                    # unit field is keyed on difficulty so loop through each difficulty's unit
                    for diff, unit in sc[UNIT_FIELD]:
                        error |= check_unit_name(unit, reason + ':' + cons['consequent'] + ':' + UNIT_FIELD)
                else:
                    error |= check_unit_name(sc[UNIT_FIELD], reason + ':' + cons['consequent'] + ':' + UNIT_FIELD)
        for ITEM_FIELD in ('feature_random_items', 'final_reward_items', 'token_reward_items'):
            if ITEM_FIELD in sc:
                def check_showcase_item_field(cons, value, reason = ''):
                    error = 0
                    # item field is keyed on difficulty so loop through each difficulty's item(s)
                    if not isinstance(value, dict):
                        value = {'Normal': value}

                    for diff in value:
                        for entry in value[diff]:
                            error |= check_item_name(entry['spec'], reason + ':' + cons['consequent'] + ':' + ITEM_FIELD)

                    return error

                if type(sc[ITEM_FIELD]) is list and type(sc[ITEM_FIELD][0]) is list:
                    # cond chain
                    for pred, item_list in sc[ITEM_FIELD]:
                        error |= check_predicate(pred, reason = reason + ':' + cons['consequent'] + ':' + ITEM_FIELD)
                        for entry in item_list:
                            error |= check_item_name(entry['spec'], reason + ':' + cons['consequent'] + ':' + ITEM_FIELD)
                else:
                    error |= check_showcase_item_field(cons, sc[ITEM_FIELD], reason)

        if 'progression_reward_items' in sc:
            ITEM_FIELD = 'progression_reward_items'

            # each "level block" specifies loot as a single item, or list (to alternate), or a cond chain thereof
            def check_progression_reward_block(entry):
                error = 0
                if isinstance(entry, dict):
                    if 'spec' in entry:
                        error |= check_item_name(entry['spec'], reason + ':' + cons['consequent'] + ':' + ITEM_FIELD)
                    elif 'multi' in entry:
                        for sub in entry['multi']:
                            error |= check_progression_reward_block(sub)
                    elif 'cond' in entry:
                        for pred, loot_list in entry['cond']:
                            error |= check_predicate(pred, reason = reason + ':' + cons['consequent'] + ':' + ITEM_FIELD)
                            error |= check_progression_reward_block(loot_list)
                    else:
                        error |= 1; print 'mal-formed progression reward entry in', reason + ':' + cons['consequent'] + ':' + ITEM_FIELD, entry
                elif isinstance(entry, list):
                    for sub in entry:
                        error |= check_item_name(sub['spec'], reason + ':' + cons['consequent'] + ':' + ITEM_FIELD)
                elif entry is None:
                    pass
                else:
                    error |= 1; print 'mal-formed progression reward entry in', reason + ':' + cons['consequent'] + ':' + ITEM_FIELD, entry
                return error

            for level_block in sc[ITEM_FIELD]:
                error |= check_progression_reward_block(level_block['loot'])

        for COND_FIELD in ('feature_random_item_count', 'ui_final_reward_bbcode', 'ui_final_reward_subtitle', 'ui_random_rewards_text'):
            if COND_FIELD in sc and type(sc[COND_FIELD]) is list:
                error |= check_cond_chain(sc[COND_FIELD], reason = reason + ':' + cons['consequent'] + ':' + COND_FIELD)
        for CONS_FIELD in ('ok_button_consequent',):
            if CONS_FIELD in sc:
                error |= check_consequent(sc[CONS_FIELD], reason = reason + ':' + cons['consequent'] + ':' + CONS_FIELD)
        for ASSET in ('villain_asset', 'corner_ai_asset'):
            if ASSET in sc:
                error |= require_art_asset(sc[ASSET], reason = reason+':'+ASSET)
        for FIELD in ('ui_villain_name',):
            if FIELD not in sc:
                error |= 1; print '%s: %s showcase consequent is missing mandatory field %s' % (reason, cons['consequent'], FIELD)
    else:
        error |= 1; print '%s: %s consequent has dialog as showcase but is missing showcase_hack' % (reason, cons['consequent'])
    return error

def range_overlap(a0, a1, b0, b1):
    if (a0 < b0) and (a1 < b0): return False
    if (a0 >= b1) and (a1 >= b1): return False
    return True

# keep track of how many map bases are spawned by time interval
# data structure is a list of [t,pop,templates] tuples ("spawn count is 'pop' at time 't'")
def spawn_pop_init(): return [[0,0,[]]]

# at time "when", add "incr" bases (may be negative to remove bases)
def spawn_pop_update(pop, when, incr, ui_name):
    i = 0
    while i < len(pop):
        if pop[i][0] >= when:
            break
        i += 1

    if i >= len(pop) or pop[i][0] != when:
        pop.insert(i, [when, pop[i-1][1], pop[i-1][2][:]])

    for j in xrange(i, len(pop)):
        pop[j][1] += incr
        if incr > 0:
            pop[j][2].append(ui_name)
        elif incr < 0:
            pop[j][2].remove(ui_name)

if 0: # test code
    p = spawn_pop_init()
    spawn_pop_update(p, 2, 100, "a")
    spawn_pop_update(p, 4, -100, "a")
    spawn_pop_update(p, 2, 100, "b")
    spawn_pop_update(p, 4, -100, "b")
    spawn_pop_update(p, 3, 50, "c")
    spawn_pop_update(p, 5, -50, "c")
    spawn_pop_update(p, 1, 50, "d")
    print p
    assert p == [[0, 0, []], [1, 50, ['d']], [2, 250, ['a','b','d']], [3, 300, ['a','b','c','d']], [4, 100, ['c','d']], [5, 50, ['d']]]
    sys.exit(0)


def check_hives_and_raids(kind, hives):
    error = 0
    max_region_pop = max(hives.get('region_pop',{}).values() + [1,])

    for spawn_array_name, spawn_array in filter(lambda k_v: k_v[0] == 'spawn' or k_v[0].startswith('spawn_for'), hives.iteritems()):
        spawn_pop = spawn_pop_init()

        # hack - instead of figuring out all the complex logic to handle infinitely-repeating events that mesh
        # with once-only events, instead just make a fixed number of copies of repeats, and ignore problems that
        # happen "far" in the future
        future_limit = float('inf')
        past_limit = time_now
        repeat_copies = 5

        if spawn_array_name == 'spawn':
            region_id = 'ALL'
        else:
            region_id = spawn_array_name.split('_for_')[1]

        for item in spawn_array:
            if item['template'] not in hives['templates']:
                error |= 1
                print 'hive %s: invalid template "%s"' % (spawn_array_name, item['template'])
            # stupid N^2 algorithm to look for overlap
            id_start = item['id_start']
            id_end = id_start + int(max_region_pop * item['num'])
            for other in spawn_array:
                if other is item: continue
                other_start = other['id_start']
                other_end = other_start + int(max_region_pop * other['num'])
                if range_overlap(id_start, id_end, other_start, other_end):
                    error |= 1
                    print 'hive %s: these two templates have overlapping ID ranges (note: num can be multiplied by %.2f for max_region_pop)!\n%s\n%s' % (spawn_array_name, max_region_pop, repr(item), repr(other))
            if item.get('active', 1):
                if (('start_time' in item) or ('end_time' in item)) and ('spawn_times' in item):
                    error |= 1
                    print 'hive %s: this template has both spawn_times and start_time/end_time specified\n%s' % (spawn_array_name, repr(item))

                if 'spawn_times' in item:
                    start_end_list = item['spawn_times']
                else:
                    start_end_list = [[item.get('start_time',-1), item.get('end_time',-1)]]

                repeat_interval = item.get('repeat_interval',0)
                if repeat_interval > 0:
                    # set time range we care about for checking hive populations

                    # don't care about anything after the last simulated run of any scheduled repeating event
                    future_limit = min(future_limit, start_end_list[-1][0] + (repeat_copies-1) * repeat_interval)
                    # DO care about old repeating runs, even if before current time
                    past_limit = min(past_limit, start_end_list[0][0])

                    # for repeating events, duplicate the start_end entries repeat_copies times
                    start_end_list = [[x[0] + repeat_interval*rep, x[1] + repeat_interval*rep] for rep in xrange(repeat_copies) for x in start_end_list]

                for start, end in start_end_list:
                    spawn_pop_update(spawn_pop, start if start > 0 else 0, item['num'], item['template']) # hives appear
                    if end > 0:
                        spawn_pop_update(spawn_pop, end, -item['num'], item['template']) # hives disappear

        # check future spawn population for abnormally low or high intervals
        if len(spawn_pop) > 1 and gamedata['game_id'] != 'mf': # ignore MF
            i = 0
            while spawn_pop[i+1][0] <= past_limit: # ignore intervals before past_limit
                i += 1

            for j in xrange(i, len(spawn_pop)):
                entry_t, pop, ui_names = spawn_pop[j]
                if entry_t >= future_limit: # ignore intervals further in the future than we've computed out
                    break
                warn = None
                if pop < 10:
                    warn  = 'LOW (%d)' % pop
                elif pop >= 1000:
                    warn = 'HIGH (%d)' % pop
                if warn:
                    interval = [entry_t, spawn_pop[j+1][0] if j+1 < len(spawn_pop) else -1]
                    ui_interval = map(lambda x: time.strftime('%Y %b %d', time.gmtime(x)) if x > 0 else 'infinity', interval)
                    print 'warning:', warn, 'number of hives set to spawn in region %s in the interval %d,%d (%s -> %s): %r' % (region_id, interval[0], interval[1], ui_interval[0], ui_interval[1], ui_names)
            #print spawn_pop[i:]

    for strid, data in hives['templates'].iteritems():
        error |= check_hive_or_raid(kind, kind+':'+strid, data)
    return error

# keep track of other bases upon which this base depends
class BDep(object):
    def __init__(self, id, deps, complist):
        self.id = id
        self.deps = deps
        self.complist = complist
        self.complete = False
        self.errored = False

def get_base_complist(pred):
    if pred['consequent'] == "PLAYER_HISTORY":
        return [(pred['key'], pred['value'])]
    elif pred['consequent'] == "IF":
        ret = []
        ret += get_base_complist(pred['then'])
        if 'else' in pred:
            ret += get_base_complist(pred['else'])
        return ret
    elif 'subconsequents' in pred:
        ret = []
        for subpred in pred['subconsequents']:
            ret += get_base_complist(subpred)
        return ret
    else:
        return []

def get_base_deps(pred, deplist, reason=''):
    if pred['predicate'] == "PLAYER_HISTORY":
        if pred['value'] == 0: # default starting value
            return
        deplist.append((pred['key'], pred['value']))
    elif pred['predicate'] == "AND":
        for subpred in pred['subpredicates']:
            get_base_deps(subpred, deplist, reason=reason)
    elif pred['predicate'] in ("AI_BASE_SHOWN", "AI_BASE_ACTIVE"):
        user_id = pred['user_id']
        if str(user_id) not in gamedata['ai_bases']['bases']:
            raise Exception('%s: AI base %d not found' % (reason, user_id))
        base = gamedata['ai_bases']['bases'][str(user_id)]
        if pred['predicate'] == "AI_BASE_SHOWN" and ('show_if' in base):
            p = base['show_if']
        elif ('activation' in base):
            p = base['activation']
        else:
            p = None
        if p:
            get_base_deps(p, deplist, reason=reason)

def check_ai_attack(name, data):
    error = 0
    if 'units' in data:
        for wave in data['units']:
            if ('direction' in wave) and (wave['direction'] not in gamedata['ai_attacks_client']['directions']):
                error |= 1
                print 'AI attack %s wave has bad direction %s' % (name, wave['direction'])
            MAX_DELAY = 10
            if ('delay' in wave) and wave['delay'] > MAX_DELAY:
                error |= 1
                print 'AI attack %s wave has excessive delay %d, it should be %d or less' % (name, wave['delay'], MAX_DELAY)
            for spec, v in wave.iteritems():
                if spec in ('direction','delay','spread'): continue
                if type(v) is dict:
                    for key in v:
                        if key.startswith('qt') and not key.endswith('y'):
                            error |= 1
                            print 'AI attack %s has bad key "%s" in wave %s, should be "qty"' % (name, key, repr(wave))
                    qty = v.get('qty',1)
                    force_level = v.get('force_level',-1)
                else:
                    qty = v
                    force_level = -1
                if (spec not in gamedata['units']) or type(qty) is not int or (qty > 30 and ('punishment' not in name)):
                    error |= 1
                    print 'AI attack %s has bad unit "%s" or quantity %s in wave %s' % (name, spec, repr(v), repr(wave))
                error |= check_unit_name(spec, name)
                maxlevel = len(gamedata['units'][spec]['max_hp'])
                if force_level > maxlevel:
                    error |= 1
                    print 'AI attack %s has unit "%s" at level %d beyond max of %d' % (name, spec, force_level, maxlevel)
    deplist = []
    complist = None
    if 'on_visit' in data:
        error |= check_consequent(data['on_visit'], reason = 'AI attack %s: on_visit' % name, context = 'ai_attack')
        if data['on_visit']['consequent'] != 'DISPLAY_MESSAGE':
            error |= 1
            print 'ai attack %s has bad on_visit consequent - on_visit for AI attacks must consist of only one DISPLAY_MESSAGE' % name
    if 'on_attack' in data:
        error |= check_consequent(data['on_attack'], reason = 'AI attack %s: on_attack' % name, context = 'ai_attack')
    if 'failure' in data:
        error |= check_consequent(data['failure'], reason = 'AI attack %s: failure' % name, context = 'ai_attack')
    if 'completion' in data:
        error |= check_consequent(data['completion'], reason = 'AI attack %s: completion' % name, context = 'ai_attack')
        complist = get_base_complist(data['completion'])
    if 'activation' in data:
        error |= check_predicate(data['activation'], reason = 'AI attack %s: activation' % name, context = 'ai_attack')
        get_base_deps(data['activation'], deplist, reason = 'AI attack %s: activation' % name)
    if 'show_if' in data:
        error |= check_predicate(data['show_if'], reason = 'AI attack %s: show_if' % name, context = 'ai_attack')

    if ('kind' in data) and ('analytics_tag' not in data) and data.get('activation',{}).get('predicate',None) != 'ALWAYS_FALSE':
        if gamedata['game_id'] != 'mf': # ignore MF
            error |= 1
            print 'AI attack %s (%s) missing analytics_tag' % (name, data.get('ui_name','UNKNOWN'))

    bdep = BDep(name, deplist, complist)
    return error, bdep, complist

def climate_allows_unit(data, spec):
    special_climate = data['name'] in ('ocean','air','space')

    if ('include_manufacture_categories' in data) and (spec['manufacture_category'] not in data['include_manufacture_categories']): return False
    if ('exclude_manufacture_categories' in data) and (spec['manufacture_category'] in data['exclude_manufacture_categories']): return False
    if data.get('exclude_air_units',False) and spec.get('flying',False): return False
    if data.get('exclude_ground_units',False) and (not spec.get('flying',False)):
        if special_climate:
            pass # special exception - ocean/air/space bases are allowed to have AI ground units defending them
        else:
            return False
    if ('include_units' in data) and (spec['name'] not in data['include_units']):
        if special_climate:
            pass # special exception - ocean/air/space bases are allowed to have AI units that break the rules
        else:
            return False
    if ('exclude_units' in data) and (spec['name'] in data['exclude_units']):
        if special_climate:
            pass # special exception - ocean/air/space bases are allowed to have AI units that break the rules
        else:
            return False

    return True

def check_ai_base_contents(strid, base, owner, base_type, ensure_force_building_levels = False):
    error = 0
    climate = base.get('base_climate', None)
    if climate:
        if climate not in gamedata['climates']:
            error |= 1; print 'ERROR: AI base %s has invalid climate "%s"' % (strid, climate)
        else:
            if gamedata['climates'][climate].get('deprecated',None):
                error |= 1; print 'ERROR: AI base %s has obsolete climate "%s", please change to "%s"' % (strid, climate, gamedata['climates'][climate]['deprecated'])

            climate_aura = gamedata['climates'][climate].get('applies_aura',None)
            if climate_aura == 'on_fire_lava_climate':
                if owner.get('tech',{}).get('lava_shield',0) < 1:
                    error |= 1; print 'ERROR: AI base %s is lava but its owner AI does not have the lava_shield tech' % (strid)

    climate_data = gamedata['climates'].get(climate, {'name':'unspecified'})

    # check deployment zone winding order
    if 'deployment_buffer' in base and type(base['deployment_buffer']) is dict and base['deployment_buffer']['type'] == 'polygon':
        verts = base['deployment_buffer']['vertices']
        last_delta = None
        for seg in zip(verts, [verts[(i+1)%len(verts)] for i in xrange(len(verts))]):
            delta = [seg[1][0]-seg[0][0], seg[1][1]-seg[0][1]]
            if last_delta:
                xp = delta[1]*last_delta[0]-delta[0]*last_delta[1]
                if xp < 0:
                    error |= 1; print 'ERROR: AI base %s deployment_buffer polygon has incorrect winding order, vertices should be %s' % (strid, list(reversed(verts)))
                    break
            last_delta = delta

    SCENERY_MAX = 9999
    if len(base.get('scenery',[])) >= SCENERY_MAX:
        print 'WARNING: AI base %s has excessively large number of scenery sprites (%d), please reduce!' % (strid, len(base['scenery']))

    if 'base_resource_loot' in base:
        for res in base['base_resource_loot']:
            if res not in gamedata['resources']:
                error |= 1; print 'AI base %s has invalid base_resource_loot entry "%s"' % (strid, res)
        if 'base_richness' in base:
            error |= 1; print 'AI base %s has base_resource_loot, therefore the base_richness setting is irrelevant and should be removed' % (strid,)
    elif not gamedata['ai_bases']['loot_table'] and base_type != 'quarry':
        error |= 1; print 'AI base %s needs a base_resource_loot table' % strid

    for KIND in ('scenery', 'buildings', 'units'):
        if KIND in base:
            for item in base[KIND]:
                if item['spec'] not in gamedata['inert' if KIND == 'scenery' else KIND] and ('%RESOURCE' not in item['spec']):
                    error |= 1
                    print 'ERROR: AI base %s has a "%s" entry with invalid spec "%s"' % (strid, KIND, item['spec'])
                    continue
                if KIND=='units':
                    error |= check_unit_name(item['spec'], 'AI base %s' % strid)
                    if not climate_allows_unit(climate_data, gamedata['units'][item['spec']]):
                        error |= 1
                        print 'ERROR: AI base %s has unit %s not allowed by climate %s' % (strid, item['spec'], climate)

                # check for climate-specific scenery with unspecified climate
                # this will cause wrong-climate-specific sprites to appear in bases with the default climate
                elif False and KIND == 'scenery' and base_type == 'home' and not (base.get('base_climate',None)) and ('base_climates' in gamedata['inert'][item['spec']]) and \
                     not any(item['spec'].startswith(x) for x in ('roadway','dirt_road','lightpost','concrete')):
                    error |= 1
                    print 'ERROR: AI base %s has climate-specific scenery sprite %s but no explicit base_climate' % (strid, item['spec'])

                max_level = -1
                if KIND == 'buildings' and ('%RESOURCE' not in item['spec']):
                    spec = gamedata['buildings'][item['spec']]
                    if spec.get('error',False):
                        error |= 1; print 'ERROR: AI base %s has an invalid building %s' % (strid, spec['name'])

                    max_level = len(spec['build_time'])
                    is_storage = False
                    # is_producer = False
                    has_exotic_resource = None
                    for res in gamedata['resources']:
                        has_this_res = False
                        if 'storage_'+res in spec:
                            has_this_res = True
                            is_storage = True
                        if 'produces_'+res in spec:
                            has_this_res = True
                            # is_producer = True
                        if has_this_res and (res not in ('iron','water')):
                            has_exotic_resource = (item['spec'], res)

                    # check that quarries do not have storage buildings (unsupported/exploitable code path)
                    if base_type == 'quarry' and is_storage:
                        error |= 1
                        print 'ERROR: quarry %s should not have a storage building (%s) in it!' % (strid, item['spec'])

                    if base_type != 'quarry' and has_exotic_resource and ('base_resource_loot' not in base):
                        error |= 1; print 'ERROR: AI base %s has a %s that will drop exotic resource "%s" loot. It should be using "base_resource_loot" instead of the old loot system' % (strid, has_exotic_resource[0], has_exotic_resource[1])

                elif KIND == 'units':
                    max_level = len(gamedata['units'][item['spec']]['max_hp'])

                if max_level >= 1:
                    level = item.get('force_level', item.get('level', 1))
                    if level <= 0 or level > max_level:
                        error |= 1
                        print 'ERROR: AI base %s has an object (%s) whose level is greater than the max (%d) for its type' % (strid, repr(item), max_level)

                    if ensure_force_building_levels and KIND == 'buildings' and ('force_level' not in item) \
                       and item['spec'] not in ('barrier','minefield',):
                        error |= 1
                        print 'ERROR: AI base %s has an building (%s) without a force_level setting' % (strid, repr(item))

                if KIND == 'units' and gamedata['units'][item['spec']].get('invis_on_hold',False):
                    if 'orders' in item and item['orders'][0]['state'] == 4 and item['orders'][0].get('aggressive',False):
                        error |= 1
                        print 'ERROR: AI base %s has a cloaked unit on hold-position but with \"aggressive\" enabled, meaning it will not stay cloaked:\n%s' % (strid, repr(item))
                if 'equipment' in item:
                    if type(item['equipment']) is not dict:
                        error |= 1
                        print 'ERROR: AI base %s has a %s with invalid "equipment": %s (must be a dictionary of {"slot_type":["item0","item1",...],...})' % (strid, KIND, repr(item['equipment']))
                    for slot_type, slots in item['equipment'].iteritems():
                        if slot_type not in gamedata['strings']['equip_slots']:
                                error |= 1
                                print 'ERROR: AI base %s has a %s with equipment on invalid slot type "%s"' % (strid, KIND, slot_type)
                        if slot_type == 'mine' and base_type == 'quarry':
                            error |= 1
                            print 'ERROR: Quarry %s: quarries do not support landmines' % (strid)
                        for slot in slots:
                            if type(slot) is dict:
                                item = slot
                            elif type(str(slot)) is str:
                                item = {'spec':slot}
                            else:
                                error |= 1; print 'ERROR: AI base %s has a %s equipped with invalid item "%r"' % (strid, KIND, slot)
                            if (item['spec'] not in gamedata['items']) or ('equip' not in gamedata['items'][item['spec']]) or \
                               (item.get('level',1) > gamedata['items'][item['spec']].get('max_level',1)):
                                error |= 1
                                print 'ERROR: AI base %s has a %s equipped with invalid item "%r"' % (strid, KIND, slot)
                            else:
                                equip_spec = gamedata['items'][item['spec']]
                                for effect in equip_spec['equip']['effects']:
                                    if effect['code'] == 'modstat' and effect['stat'] == 'on_destroy':
                                        conslist = effect['strength']
                                        for cons in conslist:
                                            if cons['consequent'] == 'SPAWN_SECURITY_TEAM':
                                                for secteam_name in cons['units']:
                                                    if not climate_allows_unit(climate_data, gamedata['units'][secteam_name]):
                                                        error |= 1
                                                        print 'ERROR: AI base %s has %s with item %r that spawns security team unit %s not allowed by climate %s' % (strid, item['spec'], slot, secteam_name, climate)
    if 'buildings' in base:
        error |= check_ai_base_contents_power(base['buildings'], strid)
    return error

def check_ai_base_contents_power(building_list, strid):
    error = 0

    if not (gamedata.get('enable_power', True)):
        return 0 # no power system

    if len(building_list) <= 1:
        return 0 # probably a dummy base

    produced = 0
    consumed = 0
    for obj in building_list:
        spec = gamedata['buildings'].get(obj['spec'], None)
        level = obj.get('force_level', obj.get('level', 1))
        if spec:
            if 'consumes_power' in spec:
                consumed += GameDataUtil.get_leveled_quantity(spec['consumes_power'], level)
            if 'provides_power' in spec:
                produced += GameDataUtil.get_leveled_quantity(spec['provides_power'], level)

    if produced <= 0:
        return 0 # tutorial or dummy base

    if produced < consumed:
        print 'WARNING, please fix: AI base %s consumes more power than it produces (%d consumed, %d produced)' % (strid, consumed, produced)
        # error |= 1 # don't break the build for now, until we fix the existing problem bases

    return error

def check_quarry(strid, base):
    error = 0
    slandlord_id = str(base.get('default_landlord_id','unknown'))
    if slandlord_id not in gamedata['ai_bases']['bases']:
        error |= 1; print 'Quarry %s default_landlord_id %s is not a valid AI base' % (strid, slandlord_id)
    else:
        error |= check_ai_base_contents(strid, base, gamedata['ai_bases']['bases'][slandlord_id], 'quarry')
    return error

def check_turf_reward(reward):
    error = 0
    for aura in reward['auras']:
        if aura['spec'] not in gamedata['auras']:
            error |= 1; print 'alliance_turf reward aura "%s" not found' % aura['spec']
        regions = aura.get('regions',[])
        for region in regions:
            error |= check_region_name(region, 'Alliance turf reward %s' % aura['spec'])
    return error


def check_hive_or_raid(kind, strid, base):
    error = 0

    if str(base['owner_id']) not in gamedata['ai_bases']['bases']:
        error |= 1
        print '%s owner %s refers to an invalid AI base' % (strid, base['owner_id'])
        return error

    if 'analytics_tag' not in base and base.get('activation',{}).get('predicate',None) != 'ALWAYS_FALSE':
        if gamedata['game_id'] != 'mf': # ignore MF
            error |= 1
            print '%s missing analytics_tag' % (strid,)

    if 'tech' in base:
        for tech_name in base['tech']:
            if tech_name not in gamedata['tech']:
                error |= 1
                print '%s (%s) refers to missing tech "%s"' % (strid, base['ui_name'], tech_name)

    if 'completion' in base:
        error |= check_consequent(base['completion'], reason = 'AI %s (%s): completion' % (strid, base['ui_name']), context = 'ai_base', context_data = base)
        #complist = get_base_complist(base['completion'])
    if 'failure' in base:
        error |= check_consequent(base['failure'], reason = 'AI %s (%s): failure' % (strid, base['ui_name']), context = 'ai_base', context_data = base)
    if 'on_visit' in base:
        error |= check_consequent(base['on_visit'], reason = 'AI %s (%s): on_visit' % (strid, base['ui_name']), context = 'ai_base', context_data = base)
    if 'on_attack' in base:
        error |= check_consequent(base['on_attack'], reason = 'AI %s (%s): on_attack' % (strid, base['ui_name']), context = 'ai_base', context_data = base)
    if 'activation' in base:
        error |= check_predicate(base['activation'], reason = 'AI %s (%s): activation' % (strid, base['ui_name']), context = 'ai_base', context_data = base)
        deplist = []
        get_base_deps(base['activation'], deplist, reason = 'AI %s (%s): activation' % (strid, base['ui_name']))
    if 'show_if' in base:
        error |= check_predicate(base['show_if'], reason = 'AI %s (%s): show_if' % (strid, base['ui_name']), context = 'ai_base', context_data = base)

    error |= check_ai_base_contents(strid, base, gamedata['ai_bases']['bases'][str(base['owner_id'])], kind)
    return error

def check_ai_base(strid, base):
    error = 0

    if ('analytics_tag' not in base) and base.get('activation',{}).get('predicate',None) != 'ALWAYS_FALSE':
        if gamedata['game_id'] != 'mf': # ignore MF
            error |= 1
            print 'AI base %s (%s) missing analytics_tag' % (strid, base['ui_name'])
    if 'activation' not in base:
        error |= 1
        print 'AI base %s missing "activation" predicate' % (strid)
    if 'portrait' not in base:
        error |= 1
        print 'AI base %s missing "portrait"' % (strid)
    else:
        error |= require_art_asset(base['portrait'], reason = 'AI base %s:portrait' % strid)

    if 'map_portrait' in base:
        error |= require_art_asset(base['map_portrait'], reason = 'AI base %s:map_portrait' % strid)

    if 'tech' not in base:
        error |= 1
        print 'AI base %s missing "tech"' % (strid)
    else:
        for tech_name in base['tech']:
            if tech_name not in gamedata['tech']:
                error |= 1
                print 'AI base %s refers to missing tech "%s"' % (strid, tech_name)

    if gamedata['game_id'] == 'fs' and base.get('auto_level'):
        error |= 1; print 'AI base %s should not have "auto_level" setting' % (strid)

    error |= require_art_asset(base['portrait'], 'AI base %s:portrait' % strid)

    for challenge in ('challenge_item','challenge_icon'):
        if challenge in base and type(base[challenge]) is list:
            error |= check_cond_chain(base[challenge], reason = strid+':'+challenge)

    # challenge_icon can be the result of a cond chain
    if 'challenge_icon' in base:
        challenge_icon_list = [value for pred, value in base['challenge_icon']] if type(base['challenge_icon']) is list else [base['challenge_icon'],]
        for entry in challenge_icon_list:
            if entry:
                error |= require_art_asset(entry, reason = 'AI base %s:challenge_icon' % strid)

    if 'item_loot' in base:
        error |= 1
        print 'ERROR: AI base %s has old-style item_loot table, please change it according to the instructions here: https://sites.google.com/a/spinpunch.com/developers/game-design/loot-tables' % strid

    if base.get('kind', None) == 'ai_attack':
        berror, bdep, complist = check_ai_attack(strid, base)
        error |= berror

    else:
        error |= check_ai_base_contents(strid, base, base, 'home',
                                        # make sure hitlist bases all have explicit levels
                                        ensure_force_building_levels = (base.get('ui_category',None) == 'hitlist'))

        deplist = []
        complist = None
        if 'completion' in base:
            error |= check_consequent(base['completion'], reason = 'AI base %s (%s L%d): completion' % (strid, base['ui_name'], base['resources']['player_level']), context = 'ai_base', context_data = base)
            complist = get_base_complist(base['completion'])
        if 'failure' in base:
            error |= check_consequent(base['failure'], reason = 'AI base %s (%s L%d): failure' % (strid, base['ui_name'], base['resources']['player_level']), context = 'ai_base', context_data = base)
        if 'on_visit' in base:
            error |= check_consequent(base['on_visit'], reason = 'AI base %s (%s L%d): on_visit' % (strid, base['ui_name'], base['resources']['player_level']), context = 'ai_base', context_data = base)
        if 'on_attack' in base:
            error |= check_consequent(base['on_attack'], reason = 'AI base %s (%s L%d): on_attack' % (strid, base['ui_name'], base['resources']['player_level']), context = 'ai_base', context_data = base)
        if 'activation' in base:
            error |= check_predicate(base['activation'], reason = 'AI base %s (%s L%d): activation' % (strid, base['ui_name'], base['resources']['player_level']), context = 'ai_base', context_data = base)
            get_base_deps(base['activation'], deplist, reason = 'AI base %s (%s L%d): activation' % (strid, base['ui_name'], base['resources']['player_level']))
        if 'show_if' in base:
            error |= check_predicate(base['show_if'], reason = 'AI base %s (%s L%d): show_if' % (strid, base['ui_name'], base['resources']['player_level']), context = 'ai_base', context_data = base)

        bdep = BDep(strid, deplist, complist)

    return error, bdep, complist

def check_ai_bases_and_attacks(ai_bases, ai_attacks):
    error = 0
    bdic = {}
    by_completion = {}

    for tech_name in ai_bases['ai_starting_conditions']['tech']:
        if tech_name not in gamedata['tech']:
            error |= 1
            print 'ai_starting_conditions refers to missing tech "%s"' % tech_name

    if 'ladder_pvp_bases' in gamedata['ai_bases']:
        for entry in gamedata['ai_bases']['ladder_pvp_bases']:
            if str(entry['base_id']) not in gamedata['ai_bases']['bases']:
                error |= 1; print 'ladder_pvp_base refers to invalid base_id %d' % entry['base_id']
            if 'activation' in entry:
                error |= check_predicate(entry['activation'], reason = 'ladder_pvp_bases:%d:activation' % entry['base_id'])
    for wave in ai_attacks['wave_table']:
        if wave['player_lacks'] not in gamedata['tech']:
            error |= 1
            print 'ai_attacks:wave_table:player_lacks refers to missing tech "%s"' % (wave['player_lacks'])
        for UNIT in ('major_unit','peon_unit','flavor_unit'):
            error |= check_unit_name(wave[UNIT], 'ai_attacks:wave_table:%s' % UNIT)
    for name, data in ai_attacks['attack_types'].iteritems():
        if str(data['attacker_id']) not in gamedata['ai_bases']['bases']:
            error |= 1
            print 'ai attack "%s" attacker_id %d not found in ai_bases/bases' % (name, data['attacker_id'])
        berror, bdep, complist = check_ai_attack(name, data)
        error |= berror
        bdic[name] = bdep
        if complist:
            for comp in complist:
                by_completion[comp] = bdep

    for strid, base in sorted(ai_bases['bases'].items(), key = lambda id_base: int(id_base[0])):
        strid = '%s (%s%s)' % (strid, base['ui_name'], (' L%d' % base['resources']['player_level']) if 'resources' in base else '')
        if base.get('kind', 'ai_base') == 'ai_attack':
            berror, bdep, complist = check_ai_attack(strid, base)
        else:
            berror, bdep, complist = check_ai_base(strid, base)
        error |= berror
        bdic[strid] = bdep
        if complist:
            for comp in complist:
                by_completion[comp] = bdep

    # Check for "orphan" AI bases and attacks that cannot be reached due to predicate chain mistakes
    # (yes, I know this should use some kind of spiffy tree search
    # algorithm, but I'm in a hurry, so brute-force it!)

    maxiter = 500
    for i in xrange(maxiter):
        done = True
        for bdep in bdic.itervalues():
            if bdep.complete or bdep.errored:
                continue
            done = False
            missing = False
            for comp in bdep.deps:
                if comp not in by_completion:
                    error |= 1
                    bdep.errored = True
                    print 'AI base or attack \"%s\" cannot be reached, because no other base or attack has a consequent to set PLAYER_HISTORY key %s to %d!' % (bdep.id, comp[0], comp[1])
                    missing = True
                    break
                if comp not in by_completion or (not by_completion[comp].complete):
                    missing = True
                    break
            if not missing:
                bdep.complete = True
        if done:
            break

    if i >= maxiter-1:
        error |= 1
        for bdep in bdic.itervalues():
            if not bdep.complete:
                print 'AI base or attack \"%s\" cannot be completed! check the chain of "activation" predicates' % bdep.id

    return error

# keep track of other quests upon which this quest depends
class QDep (object):
    def __init__(self, name, deps):
        self.name = name
        self.deps = deps # list of quest names
        self.complete = False

# pull quest dependencies out of a predicate
def get_quest_deps(pred, deplist):
    if pred['predicate'] == "QUEST_COMPLETED":
        deplist.append(pred['quest_name'])
    elif pred['predicate'] == "AND":
        for subpred in pred['subpredicates']:
            get_quest_deps(subpred, deplist)

def check_quests(quests):
    error = 0
    qdic = {}

    for key, data in quests.iteritems():
        if key != data.get('name',''):
            error |= 1
            print 'quest %s has missing or unmatched name field' % key

        for ART in ('icon',):
            if ART in data:
                error |= require_art_asset(data[ART], 'quest:'+key+':'+ART)
        if ('enable_desktop_quest_bar' in gamedata['client']) and ('icon' not in data):
            error |= 1; print 'quest %s is missing an "icon"' % key

        for PRED in ('goal','activation'):
            if check_predicate(data[PRED], reason = 'quest:'+key+':'+PRED):
                error |= 1
                print 'quest %s has bad %s predicate' % (key,PRED)
        for CONS in ('ui_accept_consequent','completion'):
            if (CONS in data) and check_consequent(data[CONS], reason = 'quest:'+key+':'+CONS):
                error |= 1; print 'quest %s has bad %s consequent' % (key,CONS)

        if 'ui_description' in data and type(data['ui_description']) is list:
            error |= check_cond_chain(data['ui_description'], reason = 'quest:'+key+':ui_description')

        for BADFIELD in ('ui_instruction','ui_descriptions'):
            if BADFIELD in data:
                error |= 1; print 'quest %s has typo: "%s"' % (key, BADFIELD)

        if ('tips' in data):
            error |= check_logic(data['tips'], reason = 'quest:'+key+':tips')

        if not (('reward_consequent' in data) or \
                (data.get('reward_xp',0) > 0 and gamedata['player_xp']['quests'] > 0) or \
                data.get('reward_gamebucks',0) > 0 or \
                sum((data.get('reward_'+res,0) for res in gamedata['resources']),0) > 0):
            error |= 1
            if data.get('reward_xp',0) > 0:
                print 'quest %s has no rewards (reward_xp does not work if gamedata.player_xp.quests is 0!)' % key
            else:
                print 'quest %s has no rewards' % key

        # this already happens in a bunch of quests, and we haven't done anything about it...
#        if data.get('reward_xp',0) > 0 and data.get('reward_gamebucks',0) > 0:
#            error |= 1; print 'quest %s gives both gamebucks and XP, which will overlap in the GUI' % key

        if ('reward_give_units' in data):
            error |= 1
            print 'quest %s has obsolete reward_give_units field, replace with reward_consequent:GIVE_LOOT' % key

        if ('reward_consequent' in data):
            cons = data['reward_consequent']

            error |= check_consequent(cons, reason = 'quest:'+key, context = 'quest')

            if cons['consequent'] == 'GIVE_UNITS':
                if key not in ('unlock_blaster_droids','unlock_machine_gunners'):
                    error |= 1
                    print 'quest %s has bad GIVE_UNITS reward consequent - this is for special cases ONLY' % key
            elif cons['consequent'] == 'GIVE_LOOT':
                if cons['reason_id'] != key:
                    error |= 1
                    print 'quest %s GIVE_LOOT reward consequent reason_id must be %s' % (key,key)

                # check the GIVE_LOOT reward consequent - since the
                # missions dialog GUI code needs to display this loot
                # table, there are restrictions on what it can
                # contain. If you want more complex loot tables, you must
                # update missions_dialog_select_mission() in main.js!

                if len(cons['loot']) > 1:
                    error |= 1
                    print 'quest %s GIVE_LOOT cannot give more than one thing (due to GUI display space limit)' % key
                if ('spec' in cons['loot'][0]):
                    # a single item
                    if cons['loot'][0]['spec'].startswith('packaged_'):
                        # packaged units are parsed by the GUI as a special case
                        if (cons['loot'][0]['spec'][9:] not in gamedata['units']):
                            error |= 1
                            print 'quest %s GIVE_LOOT reward should only contain base-level units' % key
                    else:
                        pass # some other kind of item
                elif ('multi' in cons['loot'][0]):
                    if cons['loot'][0]['multi'][0]['table'] != 'sexy_unlocked_unit':
                        error |= 1
                        print 'quest %s GIVE_LOOT reward multi table should be sexy_unlocked_unit' % key
                else:
                    error |= 1
                    print 'quest %s GIVE_LOOT consequent is too complex for the GUI code to display' % key

        if data.get('reward_res3',0) > 0 and \
           ('reward_consequent' in data or
            'reward_heal_all_units' in data or
            'reward_give_units' in data or
            'reward_heal_all_buildings' in data):
            error |= 1; print 'quest %s gives both res3 and units/items/healing, which will overlap in the GUI' % key

        deplist = []
        if 'activation' in data:
            get_quest_deps(data['activation'], deplist)
        for dep in deplist:
            if dep not in quests:
                error |= 1
                print 'quest %s requires missing quest %s to activate' % (key, dep)
        qdic[key] = QDep(key, deplist)

    # Check for "orphan" quests that cannot be completed due to predicate chain mistakes
    # (yes, I know this should use some kind of spiffy tree search
    # algorithm, but I'm in a hurry, so brute-force it!)

    maxiter = 500
    for i in xrange(maxiter):
        done = True
        for qdep in qdic.itervalues():
            if qdep.complete:
                continue
            done = False
            missing = False
            for depname in qdep.deps:
                if (depname not in qdic) or (not qdic[depname].complete):
                    missing = True
                    break
            if not missing:
                qdep.complete = True
        if done:
            break

    if i >= maxiter-1:
        error |= 1
        for qdep in qdic.itervalues():
            if not qdep.complete:
                print 'quest %s cannot be completed! check the chain of "activation" predicates' % qdep.name
    return error


def check_achievement_category(name, data):
    error = 0
    for PRED in ('activation', 'show_if'):
        if (PRED in data) and check_predicate(data[PRED], reason = 'achievement_category:'+name+':'+PRED):
            error |= 1
            print 'achievement category %s has bad %s predicate' % (name, PRED)
    if data['name'] != name:
        error |= 1; print 'achievement category %s "name" must be "%s", not "%s"' % (name, name, data['name'])
    return error

def check_achievements(achievements):
    error = 0

    for key, data in achievements.iteritems():
        if key != data.get('name',''):
            error |= 1
            print 'achievement %s has missing or unmatched name' % key
        if ('goal' not in data):
            error |= 1
            print 'achievement %s missing a "goal"' % key
        if ('icon' not in data):
            error |= 1
            print 'achievement %s missing an "icon"' % key
        else:
            error |= require_art_asset(data['icon'], key+':icon')
        if ('category' not in data) or (data['category'] not in gamedata['achievement_categories']):
            error |= 1
            print 'achievement %s has invalid category %s - must be a member of gamedata.achievement_categories' % (key, data.get('category','MISSING'))
        for PRED in ('activation', 'show_if', 'goal'):
            if (PRED in data) and check_predicate(data[PRED], reason = 'achievement:'+key+':'+PRED):
                error |= 1
                print 'achievement %s has bad %s predicate' % (key, PRED)

    return error

def check_achievement_name(name, context):
    error = 0
    if name not in gamedata['achievements']:
        error |= 1; print '%s refers to missing achievement "%s"' % (context, name)
    return error

def check_daily_tip(tip):
    error = 0
    if ('repeat_interval' in tip) and (('start_time' not in tip) or ('end_time' not in tip)):
        error |= 1
        print 'daily tip/message %s needs start_time and end_time since it is using repeat_interval' % (tip['name'])
    if 'show_if' in tip:
        if check_predicate(tip['show_if'], reason='%s:show_if' % tip['name']):
            error |= 1
            print 'daily tip %s has bad show_if predicate' % (tip['name'])
    for c in ('understood_button_consequent', 'link_button_consequent', 'consequent'):
        if c in tip:
            if check_consequent(tip[c], reason='%s:%s' % (tip['name'],c), context='daily_tip'):
                error |= 1
                print 'daily tip %s has bad %s' % (tip['name'], c)
    for FIELD in ('understood_button_url','info_button_url'):
        if FIELD in tip:
            error |= check_url(tip[FIELD], reason = '%s:%s' % (tip['name'],FIELD))
    return error

def check_daily_message(msg):
    error = 0
    error |= check_misspellings(msg, set(['show_if','attachments']), 'daily_message:%s' % msg['name'])
    if ('repeat_interval' in msg):
        if (('start_time' not in msg) or ('end_time' not in msg)):
            error |= 1
            print 'daily tip/message %s needs start_time and end_time since it is using repeat_interval' % (msg['name'])
        if ('expire_at' in msg):
            error |= 1
            print 'daily tip/message %s is using repeat_interval, so change "expire_at" to "end_time"' % (msg['name'])
    if 'show_if' in msg:
        if check_predicate(msg['show_if'], reason='%s:show_if' % msg['name']):
            error |= 1
            print 'daily message %s has bad show_if predicate' % (msg['name'])
    if 'attachments' in msg:
        for att in msg['attachments']:
            if att['spec'] not in gamedata['items']:
                error |= 1
                print 'daily message %s has bad attachment item %s' % (msg['name'], att['spec'])
    return error

def check_daily_banner(ban):
    error = 0
    if 'show_if' in ban:
        error |= check_predicate(ban['show_if'], reason='%s:show_if' % ban['name'])
    if 'on_view' in ban:
        error |= check_consequent(ban['on_view'], reason='%s:on_view' % ban['name'])
    if type(ban['spin_header_content']) is list:
        error |= check_cond_chain(ban['spin_header_content'], reason='%s:content' % ban['name'])
    return error

def check_event_schedule(schedule):
    error = 0
    for item in schedule:
        if item['name'] not in gamedata['events']:
            error |= 1
            print 'event schedule refers to missing event "%s"' % item['name']
    return error

def check_events(events):
    error = 0
    for key, data in events.iteritems():
        if data['name'] != key:
            error |= 1
            print 'event %s "name" mismatch: "name" should be %s and not %s' % (key, key, data['name'])
        if data.get('kind','MISSING') not in ('event_tutorial', # newbie tutorial guy-in-corner
                                              'current_event', # event guy-in-corner
                                              'current_event_store', # event store open
                                              'current_quarry_contest', # (obsolete) legacy regional quarry tournament
                                              'current_trophy_pve_challenge', # (obsolete) PvE trophy tournament
                                              'current_trophy_pvp_challenge', # PvP point tournament
                                              'current_stat_tournament', # Scores2 stat tournament
                                              'facebook_sale', 'bargain_sale'
                                              ):
            error |= 1; print 'event %s has invalid kind "%s"' % (key, data.get('kind','MISSING'))
        for ASSET in ('console_portrait', 'logo', 'icon'):
            if ASSET in data:
                error |= require_art_asset(data[ASSET], key+':'+ASSET)
        if ('activation' in data) and check_predicate(data['activation'], reason = 'event:'+key+':activation'):
            error |= 1
            print 'event %s has bad activation predicate' % (key)
        for CONS in ('prizes_action', 'fight_button_action', 'map_battle_button_action'):
            if CONS in data:
                if CONS == 'fight_button_action' and 'region_map' in data[CONS]: continue # old legacy option
                error |= check_consequent(data[CONS], reason = 'event:'+key+':'+CONS)

        if ('chain' in data):
            for pred, ch in data['chain']:
                if check_predicate(pred, reason='event:chain'):
                    error |= 1
                    print 'event %s has bad chain predicate' % (key)
                if ('console_portrait' in ch):
                    error |= require_art_asset(ch['console_portrait'], key+':console_portrait')
                # check for a common copy/paste typo
                if ('ui_speech' in ch):
                    if ' 1 more levels' in ch['ui_speech']:
                        error |= 1; print 'event %s has ui_speech typo: %r' % (key, ch['ui_speech'])
                if 'fight_button_action' in ch:
                    if 'visit_ladder_rival' in ch['fight_button_action']:
                        pass
                    else:
                        want_kind = None
                        want_base = None
                        if 'call_attack' in ch['fight_button_action']:
                            want_kind = 'ai_attack'
                            want_base = ch['fight_button_action']['call_attack']
                        elif 'visit_base' in ch['fight_button_action']:
                            want_kind = 'ai_base'
                            want_base = ch['fight_button_action']['visit_base']
                        else:
                            error |= 1
                            print 'event %s had bad fight_button_action: %s' % (key, repr(ch['fight_button_action']))
                        if want_base:
                            if str(want_base) in gamedata['ai_bases']['bases']:
                                actual_kind = gamedata['ai_bases']['bases'][str(want_base)].get('kind', 'ai_base')
                                if want_kind != actual_kind:
                                    error |= 1
                                    print 'event %s fight_button_action for %s %s is wrong, it should be "%s"' % (key, want_kind, str(want_base), 'call_attack' if (actual_kind=='ai_attack') else 'visit_base')
                            else:
                                error |= 1
                                print 'event %s fight_button_action refers to missing AI base or attack: %s (%s)' % (key, repr(want_base), repr(ch['fight_button_action']))
                            if pred['predicate'] in ('AI_BASE_SHOWN','AI_BASE_ACTIVE') and pred['user_id'] != want_base:
                                error |= 1; print 'event %s predicate %s mismatch with fight_button_action %s' % (key, repr(pred), repr(ch['fight_button_action']))
        if 'stat' in data:
            error |= check_scores2_stat(data['stat'], key)
        if 'info_url' in data:
            error |= check_url(data['info_url'], reason = 'event:%s' % key)
        if 'icon' in data:
            require_art_asset(data['icon'], key+':icon')
    return error

def check_dialog_widget(name, data):
    error = 0
    for FIELD in ('xy', 'dimensions'):
        if FIELD == 'dimensions' and data['kind'] == 'Dialog': continue
        if FIELD not in data:
            error |= 1; print '%s missing mandatory field %s' % (name, FIELD)

    if 'array' in data:
        if data['array_offset'][0] == -1 or data['array_offset'][1] == -1:
            if 'array_max_dimensions' not in data:
                error |= 1; print '%s has array_offset of -1 but no array_max_dimensions' % (name)

    if data['kind'] == 'Dialog' and data['dialog'] not in gamedata['dialogs']:
        error |= 1; print '%s is a Dialog widget but dialog "%s" not found in gamedata.dialogs' % (name, data['dialog'])

    for k, v in data.iteritems():
        # detect fields that should point to art assets
        if v and (('asset' in k) or ('bg_image' in k) or ('sound' in k)) and (k not in ('bg_image_resizable','bg_image_justify','push_bg_image','mouseover_sound')) and ('bg_image_offset' not in k):
            if type(v) is list:
                vlist = v
            else:
                vlist = [v,]
            for entry in vlist:
                error |= require_art_asset(entry, name+':'+k)
#    for FIELD in ('asset', 'bg_image'):
#        if (FIELD in data) and data[FIELD]:
#            error |= require_art_asset(data[FIELD], name+':'+FIELD)
    return error

def check_dialog(name, data):
    error = 0
    if ('bg_image' in data) and data['bg_image']:
        error |= require_art_asset(data['bg_image'], name+':bg_image')
    for wname, wdata in data['widgets'].iteritems():
        error |= check_dialog_widget(name+':'+wname, wdata)
    return error

def check_titles(data):
    error = 0
    if data['default_title'] not in data['titles']:
        error |= 1; print 'default_title not in titles'
    for name, title in data['titles'].iteritems():
        for PRED in ('show_if', 'requires'):
            if PRED in title:
                error |= check_predicate(title[PRED], name+':'+PRED)
    return error

def check_climate(name, data):
    error = 0
    for ASSET in ('backdrop', 'backdrop_whole'):
        if ASSET in data:
            if type(data[ASSET]) is dict:
                for key, val in data[ASSET].iteritems():
                    error |= require_art_asset(val, name+':'+ASSET+':'+key)
            else:
                error |= require_art_asset(data[ASSET], name+':'+ASSET)
    if 'building_bases' in data:
        for k, asset in data['building_bases'].iteritems():
            error |= require_art_asset(asset, name+':'+asset)

    if 'backdrop_tiles' in data:
        error |= require_art_asset(data['backdrop_tiles']['friendly'], name+':backdrop_tiles:friendly')
        error |= require_art_asset(data['backdrop_tiles']['hostile'], name+':backdrop_tiles:hostile')
    if 'applies_aura' in data:
        if data['applies_aura'] not in gamedata['auras']:
            error |= 1
            print 'climate %s refers to missing aura %s' % (name, data['applies_aura'])
    if ('ui_name' not in data):
        error |= 1; print 'climate %s needs a ui_name' % (name)
    if data.get('name',None) != name:
        error |= 1; print 'climate %s needs a "name":%s' % (name, name)

    for FIELD in ('airborne','spaceborne','no_air_units','underground'):
        if FIELD in data:
            error |= 1; print 'climate %s has obsolete field %s' % (name, FIELD)
    for FIELD in ('include_manufacture_categories', 'exclude_manufacture_categories'):
        if FIELD in data:
            for entry in data[FIELD]:
                if (entry not in gamedata['strings']['manufacture_categories']):
                    error |= 1; print 'climate %s has bad manufacture_category restriction %s' % (name, entry)
    for FIELD in ('include_units', 'exclude_units'):
        if FIELD in data:
            for entry in data[FIELD]:
                if entry not in gamedata['units']:
                    error |= 1; print 'climate %s has bad unit restriction %s' % (name, entry)

    return error

def check_abtest(name, data):
    error = 0
    if 'eligible' in data and type(data['eligible']) is dict: # some legacy "eligibles" are strings
        error |= check_predicate(data['eligible'], reason='abtest:'+name)
    if 'default_group' not in data:
        error |= 1; print 'A/B test %s missing default_group' % (name,)
    return error

def check_resource(name, data):
    error = 0
    if data['name'] != name:
        error |= 1; print 'resource %s name mismatch' % (name,)

    for FIELD in ('name', 'ui_name', 'ui_name_lower', 'storage_building', 'harvester_building', 'icon_small', 'ui_description'):
        if FIELD not in data:
            error |= 1; print 'resource %s missing field %s' % (name, FIELD)

    for BLDG in ('storage_building', 'harvester_building'):
        if data[BLDG] not in gamedata['buildings']:
            error |= 1; print 'resource %s %s invalid' % (name, BLDG)
    for ART in ('icon_small',):
        error |= require_art_asset(data[ART], name+':'+ART)

    for FX in ('harvest_effect', 'loot_effect'):
        if FX in data:
            error |= check_visual_effect('resources:'+name, data[FX])
    for PRED in ('show_if', 'loot_storage_warning_if'):
        if PRED in data:
            error |= check_predicate(data[PRED], 'resources:'+name+':'+PRED)
    return error

def check_store_sku(sku_name, sku):
    error = 0

    expect_items = None
    expect_items_unique_equipped = None
    expect_library_preds = None

    if 'item' in sku:
        if sku['item'].startswith('leader_'):
            expect_items_unique_equipped = set([gamedata['items'][sku['item']]['unique_equipped']])
        else:
            # guard against typos where a predicate refers to the wrong item or level
            expect_items = set([sku['item']])

            match = level_re.match(sku['item'])
            if match: # per-level item
                # allow any item of lesser level (still might not protect against all typos!)
                root = match.group('root')
                my_level = int(match.group('level'))
                for level in xrange(1, my_level+1):
                    expect_items.add(root + ('_L%d' % level))

            # special case to support stinger_blueprint in TR
            if sku['item'].endswith('stinger_gunner_blueprint'):
                expect_items.add(sku['item'][:-len('stinger_gunner_blueprint')] + 'stinger_blueprint')

        if '_blueprint' in sku['item']:
            # guard against typos where a library predicate of the wrong name or level is listed
            expect_library_preds = set()

            match = level_re.match(sku['item'])
            if match: # per-level blueprint
                # allow any blueprint of same or lesser level (still might not protect against all typos!)
                root = match.group('root')[:-len('_blueprint')]
                my_level = int(match.group('level'))
                for level in xrange(1, my_level+1):
                    expect_library_preds.add(root + ('_unlocked_L%d' % level))
            else: # non-per-level blueprint
                expect_library_preds.add(sku['item'][:-len('_blueprint')]+'_unlocked')


    for PRED in ('activation', 'requires', 'collected', 'show_if'):
        if PRED in sku:
            error |= check_predicate(sku[PRED], reason=sku_name+':'+PRED, expect_items=expect_items, expect_items_unique_equipped=expect_items_unique_equipped, expect_library_preds=expect_library_preds)

    for ASSET in ('icon', 'mouseover_sound'):
        if (ASSET in sku):
            error |= require_art_asset(sku[ASSET], sku_name+':'+ASSET)

    if 'mouseover_effect' in sku:
        error |= check_visual_effect('%s:mouseover_effect' % sku_name, sku['mouseover_effect'])

    if 'skus' in sku: # hierarchy
        for subsku in sku['skus']:
            error |= check_store_sku(sku_name+':'+subsku.get('name',subsku.get('item','unknown')), subsku)

    else: # single SKU
        if 'item' in sku:
            if sku['item'] not in gamedata['items']:
                error |= 1; print 'store sku %s for nonexistent item %s' % (sku_name, sku['item'])

        if 'spell' in sku and sku['spell'] not in gamedata['spells']:
            error |= 1; print 'store sku %s refers to invalid spell "%s"' % (sku_name, sku['spell'])

        if 'loot_table' in sku and sku['loot_table'] not in gamedata['loot_tables']:
            error |= 1; print 'store sku %s refers to invalid loot table "%s"' % (sku_name, sku['spell'], sku['loot_table'])

        if 'price' in sku and type(sku['price']) is list:
            if 'item' not in sku or 'spell' in sku:
                error |= 1; print 'store sku %s has cond-chain price but this is only supported for "item" SKUs not "spell" skus' % sku_name
            error |= check_cond_chain(sku['price'], reason = 'sku %s: price' % sku_name)

        if 'on_purchase' in sku: error |= check_consequent(sku['on_purchase'], reason='sku:'+sku_name+':on_purchase')
        if ('price_currency' in sku):
            if sku['price_currency'].startswith('item:'):
                item_name = sku['price_currency'].split(':')[1]
                if item_name not in gamedata['items']:
                    error |= 1
                    print 'store sku %s refers to nonexistent item "%s"' % (sku_name, item_name)
                item = gamedata['items'][item_name]
                assert item['max_stack'] > 100
                if 'store_icon' not in item:
                    error |= 1
                    print 'store sku %s currency item "%s" needs a store_icon' % (sku_name, item_name)
            elif sku['price_currency'].startswith('score:'):
                stat_name = sku['price_currency'].split(':')[1]
                if stat_name not in ('trophies_pvp', 'trophies_pvv'):
                    error |= 1
                    print 'store sku %s invalid currency stat "%s"' % (sku_name, stat_name)
                if 'INSUFFICIENT_'+stat_name.upper() not in gamedata['errors']:
                    error |= 1
                    print 'store sku %s calls for INSUFFICIENT_'+stat_name.upper()+' which needs to be in errors_gamespecific.json' % (sku_name)
                if ('score' not in gamedata['strings']['requirements_help']) or (stat_name not in gamedata['strings']['requirements_help']['score']):
                    error |= 1
                    print 'store sku %s calls for strings.json: requirements_help.score.%s' % (sku_name, stat_name)
    if 'jewel' in sku:
        if type(sku['jewel']) is list and (len(sku['jewel']) == 0 or type(sku['jewel'][0]) is dict):
            error |= 1; print 'store sku %s "jewel" must be single predicate' % (sku_name)
        else:
            error |= check_predicate(sku['jewel'], reason='sku:'+sku_name+':jewel')

    if 'ui_banner' in sku:
        if type(sku['ui_banner']) is list:
            error |= check_cond_chain(sku['ui_banner'], reason = 'sku %s: ui_banner' % sku_name)

    if 'ui_name' in sku:
        if '\n' in sku['ui_name']:
            error |= 1; print 'store sku %s: ui_name should not have "\\n" in it (spacing is now handled automatically by shrinking the font)' % (sku_name)

    return error

def check_starting_conditions(starting_conditions):
    error = 0
    starting_conditions = gamedata['starting_conditions']
    if type(starting_conditions['protection_time']) is list:
        error |= check_cond_chain(starting_conditions['protection_time'], reason = 'starting_conditions:protection_time')
    for tech, level in starting_conditions['tech'].iteritems():
        if tech not in gamedata['tech']:
            error |= 1; print 'starting_conditions: tech "%s" does not exist' % tech
    for aura in starting_conditions.get('player_auras',[]):
        if aura['name'] not in gamedata['auras']:
            error |= 1; print 'starting_conditions: aura "%s" does not exist' % aura
    for unit in starting_conditions['units'] + starting_conditions['attacking_units']:
        if unit['spec'] not in gamedata['units']:
            error |= 1; print 'starting_conditions: unit "%s" does not exist' % unit['spec']

    has_foreman = False
    for building in starting_conditions['buildings']:
        spec = gamedata['buildings'].get(building['spec'],None)
        if not spec:
            error |= 1; print 'starting_conditions: building "%s" does not exist' % building['spec']
        else:
            has_foreman = ('provides_foremen' in spec)

    if gamedata.get('enable_multiple_foremen',False) and (not has_foreman):
        # this is not a strict requirement of the game engine, but the GUI experience will be weird
        # when you "build a builder without a builder"
        error |= 1; print 'starting_conditions: needs a building with provides_foremen'

    for key in ('returning_veteran_region','force_initial_region'):
        if key in starting_conditions:
            region_list = starting_conditions[key]
            if type(region_list) is not list: region_list = [region_list,]
            for region in region_list:
                if region not in gamedata['regions'] or (not gamedata['regions'][region].get('auto_join',1)):
                    error |= 1; print 'starting_conditions: region "%s" has auto_join off, probably not suitable for new/returning players?' % region

    return error

def check_loading_screens(loading_screens):
    error = 0
    for kind in loading_screens:
        for name, data in loading_screens[kind].iteritems():
            if type(data) in (str,unicode):
                if data[0] == '#': continue # HTML color
                require_art_file(data)
            else:
                for FIELD in ('background_color', 'parallax_strength', 'animation_style', 'duration'):
                    if FIELD not in data:
                        error |= 1; print 'loading screen "%s" missing mandatory field "%s"' % (name, FIELD)
                for layer in data['layers']:
                    # this is not a complete check - needs more thoroughness!
                    for FIELD in ('image', 'dimensions'):
                        if FIELD not in layer:
                            error |= 1; print 'loading screen "%s" layer missing mandatory field "%s"' % (name, FIELD)
                    if 'image' in layer:
                        require_art_file(layer['image'])

    if 'loading_screen_image_url' in gamedata:
        error |= 1; print 'obsolete loading_screen_image_url, convert to new format'

    return error

# art source file checking - make sure that JSON format is sane
# ref_list is a set to which to add any files needed for this asset
def get_art_source_files(name, asset, ref_list):
    error = 0
    for statename, state in asset['states'].iteritems():
        if 'subassets' in state:
            for subasset in state['subassets']:
                if type(subasset) is dict:
                    subname = subasset['name']
                    substate = subasset.get('state', 'normal')
                else:
                    subname = subasset
                    substate = 'normal'
                error |= require_art_asset(subname, name+':'+statename+':subassets')
                if not error:
                    if substate not in gamedata['art'][subname]['states']:
                        error |= 1; print 'art asset %s references missing subasset %s (state %s)' % (name, subname, substate)

        if 'images' in state:
            for imagename in state['images']:
                ref_list.add(imagename)
        if 'tint_mask' in state:
            ref_list.add(state['tint_mask'])

        if 'audio' in state:
            file = state['audio']
            ref_list.add(file.replace('$AUDIO_CODEC', 'ogg'))
            ref_list.add(file.replace('$AUDIO_CODEC', 'mp3'))

    return error

def inventory_art(dir, root):
    for f in os.listdir(dir):
        if f == '.DS_Store': continue
        abspath = os.path.join(dir, f)
        relpath = os.path.join(root, f)
        if os.path.isdir(abspath):
            for x in inventory_art(abspath, relpath):
                yield x
        else:
            yield relpath

def check_art(art, report_unreferenced_art_files = True, report_unreferenced_art_assets = True):
    # optionally also warn about extra files found in art/ that aren't referenced or assets in gamedata.art that aren't referenced

    # build list of files in the 'gameclient/art' directory
    file_list = [name for name in inventory_art('../gameclient/art', 'art')]

    # ignore json and swf files since they have hardcoded references
    file_list = filter(lambda x: x.split('.')[-1] not in ('json','swf'), file_list)

    file_list = set(file_list)
    file_list.add('*') # handle "*" repeats in art JSON

    error = 0
    ref_list = set() # list of files required by art JSON

    # make sure hard-coded art files are present
    ref_list |= required_art_files

    ref_list |= set([gamedata['store']['fb_order_dialog_gamebucks_icon'],
                     gamedata['store']['fb_order_dialog_generic_icon']] + \
                    ['art/ui/spin_footer_warbird.jpg',
                     'art/mars_frontier_icon_50x50.png',
                     'art/mars_frontier_feed_icon.jpg',
                     'art/mars_frontier_feed_icon3.jpg',
                     'art/facebook_credit_icon_100x100.png',
                     'art/daily_tips/%s_pageable_generic.jpg' % gamedata['game_id'],
                     'art/anon_portrait.jpg',
                     'art/anon_portrait2.jpg',
                    ])
    ref_list |= set(['art/daily_tips/'+tip['image'] for tip in gamedata['daily_tips'] if ('image' in tip)])
    #ref_list |= set(['art/facebook_assets/'+viral['image'] for viral in gamedata['virals'].itervalues() if (type(viral) is dict and ('image' in viral))])

    for name, asset in art.iteritems():
        error |= get_art_source_files(name, asset, ref_list)

    # check for missing files referenced by art.json
    missing_files = ref_list - file_list
    if missing_files:
        print 'MISSING ART FILES required by art.json and daily_tips.json:\n   ', '\n    '.join(sorted(list(missing_files)))
        error = 1

    if report_unreferenced_art_files:
        extra_files = file_list - ref_list
        for f in sorted(extra_files):
            print 'warning: unreferenced art file on disk that art.json and daily_tips.json do not require:', f

    if report_unreferenced_art_assets:
        extra_assets = set(art.iterkeys()) - required_art_assets
        for a in sorted(extra_assets):

            asset = art[a]

            if asset.get('pragma_used',False): continue # asset manually marked as "don't warn about this"

            # don't complain about auto-built 3D assets
            # XXX hacky way of detecting 3D assets - have makeart.mcp add something here
            if 'normal' in asset['states'] and asset['states']['normal'].get('images',None):
                test = asset['states']['normal']['images'][0]
                if ('normalsize' in test) or ('iconsize' in test) or ('herosize' in test):
                    continue
                fields = test.split('/')
                if len(fields) >= 3 and fields[2].startswith(fields[1]+'_'):
                    # e.g. "art/water_harvester3/water_harvester3_normal_v1_8.png"
                    continue

            print 'warning: unreferenced art.json asset:', a

    return error

def check_adnetwork(name, data):
    error = 0
    if 'master_filter' in data:
        error |= check_predicate(data['master_filter'], reason='adnetwork:'+name)
    for evname, evdata in data['events'].iteritems():
        error |= check_predicate(evdata['predicate'], reason='adnetwork:'+name)
    return error

def check_promo_codes(promo_codes):
    error = 0
    for name, data in promo_codes.iteritems():
        reason = 'promo_code:%s' % name
#        if data.get('name',None) != name:
#            error |= 1; print '%s needs a "name" that matches its key name' % reason
        for PRED in ('requires','show_if'):
            if PRED in data:
                error |= check_predicate(data[PRED], reason=reason+':'+PRED)
        for CONS in ('on_login',):
            error |= check_consequent(data[CONS], reason=reason+':'+CONS)

    return error

def check_battle_stars(battle_stars):
    error = 0
    for name, pred in battle_stars.iteritems():
        error |= check_predicate(pred, reason='battle_stars:'+name)
    return error

def check_server(server):
    error = 0
    for PRED in ('anti_bullying_defender_filter', 'bad_internet_exception_log_filter', 'stale_account_reset_criteria', 'stale_account_repair_criteria'):
        if PRED in server:
            error |= check_predicate(server[PRED], reason='server.json:'+PRED)
    return error

def main(args):
    opts, args = getopt.gnu_getopt(args, 'uv', ['profile'])

    global verbose
    report_unreferenced_art_files = False
    report_unreferenced_art_assets = True
    do_profile = False

    for key, val in opts:
        if key == '-u':
            report_unreferenced_art_files = False
            report_unreferenced_art_assets = False
        elif key == '-v': verbose = True
        elif key == '--profile': do_profile = True

    start_time = time.time()

    error = 0

    # invoke as ./verify.py gamedata.json ai_bases_compiled.json ai_attacks_compiled.json

    # ai_bases and ai_attacks are included separately because it is not transmitted to the game client,
    # but we still want to verify them in context with the rest of gamedata.

    global gamedata
    gamedata = SpinJSON.load(open(args[0]))
    gamedata['ai_bases'] = SpinJSON.load(open(args[1]))
    gamedata['ai_attacks'] = SpinJSON.load(open(args[2]))
    gamedata['quarries'] = SpinJSON.load(open(args[3]))
    gamedata['hives'] = SpinJSON.load(open(args[4]))
    gamedata['raids'] = SpinJSON.load(open(args[5]))
    gamedata['loot_tables'] = SpinJSON.load(open(args[6]))
    gamedata['promo_codes'] = SpinJSON.load(open(args[7]))
    gamedata['server'] = SpinJSON.load(open(args[8]))
    gamedata['loading_screens'] = SpinJSON.load(open(args[9]))

    global MAX_STORAGE
    MAX_STORAGE = dict((resname, GameDataUtil.calc_max_storage_for_resource(gamedata, resname)) for resname in gamedata['resources'])

    for name, data in gamedata['dialogs'].iteritems():
        error |= check_dialog('dialog:'+name, data)

    for default_climate in (gamedata['default_climate'], gamedata.get('default_player_home_climate', gamedata['default_climate'])):
        if default_climate not in gamedata['climates']:
            error |= 1; print 'bad default climate %s' % default_climate

    for name, data in gamedata['climates'].iteritems():
        error |= check_climate(name, data)

    if 'titles' in gamedata:
        error |= check_titles(gamedata)

    for s in ('buildings', 'units'):
        for name, data in gamedata[s].iteritems():
            error |= check_mandatory_fields(s+':'+name, data, s)
            e, maxlevel = check_levels(s+':'+name, data)
            error |= e
            error |= check_object_spells(s+':'+name, data, maxlevel)

    for name, data in gamedata['inert'].iteritems():
        error |= check_inert('inert:'+name, data)

    for name, data in gamedata['tech'].iteritems():
        e, maxlevel = check_levels('tech:'+name, data)
        error |= e
        error |= check_tech('tech:'+name, name, data, maxlevel)

    for name, data in gamedata['enhancements'].iteritems():
        e, maxlevel = check_levels('enhancement:'+name, data)
        error |= e
        error |= check_enhancement('enhancement:'+name, name, data, maxlevel)

    for name, data in gamedata['auras'].iteritems():
        e, maxlevel = check_levels('aura:'+name, data)
        error |= e
        error |= check_aura('aura:'+name, data, maxlevel)

    for name, data in gamedata['items'].iteritems():
        error |= check_item('item:'+name, data)

    for name, data in gamedata['item_sets'].iteritems():
        error |= check_item_set('item_set:'+name, data)

    for name, entry in gamedata['strings']['manufacture_categories'].iteritems():
        error |= check_manufacture_category('strings:manufacture_categories:'+name, entry)
    for parent_name, parent_cat in gamedata['strings']['research_categories'].iteritems():
        for entry in parent_cat:
            error |= check_research_category('strings:research_categories:'+parent_name+':'+entry['name'], entry)
    if 'categories' in gamedata['crafting']:
        for name, data in gamedata['crafting']['categories'].iteritems():
            error |= check_crafting_category('crafting:categories:'+name, data)
    if 'recipes' in gamedata['crafting']:
        for name, data in gamedata['crafting']['recipes'].iteritems():
            error |= check_crafting_recipe('crafting:recipes:'+name, data)

    for name, data in gamedata['spells'].iteritems():
        error |= check_spell('spell:'+name, data)

    error |= check_leaderboard(gamedata['strings']['leaderboard'])

    for name, data in gamedata['regions'].iteritems():
        error |= check_region(name, data)
    for name, data in gamedata['continents'].iteritems():
        error |= check_continent(name, data)

    error |= check_cond_or_literal(gamedata['global_chat_channel_assignment'], reason = 'global_chat_channel_assignment')
    if type(gamedata['strings']['footer_linkbar_content']) is list:
        error |= check_cond_chain(gamedata['strings']['footer_linkbar_content'], reason = 'strings.footer_linkbar_content')
    error |= check_cond_or_literal(gamedata['continent_assignment'], reason = 'continent_assignment')

    # check some cond chains in the store
    for checkable in ('payments_api', 'buy_gamebucks_sku_kind', 'buy_gamebucks_sku_currency', 'ui_buy_gamebucks_warning', 'buy_gamebucks_dialog_look'):
        if checkable in gamedata['store'] and type(gamedata['store'][checkable]) is list:
            error |= check_cond_chain(gamedata['store'][checkable], reason = 'store.'+checkable)

    for name, data in gamedata['strings']['idle_buildings'].iteritems():
        if data.get('icon',None):
            error |= require_art_asset(data['icon'], 'strings:idle_buildings:'+name+':icon')

    if type(gamedata['continent_assignment']) is list:
        continent_list = [val for pred, val in gamedata['continent_assignment']]
    else:
        continent_list = [gamedata['continent_assignment']]
    for val in continent_list:
        if val not in gamedata['continents']:
            error |= 1; print 'continent_assignment value %s is not a valid continent_id' % val

    for name, data in gamedata['resources'].iteritems():
        error |= check_resource(name, data)

    error |= check_ai_bases_and_attacks(gamedata['ai_bases'], gamedata['ai_attacks'])

    for strid, data in gamedata['quarries']['templates'].iteritems():
        error |= check_quarry('quarry:'+strid, data)
    error |= check_hives_and_raids('hive', gamedata['hives'])
    error |= check_hives_and_raids('raid', gamedata['raids'])

    error |= check_turf_reward(gamedata['quarries_client']['alliance_turf'].get('reward',{"auras":[]}))

    if gamedata['territory'].get('enable_quarry_guards', True) and not gamedata.get('enable_defending_units',1):
        error |= 1; print 'territory.enable_quarry_guards should be off if global enable_defending_units setting is off'

    if str(gamedata['territory']['default_quarry_landlord_id']) not in gamedata['ai_bases']['bases']:
        error |= 1; print 'territory.default_quarry_landlord_id %d is not a valid AI base' % gamedata['territory']['default_quarry_landlord_id']

    error |= check_quests(gamedata['quests'])
    for name, data in gamedata['achievement_categories'].iteritems():
        error |= check_achievement_category(name, data)
    error |= check_achievements(gamedata['achievements'])
    error |= check_events(gamedata['events'])
    error |= check_event_schedule(gamedata['event_schedule'])

    # check player_xp settings
    # check that all buildings mentioned in player_xp.buildings actually exist
    for building_name in gamedata['player_xp']['buildings']:
        if building_name != 'level_1' and building_name not in gamedata['buildings']:
            error |= 1; print 'player_xp.buildings entry "%s" refers to invalid building' % building_name

    # check that all existing buildings give XP
    # note: exclude legacy game titles from this check because many of them skipped some buildings in player_xp.buildings and it's too late to fix!
    # also skip FS since it doesn't use this table
    if gamedata['game_id'] not in ('mf','bfm','mf2','dv','fs'):
        for building_name, building_data in gamedata['buildings'].iteritems():
            if not building_data.get('developer_only',False) and (building_name not in gamedata['player_xp']['buildings']):
                error |= 1; print 'player_xp.buildings is missing an entry for building "%s"' % building_name

    if 'level_up_reward' in gamedata['player_xp']:
        for entry in gamedata['player_xp']['level_up_reward']:
            if entry:
                error |= check_consequent(entry, reason = 'level_up_reward', context = 'level_up')

    # check that max_pvp_level_gap arrays are long enough
    for kind, arr in gamedata['max_pvp_level_gap'].iteritems():
        max_player_level = len(gamedata['player_xp']['level_xp'])
        if type(arr) is list and len(arr) < max_player_level:
            error |= 1; print 'max_pvp_level_gap array needs to be at least as long as the max player level (%d)' % max_player_level

    # make sure hard-coded art assets are present
    for art_asset in (
        # main.js
        'inventory_repair_item_green',
        'success_playful_22',
        'request_unit_donation_sound',
        'background_music',
        'conquer_sound',
        'action_button_134px',
        'error_sound',
        'building_context_1buttons_bg',
        'action_button_resizable',
        'menu_button_resizable',
        'xp_gain_sound',
        'harvest_sound',
        'minor_level_up_sound',
        'splash_victory','splash_defeat',
        'harvester_glow',
        'low_power_icon',
        'stun_icon',
        'equip_icon',
        'repair_wrench_green', 'repair_wrench_gray', 'repair_wrench_yellow',
        'repair_skull',
        'harvester_stop_icon',
        'TEMP_mapcell',
        # Consequents.js
        'conquer_sound',
        # RegionMap.js
        'region_tiles',
        'inventory_padlock',
        'trophy_15x15',
        'map_bubble',
        'map_flame',
        'loading_spinner',
        # SPFX.js
        'arrow_n', 'arrow_ne', 'arrow_nw', 'arrow_s', 'arrow_se', 'arrow_sw', 'arrow_w',
        'fx/glows',
        # SPUI.js
        'tooltip_bg',
        'mouseover_button_sound',
        'friend_frame',
        'spell_icon_frame',
        'spell_icon_glow_inner',
        # SPVideoWidget.js
        'dialog_video_widget',
        'close_button'
        ):
        error |= require_art_asset(art_asset, 'hard-coded')

    for cat in gamedata['strings']['damage_vs_categories']:
        error |= require_art_asset('damage_vs_'+cat[0], 'damage_vs_'+cat[0])

    for name in gamedata['art']:
        if name.startswith('alicon_'):
            error |= require_art_asset(name, 'alliance-icon')

    for kind, checker in (('daily_tips', check_daily_tip),
                          ('daily_messages', check_daily_message),
                          ('daily_banners', check_daily_banner)):
        names = set()
        for item in gamedata[kind]:
            error |= checker(item)
            if item['name'] in names:
                error |= 1; print '%s:name "%s" is not unique. Ensure there is only one entry in %s with this name.' % (kind, item['name'], kind)
            else:
                names.add(item['name'])

    if type(gamedata['store']['free_speedup_time']) is list:
        error |= check_cond_chain(gamedata['store']['free_speedup_time'], reason = 'store:free_speedup_time')

    for ASSET in ('gamebucks_pile_asset', 'gamebucks_inventory_icon'):
        error |= require_art_asset(gamedata['store'][ASSET], 'store:'+ASSET)

    for sku in gamedata['store']['catalog']:
        error |= check_store_sku(sku['name'], sku)

    for name, data in gamedata['tutorial'].iteritems():
        if 'ui_description' in data and type(data['ui_description']) is list:
            error |= check_cond_chain(data['ui_description'], reason = 'tutorial:'+name+':ui_description')
        if 'asset' in data:
            error |= require_art_asset(data['asset'], 'tutorial:'+name+':asset')

    for name, data in gamedata['abtests'].iteritems():
        error |= check_abtest(name, data)

    for name, data in gamedata['loot_tables'].iteritems():
        error |= check_loot_table(data['loot'], reason = 'loot_tables:'+name)
        if 'on_purchase' in data:
            error |= check_consequent(data['on_purchase'], reason = 'loot_tables:'+name+':on_purchase')
        for COND in 'ui_warning', 'metrics_description':
            if COND in data and not isinstance(data[COND], basestring):
                error |= check_cond_chain(data[COND], reason = 'loot_tables:'+name+':'+COND)

    for name, loot in gamedata.get('lottery_slot_tables',{}).iteritems():
        error |= check_loot_table(loot, reason='lottery_slot_tables:'+name)

    for name, pred in gamedata['predicate_library'].iteritems():
        expect_player_history_keys = None
        # check unit unlock predicates
        if gamedata['game_id'] != 'mf' and ('_unlocked' in name):
            match = level_re.match(name)
            if match:
                thing = match.group('root')[:-len('_unlocked')]
                my_level = int(match.group('level'))
            else:
                thing = name[:-len('_unlocked')]
                my_level = -1

            if thing in gamedata['units']:
                expect_player_history_keys = set([thing+'_blueprint_unlocked'])

                # special case to support stinger_blueprint_unlocked in TR
                if thing.endswith('stinger_gunner'):
                    expect_player_history_keys.add(thing[:-len('stinger_gunner')] + 'stinger_blueprint_unlocked')
            else:
                expect_player_history_keys = set([thing+'_blueprint_unlocked'])
                if my_level >= 0: # allow any item of equal or lesser level
                    for level in xrange(my_level, my_level+1):
                        expect_player_history_keys.add(thing+'_blueprint_unlocked'+('_L%d' % level))

        error |= check_predicate(pred, reason='predicate_library:'+name, expect_player_history_keys = expect_player_history_keys)

    for name, cons in gamedata['consequent_library'].iteritems():
        error |= check_consequent(cons, reason='consequent_library:'+name)

    matchmaking = gamedata['matchmaking']
    for name in ('ladder_point_decay_if',):
        if name in matchmaking:
            error |= check_predicate(matchmaking[name], reason='matchmaking:'+name)
    for name in ('ladder_match_switch_cost','ladder_match_history_exclude','ladder_match_min_trophies'):
        if name in matchmaking and (type(matchmaking[name]) is list):
            error |= check_cond_chain(matchmaking[name], reason='matchmaking:'+name)

    if 'ladder_loot_bonus' in matchmaking or 'ladder_loot_malus' in matchmaking:
        error |= 1; print 'migrate ladder_loot_bonus/malus to ladder_loot_bonus_by_townhall_level'
    if 'ladder_loot_bonus_by_townhall_level' in matchmaking:
        table = matchmaking['ladder_loot_bonus_by_townhall_level']
        max_cc_level = len(gamedata['buildings'][gamedata['townhall']]['build_time'])
        if len(table) != max_cc_level:
            error |= 1; print 'ladder_loot_bonus_by_townhall_level length must equal max townhall level (%d)' % max_cc_level
        for row in table:
            if len(row) != max_cc_level:
                error |= 1; print 'ladder_loot_bonus_by_townhall_level row length must equal max townhall level (%d)' % max_cc_level

    for name in ('loot_attacker_gains', 'loot_defender_loses'):
        if type(gamedata[name]) is dict:
            for kind, table in gamedata[name].iteritems():
                if type(table) is list:
                    error |= check_cond_chain(table, reason=name+':'+kind)

    if 'battle_stars' in gamedata:
        error |= check_battle_stars(gamedata['battle_stars'])

    error |= check_starting_conditions(gamedata['starting_conditions'])

    for name in ('chat_welcome_if',):
        if name in gamedata:
            error |= check_predicate(gamedata[name], reason='gamedata:'+name)

    for name, fx in gamedata['client']['vfx'].iteritems():
        error |= check_visual_effect('client_vfx:'+name, fx)

    for name in ('enable_replay_recording', 'enable_replay_playback',):
        error |= check_predicate(gamedata['client'][name], reason = 'client:'+name)

    error |= check_server(gamedata['server'])
    error |= check_promo_codes(gamedata['promo_codes'])

    for name, data in gamedata['adnetworks'].iteritems():
        error |= check_adnetwork(name, data)

    error |= check_loading_screens(gamedata['loading_screens'])

    # this must come last, because it depends on required_art_assets being filled out by previous code
    error |= check_art(gamedata['art'],
                       report_unreferenced_art_files = report_unreferenced_art_files,
                       report_unreferenced_art_assets = report_unreferenced_art_assets)

    if do_profile:
        end_time = time.time()
        print 'VERIFY: %.1f ms' % (1000.0*(end_time-start_time))

    return error

# by default, use stdin for input
if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:
        print 'gamedata error:', traceback.format_exc(e)
        sys.exit(1)
