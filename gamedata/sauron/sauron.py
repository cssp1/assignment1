#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# 'Sauron', for displaying important data regarding Live Ops, Game Design, Testing, and more in a human readable format

import SpinJSON
import SpinConfig
import sys, getopt, os, time, datetime, math

# XXX need to add all games
GAME_IDS = ['bfm', 'tr'] #'sg', 'mf', 'mf2', 'gg', 'dv']
GAME_URLS = {"bfm": "https://apps.facebook.com/tablettransform/?event_time_override=", \
             "tr": "https://apps.facebook.com/thudrunner/?event_time_override="}
GAME_UI_NAMES = {"bfm": "Battlefront Mars", "tr": "Thunder Run"}
gamedata = None
basedata = None
hivedata = None
lootdata = None
time_now = 0


# calculate the total harmful DPS, total HP, and the total unit space
def calculate_unit_stats(units,tech):
    total_dps = 0
    total_hp = 0
    total_space = 0
    for unit in units:
        spec = gamedata['units'][unit['spec']]

        if 'force_level' in unit:
            level = unit['force_level']
        elif isinstance(tech, dict):
            #if force_level does not exist, but tech contains a spec['name']_production value, use that
            production_type = str(spec['name'] + '_production')
            level = tech[production_type] if production_type in tech else 1
        else:
            level = 1

        spell = gamedata['spells'][spec['spells'][0]]
        if spell['activation'] != 'auto' or spell.get('help', 0):
            dps = 0
        else:
            damage = spell.get('damage', 0)
            if isinstance(damage, list): dps = damage[level-1]
            else: dps = damage

        if spell.get('targets_self',0):
            # count suicide attacks as half as much DPS
            dps *= 0.5
        elif 'splash_range' in spell:
            # count splash-capable attacks as twice as much DPS
            dps *= 2
        total_dps += dps
        total_hp += spec['max_hp'][level-1]
        total_space += spec['consumes_space']

    return total_dps, total_hp, total_space

# calculate how many turrets there are, the total harmful DPS, and total HP
def calculate_turret_stats(buildings):
    total_turrets = 0
    total_dps = 0
    total_hp = 0
    for building in buildings:
        spec = gamedata['buildings'][building['spec']]
        if 'ui_damage_vs' in spec and 'spells' in spec:
            total_turrets += 1

            spell = gamedata['spells'][spec['spells'][0]]
            if spell['activation'] != 'auto' or spell.get('help', 0):
                continue

            level = building['force_level'] if 'force_level' in building else 1
            dps = spell['damage'][level-1] if 'damage' in spell else 0

            if spell.get('targets_self',0):
                # count suicide attacks as half as much DPS
                dps *= 0.5
            elif 'splash_range' in spell:
                # count splash-capable attacks as twice as much DPS
                dps *= 2
            total_dps += dps
            total_hp += spec['max_hp'][level-1]
        else:
            continue

    return total_turrets, total_dps, total_hp

# parse the units of an ai_attack level into the same form as ai_base levels
def parse_defense_units(directions):
    units = []
    for direction in directions:
        for spec in direction:
            val = direction[spec]
            if spec not in gamedata['units']:
                continue
            level = 1
            qty = 0
            if isinstance(val, dict):
                level = val['force_level']
                qty = val['qty']
            else:
                qty = val
            unit = {"spec": spec, "force_level": level}
            for x in range(0, qty): units.append(unit)
    return units

# parse out all useful information out of a raw json base
def prepare_base_data(base):
    base_data = {}
    base_data['level_order'] = base['resources']['player_level'] if 'resources' in base else 9999
    base_data['type'] = 'DEFENSE' if 'kind' in base and base['kind'] == 'ai_attack' else 'AI_BASE'
    tech = base.get('tech')
    units = base['units']
    if base_data['type'] == 'DEFENSE':
        units = parse_defense_units(units)
    base_data['num_units'] = len(units)
    unit_stats = calculate_unit_stats(units,tech)
    base_data['unit_dps'] = unit_stats[0]
    base_data['unit_hp'] = unit_stats[1]
    base_data['unit_space'] = unit_stats[2]
    buildings = base.get('buildings', [])
    turret_stats = calculate_turret_stats(buildings)
    base_data['num_turrets'] = turret_stats[0]
    base_data['turret_dps'] = turret_stats[1]
    base_data['turret_hp'] = turret_stats[2]
    scenery = base.get('scenery', [])
    base_data['num_sprites'] = len(buildings) + len(units) + len(scenery)
    base_data['loot'] = get_base_loot(base)
    base_data['tokens'] = get_base_token_drop_amount(base_data['loot'])
    return base_data

# create and initialize keys for all event stats
def init_event_stats():
    stats = {}
    stats['total_base_levels'] = 0
    stats['total_base_units'] = 0
    stats['total_base_dps'] = 0
    stats['total_base_hp'] = 0
    stats['total_base_space'] = 0
    stats['total_turrets'] = 0
    stats['total_turret_dps'] = 0
    stats['total_turret_hp'] = 0
    stats['total_sprites'] = 0
    stats['total_base_tokens'] = 0
    stats['total_defense_levels'] = 0
    stats['total_defense_units'] = 0
    stats['total_defense_dps'] = 0
    stats['total_defense_hp'] = 0
    stats['total_defense_space'] = 0
    stats['total_defense_tokens'] = 0
    return stats

def collect_event_data(game_id):
    events = {}
    # search through events on the schedule
    for e in gamedata['event_schedule']:
        #if e['end_time'] < time_now:
        #    continue

        # make sure this is a live ops event and not a PvP tourney
        if e['name'][:5] != 'event':
            continue

        split_name = e['name'].split('_')
        name = split_name[1]
        identifier = split_name[-1]

        if name not in events:
            events[name] = {}
            events[name]['type'] = 'Event'
            events[name]['bases'] = {}
            events[name]['hives'] = {}
            events[name]['stats'] = init_event_stats()
        event = events[name]

        if identifier == name:
            event['start_time'] = e['start_time']
            event['end_time'] = e['end_time']
        elif identifier == 'preannounce':
            event['preannounce_start'] = e['start_time']
            event['preannounce_end'] = e['end_time']
        elif identifier == 'map':
            event_data = gamedata['events'][e['name']]
            event['type'] = 'ONP' if 'token_item' in event_data else 'IMM'
            event['ui_title'] = event_data['ui_title']

        # figure out the base ids associated with this event
        if name != 'tutorial':
            chain = gamedata['events'][e['name']].get('chain', [])
            # XXX seems very specific and fragile, investigate other ways to get base_ids associated with an event
            for link in chain:
                fight_button_action = link[1]['fight_button_action']
                if 'call_attack' in fight_button_action:
                    event['bases'][fight_button_action['call_attack']] = {}
                elif 'visit_base' in fight_button_action:
                    event['bases'][fight_button_action['visit_base']] = {}

    bases_touched = []
    for key, event in events.iteritems():
        if event['type'] != 'Event':
            bases_touched += collect_event_base_data(event)

    collect_tutorial_and_imm_data(events, bases_touched)
    collect_hive_data(events)

    # count the ONP in each event
    for key in events:
        event = events[key]
        event['tokens'] = get_event_token_drop_amount(event['bases']) if event['type'] == 'ONP' else 0

    return events

# collect all the relevant base data for an event
def collect_event_base_data(event):
    bases_touched = []
    for base_id in event['bases']:
        has_progress = True
        if str(base_id) in basedata['bases']:
            base = basedata['bases'][str(base_id)]
            event['bases'][base_id] = prepare_base_data(base)
            collect_event_totals(event['stats'], event['bases'][base_id])
            bases_touched.append(base_id)
    return bases_touched

# increment event stats with data from this base
def collect_event_totals(stats, base):
    if base['type'] == 'AI_BASE':
        stats['total_base_levels'] += 1
        stats['total_base_units'] += base['num_units']
        stats['total_base_dps'] += base['unit_dps']
        stats['total_base_hp'] += base['unit_hp']
        stats['total_base_space'] += base['unit_space']
        stats['total_turrets'] += base['num_turrets']
        stats['total_turret_dps'] += base['turret_dps']
        stats['total_turret_hp'] += base['turret_hp']
        stats['total_sprites'] += base['num_sprites']
        stats['total_base_tokens'] += base['tokens']
    elif base['type'] == 'DEFENSE':
        stats['total_defense_levels'] += 1
        stats['total_defense_units'] += base['num_units']
        stats['total_defense_dps'] += base['unit_dps']
        stats['total_defense_hp'] += base['unit_hp']
        stats['total_defense_space'] += base['unit_space']
        stats['total_defense_tokens'] += base['tokens']

# parse all useful information out of a raw hive json
def prepare_hive_data(hive):
    hive_data = {}
    hive_data['num_units'] = len(hive['units'])
    tech = hive.get('tech')
    unit_stats = calculate_unit_stats(hive['units'],tech)
    hive_data['unit_dps'] = unit_stats[0]
    hive_data['unit_hp'] = unit_stats[1]
    hive_data['unit_space'] = unit_stats[2]
    buildings = hive.get('buildings', [])
    turret_stats = calculate_turret_stats(buildings)
    hive_data['num_turrets'] = turret_stats[0]
    hive_data['turret_dps'] = turret_stats[1]
    hive_data['turret_hp'] = turret_stats[2]
    scenery = hive.get('scenery', [])
    hive_data['num_sprites'] = len(buildings) + len(hive['units']) + len(scenery)
    hive_data['tokens'] = get_hive_token_drop_amount(hive)
    hive_data['num'] = hive['num']
    return hive_data

# build hive data into a more useful structure, organized by start_time
#   hives: { start_time: { template_name: {template_data} } }
def collect_hive_data(events):
    hives = {}
    for spawn in hivedata['spawn']:
        if 'active' in spawn and spawn['active'] == 0: # XXX should this pass if 'active' isn't present?
            continue
        if 'start_time' in spawn:
            if spawn['start_time'] not in hives:
                hives[spawn['start_time']] = {}
            hive = hivedata['templates'][spawn['template']]
            hive['num'] = spawn['num']
            hives[spawn['start_time']][spawn['template']] = prepare_hive_data(hive)
        elif 'spawn_times' in spawn:
            for time_range in spawn['spawn_times']:
                if time_range[0] not in hives:
                    hives[time_range[0]] = {}
                hive = hivedata['templates'][spawn['template']]
                hive['num'] = spawn['num']
                hives[time_range[0]][spawn['template']] = prepare_hive_data(hive)

    # based on start time, populate events with the appropriate hive data
    for key in events:
        event = events[key]
        if 'start_time' not in event:
            continue
        event['hives'] = hives.get(event['start_time'], {})

# XXX hacky implementation, needs to be cleaner
# returns False if the end_time of an ABSOLUTE_TIME predicate has passed (the event has already occured)
def check_time_predicate(pred):
    passes = True
    # if we have nesting, dig deeper with recursion
    if 'subpredicates' in pred:
        for sub in pred['subpredicates']:
            if not check_time_predicate(sub):
                passes = False
    elif pred['predicate'] == 'ABSOLUTE_TIME':
        passes = pred['range'][1] > time_now
    return passes

# XXX hacky implementation, needs to be cleaner
# returns the time range of the first ABSOLUTE_TIME predicate, depth first
def get_time_from_predicate(pred):
    # if we have nesting, dig deeper with recursion
    if 'subpredicates' in pred:
        for sub in pred['subpredicates']:
            return get_time_from_predicate(sub)
    elif pred['predicate'] == 'ABSOLUTE_TIME':
        return pred['range']

    return [time_now, time_now + 60*60*24*7]

# collects all the useful information any bases not a part of events on the event schedule
def collect_tutorial_and_imm_data(events, bases_touched=[]):
    for base_id in basedata['bases']:
        # make sure we haven't processed this base yet
        if int(base_id) in bases_touched:
            continue
        base = basedata['bases'][base_id]

        # must not be deactivated
        if 'activation' not in base or base['activation']['predicate'] == 'ALWAYS_FALSE':
            continue

        # must not have ended already
        if not check_time_predicate(base['activation']):
            continue
        if 'show_if' in base and not check_time_predicate(base['show_if']):
            continue

        # need analytics tag for indexing
        if 'analytics_tag' not in base:
            continue
        tag = base['analytics_tag']

        if tag not in events:
            event = {}
            event['start_time'] = get_time_from_predicate(base['show_if'])[0] if 'show_if' in base else time_now
            event['type'] = 'TUT' if tag.startswith('tutorial') else 'IMM'
            event['ui_title'] = base['ui_map_name'] if 'ui_map_name' in base else base['ui_name']
            event['bases'] = {}
            event['hives'] = {}
            event['stats'] = init_event_stats()
            events[tag] = event
        event = events[tag]
        base_data = prepare_base_data(base)
        event['bases'][int(base_id)] = base_data
        collect_event_totals(event['stats'], base_data)

# XXX kind of a messy way to get the loot, no good way to do it but this could be done cleaner
def get_base_loot(base):
    if 'completion' not in base:
        return []

    old_loot = []
    for cons in base['completion']['subconsequents']:
        if cons['consequent'] == 'GIVE_LOOT':
            old_loot += cons['loot']

    new_loot = []
    for l in old_loot:
        if 'multi' in l:
            # recursively parse through multi loot drops
            new_loot.append({"spec": "multi", "items": parse_multi_loot(l['multi']), "weight": 1})

        elif 'table' in l:
            table = lootdata[l['table']]

            # if the loot table is too big, just save the table name
            if len(table['loot']) > 6:
                new_loot.append({"spec": l['table'], "weight": 1})
                continue

            for drop in table['loot']:
                # can't be recursive here since JSON structure is slightly different
                stack = drop.get('stack', 1)
                weight = drop.get('weight', 1)
                if 'cond' in drop:
                    new_loot.append({"spec": l['table'], "weight": 1})
                    break
                if 'table' in drop:
                    new_loot.append({"spec": drop['table'], "stack": stack, "weight": weight})
                elif 'spec' in drop:
                    new_loot.append({"spec": drop['spec'], "stack": stack, "weight": weight})
                elif 'multi' in drop:
                    new_loot.append({"spec": "multi", "items": parse_multi_loot(drop['multi']), "weight": weight})
                else:
                    new_loot.append(drop)

        elif 'spec' in l:
            l['weight'] = 1
            new_loot.append(l)

    return new_loot

# parse through a multi loot json and convert it into a list of loot items
def parse_multi_loot(loot):
    multi_loot = []
    for l in loot:
        if 'multi' in l:
            multi_loot += parse_multi_loot(l['multi'])
        elif 'spec' in l:
            multi_loot.append({"spec": l['spec'], "stack": l.get('stack',1)})
        elif 'table' in l:
            multi_loot.append({"spec": l['table'], "stack": 1})
    return multi_loot

# XXX might need to dig deeper in case tokens get deeply packed into a loot table
def get_event_token_drop_amount(bases):
    tokens = 0
    for base_id in bases:
        base = bases[base_id]
        tokens += get_base_token_drop_amount(base['loot'])
    return tokens

# return the total number of tokens that base drops; takes parsed loot as a parameter
def get_base_token_drop_amount(loot):
    tokens = 0
    for l in loot:
        if 'spec' not in l:
            continue
        if l['spec'] == 'token':
            tokens += l['stack']
        elif l['spec'] == 'multi':
            for item in l['items']:
                if item['spec'] == 'token': tokens += item['stack']
    return tokens

# return the total number of tokens that hive drops; takes a parsed hive as a parameter
def get_hive_token_drop_amount(hive):
    loot = get_base_loot(hive)

    for l in loot:
        if 'spec' not in l:
            continue

        if l['spec'] == 'multi':
            for i in l['items']:
                if 'spec' not in i: continue
                if i['spec'] == 'token': return i['stack']
        elif l['spec'] == 'token': return l['stack']

    return 0

def estimate_cc_level_ai_base(base):
    # see documentation for explanation of CC level formula
    cc_level = (0.4*(base['unit_dps']+79024.0)/37291.0) + \
                (0.4*(base['unit_hp']+281460.0)/96136.0) + \
                (0.1*(base['turret_dps']+ 14235.0)/4718.0) + \
                (0.1*(base['turret_hp']+43256.0)/23091.0)

    return cc_level

def estimate_cc_level_defense(base):
    # see documentation for explanation of CC level formula
    cc_level = 0.5*(3.28e-5*base['unit_dps']+2.93) + \
                0.5*(1.64e-5*base['unit_hp']+3.19)

    return cc_level

def format_loot(base_loot):
    formatted_loot = []

    for loot in base_loot:
        if 'nothing' in loot:
            formatted_loot.append(('no drop', (loot['weight']*100)))
        elif loot['spec'] == 'multi':
            s = ' '
            for item in loot['items']:
                if item['stack'] > 1:
                    s += '%dx%s, ' % (item['stack'], item['spec'])
                else:
                    s += '%s, ' % item['spec']
            formatted_loot.append((s, (loot['weight']*100)))
        else:
            stack = loot.get('stack', 1)
            if stack > 1:
                s = '%dx%s' % (loot['stack'], loot['spec'])
                formatted_loot.append((s, (loot['weight']*100)))
            else:
                s = '%s' % loot['spec']
                formatted_loot.append((s, (loot['weight']*100)))

    return formatted_loot

def average_and_total_stats(stats):
    averaged_base_stats = {}
    averaged_defense_stats = {}
    total_stats = {}

    for key in stats:
        averaged_base_stats[key] = stats[key] / max(1,stats['total_base_levels'])
        averaged_defense_stats[key] = stats[key] / max(1,stats['total_defense_levels'])

    total_stats['total_units'] = stats['total_base_units'] + stats['total_defense_units']
    total_stats['total_dps'] = stats['total_base_dps'] + stats['total_defense_dps']
    total_stats['total_hp'] = stats['total_base_hp'] + stats['total_defense_hp']
    total_stats['total_space'] = stats['total_base_space'] + stats['total_defense_space']
    total_stats['total_turrets'] = stats['total_turrets']
    total_stats['total_turret_dps'] = stats['total_turret_dps']
    total_stats['total_turret_hp'] = stats['total_turret_hp']

    return averaged_base_stats, averaged_defense_stats, total_stats

def print_event_details_txt(game_id):
    print '======================================================================='
    print '%s EVENT DETAILS :' % game_id.upper()
    print '======================================================================='

    events = collect_event_data(game_id)
    for event_key in sorted(events, key=lambda x: (events[x]['type'], len(events[x]['bases']))):
        base_count = 1
        event = events[event_key]
        if 'ui_title' not in event:
            continue
        print '-----------------------------------------------------------------------'
        print '  %s %s: \"%s\" event_name: \"%s\"' % (game_id.upper(), event['type'], event['ui_title'], event_key)
        print '  %s' % (GAME_URLS[game_id] + str(event['start_time']))
        print '-----------------------------------------------------------------------'
        print '  %s Level(s) | ONP %06d | Hives %03d\n' % (len(event['bases']), event['tokens'], len(event['hives']))
        print 'PROGRESSION\n'
        for base_id in sorted(event['bases'], key=lambda x:event['bases'][x]['level_order']):
            base = event['bases'][base_id]
            level = '%02d' % base_count if base['level_order'] < 9999 else '??'
            print 'L%s %s: %04d ID |' % (level, base['type'], base_id),
            if event['type'] == 'ONP':
                print '%06d ONP |' % base['tokens'],
            print '%04d UNT, %07d DPS, %07d HLT, %06d SPC' % (base['num_units'], base['unit_dps'], base['unit_hp'], base['unit_space']),
            if base['type'] == 'AI_BASE':
                cc_level = estimate_cc_level_ai_base(base)
                print '| %.2f CCL' %  (cc_level),
                print '| %03d TUR, %07d DPS, %07d HLT' % (base['num_turrets'], base['turret_dps'], base['turret_hp']),
                print '| %04d SPT' %  (base['num_sprites']),
            elif base['type'] == 'DEFENSE':
                cc_level = estimate_cc_level_defense(base)
                print '| %.2f CCL' %  (cc_level),
            print ''
            base_count += 1

        # output totals/averages for the event
        stats = event['stats']
        averaged_base_stats, averaged_defense_stats, total_stats = average_and_total_stats(stats)
        print '\n-----------------------------------------------------------------------'
        print 'AVG AI_BASE:        ',
        if event['type'] == 'ONP':
            print '| %06d ONP' % (stats['total_base_tokens'] / max(1,stats['total_base_levels'])),
        print '| %04d UNT, %07d DPS, %07d HLT, %06d SPC' % (averaged_base_stats['total_base_units'], averaged_base_stats['total_base_dps'],\
                                                            averaged_base_stats['total_base_hp'] , averaged_base_stats['total_base_space']),
        print '| %03d TUR, %07d DPS, %07d HLT | %04d SPT' % (averaged_base_stats['total_turrets'], averaged_base_stats['total_turret_dps'], \
                                                             averaged_base_stats['total_turret_hp'], averaged_base_stats['total_sprites'])
        print 'AVG DEFENSE:        ',
        if event['type'] == 'ONP':
            print '| %06d ONP' % (stats['total_defense_tokens'] / max(1,stats['total_defense_levels'])),
        print '| %04d UNT, %07d DPS, %07d HLT, %06d SPC' % (averaged_defense_stats['total_defense_units'], averaged_defense_stats['total_defense_dps'], \
                                                          averaged_defense_stats['total_defense_hp'], averaged_defense_stats['total_defense_space'])
        print 'TTL PROGRES:        ',
        if event['type'] == 'ONP':
            print '| %06d ONP' % event['tokens'],
        print '| %04d UNT, %07d DPS, %07d HLT, %06d SPC' % (total_stats['total_units'], total_stats['total_dps'], \
                                                          total_stats['total_hp'], total_stats['total_space']),
        print '| %03d TUR, %07d DPS, %07d HLT' % (total_stats['total_turrets'], total_stats['total_turret_dps'], total_stats['total_turret_hp'])
        print '-----------------------------------------------------------------------'
        print ''

        # output loot drop data
        print 'LOOT STATS\n'
        base_count = 1
        for base_id in sorted(event['bases'], key=lambda x:event['bases'][x]['level_order']):
            base = event['bases'][base_id]
            formatted_loot = format_loot(base['loot'])
            level = '%02d' % base_count if base['level_order'] < 9999 else '??'
            print 'L%s:' % level,

            if len(formatted_loot) < 1:
                print '\tno drop | 100% WGT'
                base_count += 1
                continue

            for loot in formatted_loot:
                print '\t%s | %03d%% WGT' % loot

            base_count += 1
        print ''

        # output hive template stats
        if len(event['hives']):
            print 'HIVE STATS\n'
            for hive_key in sorted(event['hives']):
                hive = event['hives'][hive_key]
                cc_level = estimate_cc_level_ai_base(hive)
                print '%s | %05d ONP' % (hive_key, hive['tokens']),
                print '| %03d UNT, %06d DPS, %06d HLT' % (hive['num_units'], hive['unit_dps'], hive['unit_hp']),
                print '| %03d TUR, %06d DPS, %06d HLT | %.2f CCL | %03d SPT' % (hive['num_turrets'], hive['turret_dps'], \
                                                                     hive['turret_hp'], cc_level, hive['num_sprites'])

            print ''

def print_event_details_csv(game_id):
    events = collect_event_data(game_id)
    hives_touched = []

    for event_key in sorted(events, key=lambda x: (events[x]['type'], len(events[x]['bases']))):
        base_count = 1
        event = events[event_key]
        if 'ui_title' not in event:
            continue

        for base_id in sorted(event['bases'], key=lambda x:event['bases'][x]['level_order']):
            base = event['bases'][base_id]
            formatted_loot = format_loot(base['loot'])
            level = '%02d' % base_count if base['level_order'] < 9999 else '??'
            if base['type'] == 'AI_BASE':
                cc_level = estimate_cc_level_ai_base(base)
            elif base['type'] == 'DEFENSE':
                cc_level = estimate_cc_level_defense(base)

            # output stats in csv fashion
            print '%s-L%s, %s, %04d, %.2f,' % (event_key,level, base['type'], base_id, cc_level),
            print '%06d,' % base['tokens'],
            print '%04d, %07d, %07d, %06d,' % (base['num_units'], base['unit_dps'], base['unit_hp'], base['unit_space']),
            print '%03d, %07d, %07d,' % (base['num_turrets'], base['turret_dps'], base['turret_hp']),
            print '%04d,' %  (base['num_sprites']),

            # output loot drop data
            for loot in formatted_loot:
                print '(%s %03d%% WGT)' % loot,

            print ''
            base_count += 1

        # output hive template stats
        if len(event['hives']):
            for hive_key in sorted(event['hives']):
                hive = event['hives'][hive_key]
                if hive_key not in hives_touched:
                    hives_touched.append(hive_key)
                    cc_level = estimate_cc_level_ai_base(hive)
                    print '%s, HIVE, 0, %.2f, %05d,' % (hive_key, cc_level, hive['tokens']),
                    print '%03d, %06d, %06d,' % (hive['num_units'], hive['unit_dps'], hive['unit_hp']),
                    print '%03d, %06d, %06d, %03d,0,' % (hive['num_turrets'], hive['turret_dps'], hive['turret_hp'], hive['num_sprites']),
                    print ''

def main(args):
    global gamedata
    global basedata
    global hivedata
    global lootdata
    global time_now

    opts, args = getopt.gnu_getopt(args, 'cg:', [])

    game_id = 'ALL'
    output = 'txt'

    for key, val in opts:
        if key == '-g':
            game_id = val
        if key == '-c':
            output = 'csv'

    time_now = int(time.time())

    date_now = datetime.datetime.utcfromtimestamp(time_now)
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
    cur_week = SpinConfig.get_pvp_week(gamedata['matchmaking']['week_origin'], time_now)
    today5pm = SpinConfig.cal_to_unix(SpinConfig.unix_to_cal(time_now)) + 17*60*60
    if time_now < today5pm:
        cur_day = ((date_now.weekday() + 3) % 7 + 1)
    else:
        cur_day = ((date_now.weekday() + 4) % 7 + 1)

    if output == 'txt':
        print 'Sauron v0.01.015 | %s, %s %s (Week %s, Day %s) %s GMT:<br>' % (date_now.strftime('%A')[:3].upper(), date_now.strftime("%B")[:3].upper(), date_now.strftime('%d, %Y'), cur_week, cur_day, date_now.strftime('%H:%M:%S'))
        print '======================================================================='

        print '\n  TITLES :\n'
        print '    TR  - Thunder Run'
        print '    BFM - Battlefront Mars'
        print ''
        print '  ALL TITLES :\n'
        print '    TEST CALENDAR (Coming soon)'
        print '    EVENT CALENDAR (Coming soon)'
        print ''

        print '======================================================================='
        print '  LEGEND'
        print '=======================================================================\n'
        print '  EVENT DETAILS :\n'
        print '    ONP: Ops Needs Points event'
        print '    IMM: Immortal event'
        print '    TUT: Tutorial event'
        print '    ID:  AI base/attack id'
        print '    UNT: Number of AI units'
        print '    DPS: Total harmful damage per second of AI units/turrets'
        print '    HLT: Total max health of AI units/turrets'
        print '    SPC: Total unit space taken up by AI units'
        print '    TUR: Number of turrets'
        print '    SPT: Total sprite count of AI buildings, units, and scenery for gauging frame rates.'
        print '    CCL: Estimated difficulty in terms of CC level.'
        print ''

    if output == 'csv':
        print 'Level, Type, Base ID, Estimate CCL, ONP, Unit Count, Unit Health, Unit DPS, Unit Space, Turret Count, Turret Health, Turret DPS, Sprite Count, Loot'


    if game_id is 'ALL':
        for id in GAME_IDS:
            try:
                gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = id)))
                basedata = SpinJSON.load(open('./%s/built/%s_ai_bases_compiled.json' % (id, id)))
                hivedata = SpinJSON.load(open('./%s/built/%s_hives_compiled.json' % (id, id)))
                lootdata = SpinJSON.load(open('./%s/built/%s_loot_tables_compiled.json' % (id, id)))
            except IOError:
                print 'ERROR: Can\'t find compiled gamedata files for %s. Please run cd ../gameserver; ./make-gamedata.sh -u -g %s\n' % (id, id)
                return

        if output == 'txt':
            print_event_details_txt(id)
        elif output == 'csv':
            print_event_details_csv(id)
    else:
        if game_id not in GAME_IDS:
            print 'Invalid game id: %s' % game_id
            return

        try:
            gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
            basedata = SpinJSON.load(open('./%s/built/%s_ai_bases_compiled.json' % (game_id, game_id)))
            hivedata = SpinJSON.load(open('./%s/built/%s_hives_compiled.json' % (game_id, game_id)))
            lootdata = SpinJSON.load(open('./%s/built/%s_loot_tables_compiled.json' % (game_id, game_id)))
        except IOError:
                print 'ERROR: Can\'t find compiled gamedata files for %s. Please run cd ../gameserver; ./make-gamedata.sh -u -g %s\n' % (game_id, game_id)
                return

        if output == 'txt':
            print_event_details_txt(game_id)
        elif output == 'csv':
            print_event_details_csv(game_id)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
