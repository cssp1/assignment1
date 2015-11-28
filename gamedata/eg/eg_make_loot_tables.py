#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this script makes the AI loot-drop tables

import SpinJSON
import AtomicFileWrite
import sys, os, getopt

if __name__ == '__main__':
    #print "// AUTO-GENERATED BY make_loot_tables.py"

    # relative likelihood to get the different frequency classes
    FREQUENT_WEIGHT = 100
    INFREQUENT_WEIGHT = 30
    AWESOME_WEIGHT = 5

    out = dict([(data['name'], data) for data in [

        # Gamebucks SKU item bundles

        # for the ~$5 USD, 500-gamebuck SKU
        {"name": "item_bundle_500", "loot": []},
        # for the ~$10 USD, 1000-gamebuck SKU
        {"name": "item_bundle_1000", "loot": []},
        # for the ~$25 USD, 2500-gamebuck SKU
        {"name": "item_bundle_2500", "loot": []},
        # for the ~$50 USD, 5000-gamebuck SKU
        {"name": "item_bundle_5000", "loot": []},
        # for the ~$100 USD, 10000-gamebuck SKU
        {"name": "item_bundle_10000", "loot": []},
        # for the ~$200 USD, 20000-gamebuck SKU
        {"name": "item_bundle_20000", "loot": []},

        # return one packaged L1+ unit that represents the "sexiest" unit the player has already unlocked
        {"name": "sexy_unlocked_unit",
         "loot": [{"cond": [
        # note: these are in (somewhat arbitrary) order from "most sexy" to "least sexy"
        [{"predicate":"ALWAYS_TRUE"}, {"spec": "packaged_rifleman"}]
        ]}]
         },

        # same as sexy_unlocked_unit, but gives a 5-pack instead of just 1 unit
        {"name": "sexy_unlocked_unit_5pack",
         "loot": [{"multi": [{"table": "sexy_unlocked_unit"}], "multi_stack": 5}]
         },

        # some multiples of different missile types

        # free and paid random item SKUs in the in-game store
        # *** use gameserver/LootTable.py to check the Expected Value resulting from this table ***
        {"name": "store_random_item",
         "loot":[
             # Best available unit rewards
             {"multi": [{"table": "sexy_unlocked_unit"}], "multi_stack": 5, "weight": 0.04},
             ]
         },

        {"name": "daily_random_item",
            "loot":[
                # Packaged Units
                {"multi": [{"table": "sexy_unlocked_unit"}], "multi_stack": 2, "weight": 0.06},

                # Resources
                {"spec": "boost_iron_10000", "weight": 0.3},
                {"spec": "boost_water_10000", "weight": 0.3},
                {"spec": "boost_iron_20000", "weight": 0.18},
                {"spec": "boost_water_20000", "weight": 0.18},
                {"spec": "boost_iron_50000", "weight": 0.12},
                {"spec": "boost_water_50000", "weight": 0.12},
                {"spec": "boost_iron_100000", "weight": 0.07},
                {"spec": "boost_water_100000", "weight": 0.07},
            ]
        },
  ]])

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])
    out_fd = AtomicFileWrite.AtomicFileWrite(args[0], 'w', ident=str(os.getpid()))

    count = 0
    print >>out_fd.fd, '{',
    for data in out.itervalues():
        # verify
        err = None
        for entry in data['loot']:
            # do not bother checking for valid 'spec' here - let verify.py do it
            if 'table' in entry:
                if entry['table'] not in out:
                    err = 'refers to non-existent loot table "'+entry['table']+'"'
        if err:
            sys.stderr.write('Error in '+sys.argv[0]+': table "' + data['name'] + '" '+ err + '\n')
            sys.exit(1)

        print >>out_fd.fd, '"%s":' % data['name'], SpinJSON.dumps(data, pretty=True),
        if count != len(out)-1:
            print >>out_fd.fd, ','
        else:
            print >>out_fd.fd
        count += 1
    print >>out_fd.fd, '}'
    out_fd.complete()
