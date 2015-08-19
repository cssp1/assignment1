#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinJSON
import SpinConfig
import AtomicFileWrite
import sys, getopt, random

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

if __name__ == '__main__':
    level_range = [1,1]
    secteam_chance = 1.0


    opts, args = getopt.gnu_getopt(sys.argv, '', ['level=', 'min-level=', 'max-level=', 'secteam-chance='])

    for key, val in opts:
        if key == '--level':
            level_range = [int(val),int(val)]
        elif key == '--min-level':
            level_range[0] = int(val)
        elif key == '--max-level':
            level_range[1] = int(val)
        elif key == '--secteam-chance':
            secteam_chance = float(val)

    for filename in args[1:]:
        base = SpinConfig.load(filename, stripped = True)

        TEAM_TYPES = {'supply_yard':'harvester',
                      'supply_depot':'storage',
                      'fuel_yard':'harvester',
                      'fuel_depot':'storage',
                      'generator':'generator',
                      'mg_tower':'turret',
                      'mortar_emplacement':'turret',
                      'tow_emplacement':'turret',
                      'turret_emplacement':'turret',

                      'tesla_coil':'turret',
                      'energy_plant':'energy_plant',
                      'water_storage':'storage','iron_storage':'storage',
                      'water_harvester':'harvester','iron_harvester':'harvester'
                      }

        for obj in base['buildings']:
            team_type = TEAM_TYPES.get(obj['spec'], None)
            if team_type:
                if 'equipment' not in obj: obj['equipment'] = {}
                if 'defense' not in obj['equipment']: obj['equipment']['defense'] = []

                # clear out existing secteams and anti_missiles
                to_remove = []
                for entry in obj['equipment']['defense']:
                    if ('secteam' in entry) or ('anti_missile' in entry):
                        to_remove.append(entry)
                for entry in to_remove: obj['equipment']['defense'].remove(entry)

                equip_list = []

                if random.random() < secteam_chance:
                    if obj['spec'] == 'tesla_coil':
                        equip_list.append('tesla_anti_missile_L5')
                        if 0:
                            equip_list.append('ai_warbird_secteam_L2')
                    else:
                        if 1:
                            level = int(level_range[0] + int((level_range[1]-level_range[0]+1)*random.random()))
                            specname = '%s_secteam_L%d' % (team_type, level)
                            equip_list.append(specname)

                    for specname in equip_list:
                        if specname not in gamedata['items']:
                            sys.stderr.write('bad specname '+specname+'\n')
                            sys.exit(1)
                        obj['equipment']['defense'].append(specname)

                # clean up empty equip lists
                if len(obj['equipment']['defense']) < 1: del obj['equipment']['defense']
                if len(obj['equipment']) < 1: del obj['equipment']

        atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
        atom.fd.write(SpinJSON.dumps(base, pretty = True)[1:-1]+'\n') # note: get rid of surrounding {}
        atom.complete()
