#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# automatically generate tech_mods.json from tech.json

import SpinConfig
import SpinJSON
import AtomicFileWrite
import sys, os, getopt

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['game-id=',])

    game_id = None
    for key, val in opts:
        if key == '--game-id' or key == '-g':
            game_id = val
    assert game_id

    if game_id != 'mf': # no mods except in old MF
        sys.exit(0)

    gamedata = SpinConfig.load(args[0], stripped = True) # main_options.json only
    tech = SpinConfig.load(args[1], stripped = True)
    out_fd = AtomicFileWrite.AtomicFileWrite(args[2], 'w', ident=str(os.getpid()))

    print >>out_fd.fd, "// AUTO-GENERATED BY make_tech_mod_quests.py"

    out = {}

    VALUES = [{'name': 'health', 'ui_name': 'Health', 'ui_flavor_name': 'Beef Up',
               "ui_instructions": "Modify any unit's Health attribute to level %d using the Research menu",
               "ui_description": "Our enemies are tough, we need to get tougher. Use our new modification options to boost the health of our units."},
              {'name': 'damage', 'ui_name': 'Damage', 'ui_flavor_name': 'Add Firepower',
               "ui_instructions": "Modify any unit's DPS (Damage Per Second) to level %d using the Research menu",
               "ui_description": "These new offensive upgrades please me to no end, Commander."},
              {'name': 'armor', 'ui_name': 'Armor', 'ui_flavor_name': 'Double-plated',
               "ui_instructions": "Modify any unit's Armor attribute to level %d using the Research menu",
               "ui_description": "With these new defensive upgrades, our battle units will stay and fight while lesser robots get blown to dust."},

              ]

    MOD_LEVELS = 5 # how many levels of mods to cover

    for vals in VALUES:
        for level in xrange(1, MOD_LEVELS+1):

            quest = {
                "name": "any_mod_tech_%s_%d" % (vals['name'], level),
                "ui_name": "Modify %s Level %d" % (vals['ui_name'], level),
                "ui_priority": -10,
                "ui_flavor_name": vals['ui_flavor_name'],
                "ui_instructions": vals['ui_instructions'] % level,
                "ui_description": vals['ui_description'],
#                "goal": {"predicate": "OR", "subpredicates":
#                         [{"predicate": "TECH_LEVEL", "tech": tech_name.replace('_production', '_'+vals['name']), "min_level": level} \
#                          for tech_name, tech_spec in tech.iteritems() if tech_name.endswith('_production')]},
                "goal": {"predicate": "ALWAYS_FALSE"}, # obsolete
                "reward_xp": 100 * level,
                "reward_iron": 1000 * level,
                "reward_water": 1000 * level
                }

            quest['activation'] = {"predicate": "AND", "subpredicates":
                                   [
                {"predicate": "ALWAYS_FALSE"}
                #{"predicate": "ANY_ABTEST", "key": "enable_mod_techs", "value": 1, "default": 0 }
                                    ]}
            if level == 1:
                quest['activation']['subpredicates'].append({"predicate": "LIBRARY", "name": "extended_tutorial_complete"})
                quest['activation']['subpredicates'].append({"predicate": "BUILDING_LEVEL", "building_type": gamedata['townhall'], "trigger_level": 4 })
            else:
                quest['activation']['subpredicates'].append({"predicate": "QUEST_COMPLETED", "quest_name": "any_mod_tech_%s_%d" % (vals['name'], level-1) })


            out[quest['name']] = quest

    count = 0
    for name, data in out.iteritems():
        print >>out_fd.fd, '"%s":' % name, SpinJSON.dumps(data, pretty=True),
        if count != len(out)-1:
            print >>out_fd.fd, ','
        else:
            print >>out_fd.fd
        count += 1
    out_fd.complete()
