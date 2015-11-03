#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library to randomize AI base defenses
# works on AI base/hive templates or JSON instantiations

import random, bisect
from Equipment import Equipment

# override for history_category-based secteam type determination
TEAM_TYPES = {}

# [min,max] level of security teams, indexed by base townhall level
TEAM_LEVELS = [[0,0], # townhall L1
               [0,0], # townhall L2
               [0,0], # townhall L3
               [1,2], # townhall L4
               [1,2], # townhall L5
               [3,4], # townhall L6
               [5,6], # townhall L7+
               ]
# chance of finding a security team on any building, indexed by base townhall level
TEAM_CHANCE = [0, # townhall L1
               0, # townhall L2
               0, # townhall L3
               0.20, # townhall L4
               0.35, # townhall L5
               0.45, # townhall L6
               0.55, # townhall L7
               0.65, # townhall L8
               0.75, # townhall L9
               0.85, # townhall L10+
               ]

ANTI_MISSILE_TYPES = {'auto_cannon': ['auto_cannon_anti_missile_L1', # townhall L1
                                      'auto_cannon_anti_missile_L1', # townhall L2
                                      'auto_cannon_anti_missile_L1', # townhall L3
                                      'auto_cannon_anti_missile_L1', # townhall L4
                                      'auto_cannon_anti_missile_L1', # townhall L5
                                      'auto_cannon_anti_missile_L1', # townhall L6
                                      'auto_cannon_anti_missile_L3', # townhall L7
                                      'auto_cannon_anti_missile_L3', # townhall L8
                                      'auto_cannon_anti_missile_L5', # townhall L9
                                      'auto_cannon_anti_missile_L5', # townhall L10+
                                      ]
                      }

ANTI_MISSILE_CHANCE = [0, # townhall L1
                       0, # townhall L2
                       0, # townhall L3
                       0, # townhall L4
                       0.2, # townhall L5
                       0.18, # townhall L6
                       0.16, # townhall L7
                       0.145, # townhall L8
                       0.13, # townhall L9
                       0.12, # townhall L10+
                       ]

# MINES
# [min,max] level of landmines, indexed by base townhall level
MINE_LEVELS = {"anti_infantry": [[0,0], # townhall L1
                                 [0,0], # townhall L2
                                 [0,0], # townhall L3
                                 [6,9], # townhall L4
                                 [9,10], # townhall L5+
                                 ],
               "anti_tank": [[0,0], # townhall L1
                              [0,0], # townhall L2
                              [0,0], # townhall L3
                              [1,2], # townhall L4
                              [3,4], # townhall L5
                              [5,6], # townhall L6
                              [7,9], # townhall L7
                              [9,10], # townhall L8
                              [10,10], # townhall L9+
                              ],
               "anti_air": [[0,0], # townhall L1
                            [0,0], # townhall L2
                            [0,0], # townhall L3
                            [1,2], # townhall L4
                            [3,4], # townhall L5
                            [5,6], # townhall L6
                            [7,9], # townhall L7
                            [9,10], # townhall L8
                            [10,10], # townhall L9+
                            ],
               }

# relative composition of landmines, indexed by base townhall level
MINE_COMPOSITION = [{"anti_infantry": 2, "anti_tank": 4, "anti_air": 4}, # townhall L1
                    {"anti_infantry": 2, "anti_tank": 4, "anti_air": 4}, # townhall L2
                    {"anti_infantry": 2, "anti_tank": 4, "anti_air": 4}, # townhall L3
                    {"anti_infantry": 2, "anti_tank": 4, "anti_air": 4}, # townhall L4
                    {"anti_infantry": 1, "anti_tank": 4.5, "anti_air": 4.5}, # townhall L5
                    {"anti_infantry": 0, "anti_tank": 5, "anti_air": 5}, # townhall L6+
                    ]

# max total number of landmines, indexed by base townhall level
MINE_NUM = [0, # townhall L1
            0, # townhall L2
            0, # townhall L3
            4, # townhall L4
            8, # townhall L5
            12, # townhall L6
            16, # townhall L7
            20, # townhall L8
            24, # townhall L9
            28, # townhall L10+
            ]

def is_minefield(gamedata, obj):
    return (obj['spec'] in gamedata['buildings']) and \
           ('mine' in gamedata['buildings'][obj['spec']].get('equip_slots',{}))

def randomize_defenses(gamedata, obj_list, random_seed = 42, ui_name = 'unknown', msg_fd = None):
    random.seed(random_seed)

    # get townhall level of the base
    townhall_level = -1
    for obj in obj_list:
        if obj['spec'] == gamedata['townhall']:
            townhall_level = obj.get('force_level', obj.get('level',1))
            break
    if townhall_level < 0:
        raise Exception('%s: no townhall found' % ui_name)

    # plan the landmine composition
    mine_list = [] # list of specname (or None) for landmines indexed by minefield's ordering within obj_list
    mine_level_range = dict((kind, MINE_LEVELS[kind][min(townhall_level-1, len(MINE_LEVELS[kind])-1)]) for kind in MINE_LEVELS)
    mine_composition = MINE_COMPOSITION[min(townhall_level-1, len(MINE_COMPOSITION)-1)]
    mine_num = MINE_NUM[min(townhall_level-1, len(MINE_NUM)-1)]

    if mine_composition and mine_num > 0:
        # how many possible mine placements are there?
        placement_count = sum((1 for obj in obj_list if is_minefield(gamedata, obj)), 0)
        if placement_count < mine_num:
            raise Exception('%s: defense randomizer needs %d minefields but only %d are present' % (ui_name, mine_num, placement_count))

        # chance of mine being of each kind
        kinds = sorted(mine_composition.keys())
        breakpoints = []
        bp = 0.0
        for kind in kinds:
            weight = mine_composition[kind]
            bp += weight
            breakpoints.append(bp)

        # build up a list of the mines we want
        for i in xrange(mine_num):
            r = breakpoints[-1] * random.random()
            kind = kinds[min(bisect.bisect(breakpoints, r), len(breakpoints)-1)]
            level = int(mine_level_range[kind][0] + int((mine_level_range[kind][1]-mine_level_range[kind][0]+1)*random.random()))
            specname = 'mine_%s_L%d' % (kind, level)
            if specname not in gamedata['items']:
                raise Exception('mine item does not exist: %s' % specname)
            mine_list.append(specname)

        # padd the list with empty mine placements
        mine_list += [None,] * (placement_count - mine_num)

        # scramble the list order
        random.shuffle(mine_list)

    if msg_fd: print >>msg_fd, 'landmines: %r' % mine_list

    mine_i = 0 # index into mine_list

    for obj in obj_list:
        if obj['spec'] not in gamedata['buildings']: continue # only mutate buildings
        spec = gamedata['buildings'][obj['spec']]

        # clear out existing secteams, mines, and anti_missiles
        if 'equipment' in obj:
            for slot_type in ('defense','leader','mine'):
                if slot_type in obj['equipment']:
                    obj['equipment'][slot_type] = filter(lambda x: not (('secteam' in x['spec']) or ('anti_missile' in x['spec']) or x['spec'].startswith('mine_anti_')),
                                                         Equipment.slot_type_iter(obj['equipment'][slot_type]))
        else:
            obj['equipment'] = {}

        # ANTI-MISSILE
        anti_missile_type = ANTI_MISSILE_TYPES.get(obj['spec'], None)
        if anti_missile_type:
            anti_missile_chance = ANTI_MISSILE_CHANCE[min(townhall_level-1, len(ANTI_MISSILE_CHANCE)-1)]
            specname = anti_missile_type[min(townhall_level-1, len(anti_missile_type)-1)]
            if specname not in gamedata['items']:
                raise Exception('anti-missile item does not exist: %s' % specname)
            if random.random() < anti_missile_chance:
                if msg_fd: print >>msg_fd, obj['spec'], 'anti-missile', [specname,]
                if 'defense' not in obj['equipment']:
                    obj['equipment']['defense'] = []
                obj['equipment']['defense'].append(specname)

        # SECURITY TEAMS
        if spec.get('history_category',None) in ('turrets','turret_emplacements'):
            secteam_type = 'turret'
        elif spec.get('provides_power',None):
            secteam_type = 'generator'
        elif spec.get('history_category',None) == 'storages':
            secteam_type = 'storage'
        elif spec.get('history_category',None) == 'harvesters':
            secteam_type = 'harvester'
        elif 'MAKE_DROIDS' in spec['spells'] or 'RESEARCH_FOR_FREE' in spec['spells']:
            secteam_type = 'harvester' # use harvester secteams for factories/labs
        else:
            secteam_type = TEAM_TYPES.get(obj['spec'], None)
        secteam_level_range = TEAM_LEVELS[min(townhall_level-1, len(TEAM_LEVELS)-1)]
        secteam_chance = TEAM_CHANCE[min(townhall_level-1, len(TEAM_CHANCE)-1)]

        if secteam_type and secteam_level_range[1] >= 1 and secteam_chance > 0:
            equip_list = []
            if random.random() < secteam_chance:
                level = int(secteam_level_range[0] + int((secteam_level_range[1]-secteam_level_range[0]+1)*random.random()))
                specname = '%s_secteam_L%d' % (secteam_type, level)
                if specname not in gamedata['items']:
                    raise Exception('security team item does not exist: %s' % specname)
                equip_list.append(specname)

            if equip_list:
                if msg_fd: print >>msg_fd, obj['spec'], 'secteam', equip_list

                if 'defense' not in obj['equipment']:
                    obj['equipment']['defense'] = []
                obj['equipment']['defense'] += equip_list

        # LANDMINES
        if mine_list and is_minefield(gamedata, obj):
            specname = mine_list[mine_i]
            if specname:
                if 'mine' not in obj['equipment']:
                    obj['equipment']['mine'] = []
                obj['equipment']['mine'].append(specname)
            mine_i += 1

        # clean up empty equip lists
        for slot_type in obj['equipment'].keys():
            if len(obj['equipment'][slot_type]) < 1: del obj['equipment'][slot_type]
        if len(obj['equipment']) < 1: del obj['equipment']


# test code - apply to a single AI base/hive
if __name__ == '__main__':
    import SpinJSON, SpinConfig
    import AtomicFileWrite
    import sys, os.path, getopt, time, traceback
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
    random_seed = 1000*time.time()
    opts, args = getopt.gnu_getopt(sys.argv, '', ['random-seed='])
    for key, val in opts:
        if key == '--random-seed': int(val)
    for filename in args[1:]:
        try:
            base = SpinConfig.load(filename, stripped = True)
            randomize_defenses(gamedata, base['buildings'], random_seed = random_seed, ui_name = os.path.basename(filename), msg_fd = sys.stdout)
            atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
            atom.fd.write(SpinJSON.dumps(base, pretty = True)[1:-1]+'\n') # note: get rid of surrounding {}
            atom.complete()
        except:
            sys.stderr.write(traceback.format_exc())

