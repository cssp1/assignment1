#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

try: import simplejson as json
except: import json

TARGETS = ['rover', 'transport', 'starcraft', 'building']
QUALITIES = ['ineffective', 'poor', 'good', 'excellent']

for i in xrange(len(TARGETS)):
    targ = TARGETS[i]
    ret = '    "damage_vs_'+targ+'": '
    data = {'states':{}}
    for j in xrange(len(QUALITIES)):
        qual = QUALITIES[j]
        data['states'][qual] = {
            'images': ['art/ui/damage_vs_icons3.png'],
            'dimensions': [21,21],
            'load_priority': 70,
            'origins': [21*j,21*i]
            }
    ret += json.dumps(data)
    ret += ','
    print ret
#   "resource_icon_power": { "states": { "normal": { "images": ["art/ui/resource_icons3.png"], "origins": [0,84], "dimensions": [21,21], "load_priority": 100 } } },
