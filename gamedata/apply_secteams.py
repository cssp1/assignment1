#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinJSON
import SpinConfig
import AtomicFileWrite
import sys, getopt, random
from Equipment import Equipment

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

if __name__ == '__main__':
    level_range = [1,1]
    secteam_chance = 1.0
    random_seed = 42

    opts, args = getopt.gnu_getopt(sys.argv, '', ['level=', 'min-level=', 'max-level=', 'secteam-chance=', 'random-seed='])

    for key, val in opts:
        if key == '--level':
            level_range = [int(val),int(val)]
        elif key == '--min-level':
            level_range[0] = int(val)
        elif key == '--max-level':
            level_range[1] = int(val)
        elif key == '--secteam-chance':
            secteam_chance = float(val)
        elif key == '--random-seed':
            random_seed = int(val)

    for filename in args[1:]:
        random.seed(random_seed)

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
                for slot_type in ('defense','leader'):
                    if slot_type in obj['equipment']:
                        obj['equipment'][slot_type] = filter(lambda x: not (('secteam' in x['spec']) or ('anti_missile' in x['spec'])),
                                                             Equipment.slot_type_iter(obj['equipment'][slot_type]))

                equip_list = []

                if random.random() < secteam_chance:
                    level = int(level_range[0] + int((level_range[1]-level_range[0]+1)*random.random()))
                    specname = '%s_secteam_L%d' % (team_type, level)
                    if specname not in gamedata['items']:
                        raise Exception('bad specname '+specname+'\n')

                    equip_list.append(specname)

                obj['equipment']['defense'] += equip_list

                # clean up empty equip lists
                for slot_type in obj['equipment'].keys():
                    if len(obj['equipment'][slot_type]) < 1: del obj['equipment'][slot_type]
                    if len(obj['equipment']) < 1: del obj['equipment']

        atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
        atom.fd.write(SpinJSON.dumps(base, pretty = True)[1:-1]+'\n') # note: get rid of surrounding {}
        atom.complete()
