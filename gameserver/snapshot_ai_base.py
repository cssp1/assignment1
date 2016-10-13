#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# convert playerdb/xxxx.txt saved game file into the format for AI bases

# use old JSON library for better syntax error messages
try: import simplejson as json
except: import json
import sys
import SpinConfig
import SpinJSON
import getopt
import AtomicFileWrite

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

def pretty_print_array(f, name, out, final):
    f.write('\t"%s": [\n' % name)
    for i in range(len(out)):
        props = out[i]
        f.write('\t\t' + json.dumps(props))
        if i != (len(out)-1):
            f.write(',\n')
    f.write('\n\t]')
    if not final:
        f.write(',')
    f.write('\n')

# fields that should be copied verbatim from GameObject state
OBJECT_FIELDS = ['equipment','orders','patrol','pack_id','behaviors']

# convert playerdb base to AI base
def from_playerdb(player, output, force_unit_level):
    out = {}

    out['buildings'] = []
    out['units'] = []

    if 'base_climate' in player: out['base_climate'] = player['base_climate']
    if 'deployment_buffer' in player: out['deployment_buffer'] = player['deployment_buffer']
    if 'unit_equipment' in player: out['unit_equipment'] = player['unit_equipment']

    if output == 'ai_base':
        out['tech'] = player.get('tech', {})

        # handle a special case in WSE where some players have anti_rover_mines tech even though it was later renamed to anti_tracker_mines
        if 'anti_tracker_mines' in out['tech'] and 'anti_rover_mines' in out['tech']:
            del out['tech']['anti_rover_mines']

    if 1: # output == 'quarry':
        out['inert'] = []

    for obj in player['my_base']:
        specname = obj['spec']
        props = {'spec': specname, 'xy': obj['xy']}
        props['force_level'] = obj.get('level',1)
        for field in OBJECT_FIELDS:
            if field in obj: props[field] = obj[field]
        if specname in gamedata['buildings']:
            spec = gamedata['buildings'][specname]
            if output == 'quarry':
                if specname.endswith('_harvester'):
                    props['spec'] = '%RESOURCE_harvester'
                elif specname not in ('barrier','quarry_energy_plant') and \
                   spec.get('history_category',None) != 'turrets':
                    print 'skipping', specname
                    continue
            out['buildings'].append(props)
        elif specname in gamedata['units']:
            if force_unit_level > 0:
                props['force_level'] = force_unit_level
            props['force_level'] = obj.get('level',1)
            if obj.get('squad_id',0) != 0: continue # do not include units that belong to squads other than base defenders
            out['units'].append(props)
        elif specname in gamedata['inert']:
            if specname in ('iron_deposit','armyguy_dead','droid_debris'): continue # don't copy deposits
            spec = gamedata['inert'][specname]
            if output == 'quarry' and spec.get('base_type','').startswith('quarry'):
                specname = specname.replace('iron', '%RESOURCE').replace('water', '%RESOURCE')
            out['inert'].append({'spec':specname, 'xy':obj['xy']})
        else:
            pass

    def sortkey(x):
        if x['spec'] == 'barrier': return 0
        elif x['spec'].endswith('_harvester'): return -3
        else: return -1

    out['buildings'].sort(key = sortkey)

    for OBJ_FIELD in ('tech','unit_equipment'):
        if OBJ_FIELD in out:
            print '\t"'+OBJ_FIELD+'": ', json.dumps(out[OBJ_FIELD], indent=1), ','

    if len(out['inert']) > 0:
        pretty_print_array(sys.stdout, 'scenery', out['inert'], False)

    pretty_print_array(sys.stdout, 'buildings', out['buildings'], False)
    pretty_print_array(sys.stdout, 'units', out['units'], True)

    #print json.dumps(out, indent=None, sort_keys = True)

# convert AI base to player base (overwriting contents of the playerdb file)
def to_playerdb(player_filename, player, base_id):
    gamedata['ai_bases'] = SpinJSON.load(open(SpinConfig.gamedata_component_filename("ai_bases_compiled.json")))
    base = gamedata['ai_bases']['bases'][str(base_id)]
    my_base = []
    townhall_level = -1
    for building in base['buildings']:
        if building['spec'] == gamedata['townhall']:
            townhall_level = building.get('level',1)
        props = {'spec':building['spec'],
                 'xy':building['xy'],
                 'level':building.get('level',1)}
        for field in OBJECT_FIELDS:
            if field in building:
                props[field] = building[field]
        my_base.append(props)
    for unit in base['units']:
        props = {'spec':unit['spec'], 'level':unit.get('level',1), 'xy': unit['xy']}
        for field in OBJECT_FIELDS:
            if field in unit:
                props[field] = unit[field]
        my_base.append(props)
    for scenery in base.get('scenery',[]):
        my_base.append({'spec':scenery['spec'], 'xy': scenery['xy']})

    player['unit_repair_queue'] = []
    player['my_base'] = my_base
    player['tech'] = base['tech']

    if townhall_level > 0:
        player['history'][gamedata['townhall']+'_level'] = townhall_level

    if 'base_climate' in base: player['base_climate'] = base['base_climate']
    if 'deployment_buffer' in base: player['deployment_buffer'] = base['deployment_buffer']

    atom = AtomicFileWrite.AtomicFileWrite(player_filename, 'w')
    SpinJSON.dump(player, atom.fd, pretty = True)
    atom.complete(fsync = False)
    print 'wrote contents of AI base %d to %s!' % (base_id, player_filename)

if __name__ == "__main__":
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['quarry', 'force-unit-level=', 'from-gamedata='])

    if len(args) < 1:
        print 'usage: %s playerdb/xxxx_mftest.txt' % sys.argv[0]
        print 'Converts a player base into the "units"/"buildings"/"tech"/"scenery" arrays that go into ai_bases_*.json, quarries.json, and hives.json'
        print '       --quarry                  output a quarry rather than an AI base or hive'
        print '       --force-unit-level N      force all mobile units to level N'
        print '       --from-gamedata BASE_ID   read BASE_ID from gamedata and output that base into the playerdb file'
        sys.exit(1)

    output = 'ai_base'
    base_id = -1
    force_unit_level = -1

    for key, val in opts:
        if key == '--quarry':
            output = 'quarry'
        elif key == '--force-unit-level':
            force_unit_level = int(val)
        elif key == '--from-gamedata':
            output = 'playerdb'
            base_id = int(val)

    player_filename = args[0]
    player = json.load(open(player_filename))

    if output == 'playerdb':
        to_playerdb(player_filename, player, base_id)
    else:
        from_playerdb(player, output, force_unit_level)
    sys.exit(0)
