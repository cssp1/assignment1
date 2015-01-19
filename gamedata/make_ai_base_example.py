#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# instructions for running this script:
# go to the gamedata/ directory
# PYTHONPATH=../gameserver ./make_ai_base_example.py
# (optional: use > to write output to a file instead of printing to the console)

import SpinJSON # JSON reading/writing library
import SpinConfig
import AtomicFileWrite # little library for safely overwriting files atomically
import sys, copy, getopt, os, random # import some misc. Python libraries

# load in gamedata
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

if __name__ == '__main__':
    townhall_level = 1 # this is a parameter that controls the townhall level

    opts, args = getopt.gnu_getopt(sys.argv, '', ['townhall-level='])

    for key, val in opts:
        if key == '--townhall-level':
            townhall_level = int(val)

    # If you need to load an EXISTING base JSON file, here is how to do it:
    if len(args) > 1:
        filename = args[1]
        # SpinConfig.load reads JSON, and strips out comments
        old_base = SpinConfig.load(filename, stripped = True)
        # at this point, "old_base" will be a Python data structure (actually a dictionary)
        # that contains everything that was in the JSON file you loaded

    # let's create a fresh AI base JSON structure from scratch
    base = {'scenery': [], 'buildings': [], 'units': []}

    # let's add some scenery objects
    base['scenery'].append({"xy": [50,90],
                            "spec": "scenery_cave_stalag_big"})

    # let's add some buildings
    base['buildings'].append({"xy": [90,90],
                              "spec": "toc",
                              # note: please use "force_level" rather than "level" so that it overrides the server's auto-leveling code
                              "force_level": townhall_level
                              })

    # let's add some units
    base['units'].append({"xy": [120,90],
                          "spec": "t90",
                          # note: please use "force_level" rather than "level" so that it overrides the server's auto-leveling code
                          "force_level": 5
                          })

    # convert the Python data structure into a string for final output
    output_json = SpinJSON.dumps(base, pretty = True)[1:-1]+'\n' # note: get rid of surrounding {}
    print output_json,


    # in case you want to write the output to a particular file, here is how to do it:
#    atom = AtomicFileWrite.AtomicFileWrite(output_filename, 'w')
#    atom.fd.write(output_json)
#    atom.complete()
