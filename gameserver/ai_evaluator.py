#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# obsolete AI base analytics tool

import SpinJSON
import SpinConfig
import sys, os, glob, re, gzip, traceback

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
gamedata['ai_bases'] = SpinConfig.load(SpinConfig.gamedata_component_filename("ai_bases_compiled.json"))

ai_ids = sorted(map(int, gamedata['ai_bases']['bases'].keys()))
ai_id_set = set(ai_ids)

def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty

def check_bad_units():
    for id in ai_ids:
        base = gamedata['ai_bases']['bases'][str(id)]
        level = base['resources']['player_level']

        if level < 15 and base.get('deployment_buffer',1) != 0:
            print id, base['ui_name'], 'L', level, 'has a deployment buffer'

        if base['ui_name'] in ('Kirat','Vell Jomil'): continue

        bad_units = []
        for unit in base['units']:
            spec = gamedata['units'][unit['spec']]
            if level < 5:
                if spec.get('flying',0) or spec['name'] == 'blaster_droid' or (level < 3 and spec['name'] == 'muscle_box'):
                    bad_units.append(unit)
        for obj in base['buildings']:
            spec = gamedata['buildings'][obj['spec']]
            if level < 5:
                if spec.get('history_category',0) == 'turrets':
                    bad_units.append(obj)

        if bad_units:
            print id, base['ui_name'], [unit['spec'] for unit in bad_units]

def check_cost(individual):
    import csv

    log_dir = SpinConfig.config.get('log_dir', 'logs')
    name_pattern = re.compile('.*-([0-9]+)-vs-([0-9]+)\.')
    g_totals = {}
    columns = ['base_id', 'ai_name', 'ai_level', 'human_attacker_level', 'resources_gained', 'resources_lost', 'units_killed', 'units_lost',
               'N', 'outcome_defeat', 'outcome_victory']

    if individual:
        writer = csv.DictWriter(open(individual,'w'), columns, dialect='excel')
        writer.writerow(dict((fn,fn) for fn in columns))

    battle_dir_list = sorted(glob.glob(os.path.join(log_dir, '*-battles')))

    for i in xrange(len(battle_dir_list)):
        battle_dir = battle_dir_list[i]
        sys.stderr.write('reading from %s... (%d/%d)\n' % (battle_dir, i+1, len(battle_dir_list)))

        for battle_file in glob.glob(os.path.join(battle_dir, '*.json.gz')):
            match = name_pattern.search(battle_file)
            if not match: continue
            # attacker_id = int(match.group(1))
            defender_id = int(match.group(2))
            if defender_id not in ai_id_set: continue

            # note: all fields are from the perspective of the human player making the attack
            if defender_id not in g_totals:
                base = gamedata['ai_bases']['bases'][str(defender_id)]
                g_totals[defender_id] = {'base_id': defender_id,
                                         'ai_name': base['ui_name'], 'ai_level': base['resources']['player_level'],
                                         'outcome_defeat':0, 'outcome_victory': 0, 'N':0,
                                         'resources_lost':0, 'resources_gained':0, 'units_lost':0, 'units_killed':0 }

            totals = g_totals[defender_id]

            data = {'base_id': defender_id, 'ai_name': base['ui_name'], 'ai_level': base['resources']['player_level'],
                    'outcome_defeat':0, 'outcome_victory': 0, 'N': 1}

            try:
                fd = gzip.GzipFile(battle_file)
                for line in fd.readlines():
                    if ('unit_destroyed' not in line) and ('battle_start' not in line) and ('battle_end' not in line): continue
                    event = SpinJSON.loads(line)
                    if event['event_name'] == '3820_battle_start':
                        data['human_attacker_level'] = event['attacker_level']
                    elif event['event_name'] == '3830_battle_end':
                        data['resources_gained'] = sum(event.get('gain_'+rsrc,0) for rsrc in gamedata['resources'])
                        data['units_lost'] = event.get('units_lost',0)
                        data['units_killed'] = event.get('units_killed',0)
                        data['outcome_'+event['battle_outcome']] += 1
                    elif event['event_name'] == '3930_unit_destroyed' and event['user_id'] != defender_id:
                        spec_name = event['unit_type']
                        level = event['level']
                        spec = gamedata['units'][spec_name]
                        cost = sum(get_leveled_quantity(spec['build_cost_'+rsrc], level) for rsrc in gamedata['resources'])
                        data['resources_lost'] = data.get('resources_lost',0) + cost

                if individual:
                    writer.writerow(data)

                for field in ('resources_gained', 'resources_lost', 'units_killed', 'units_lost', 'outcome_defeat', 'outcome_victory', 'N'):
                    totals[field] += data.get(field,0)

            except KeyboardInterrupt:
                return
            except:
                sys.stderr.write('error reading '+battle_file+': '+traceback.format_exc())

    if True: # not individual:
        writer = csv.DictWriter(sys.stdout, columns, dialect='excel')
        writer.writerow(dict((fn,fn) for fn in columns))
        for ai_id in ai_ids:
            if ai_id in g_totals:
                writer.writerow(g_totals[ai_id])

if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'bad-units':
        check_bad_units()
    elif mode == 'cost':
        check_cost(sys.argv[2])
