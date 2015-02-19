#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# example script to make base JSON files

try: import simplejson as json
except: import json

if __name__ == '__main__':
    print "// AUTO-GENERATED base file"

    out = {}

    out['tech'] = {'mining_droid_production':1}
    out['buildings'] = []
    out['units'] = []

    # add some buildings
    out['buildings'].append({'spec':'central_computer', 'force_level':3, 'xy': [90,90]})
    out['buildings'].append({'spec':'tesla_coil', 'force_level':5, 'xy': [105,90]})

    # add some units
    out['units'].append({'spec':'mining_droid', 'force_level':2, 'xy':[30,30]})
    out['units'].append({'spec':'blaster', 'force_level':2, 'xy':[70,70]})

    count = 0
    for key, val in out.iteritems():
        print '"%s":' % key, json.dumps(val, indent=2),
        if count != len(out)-1:
            print ','
        else:
            print
        count += 1
