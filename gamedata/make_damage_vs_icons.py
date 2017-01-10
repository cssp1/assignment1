#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

try: import simplejson as json
except: import json

TARGETS = ['rover', 'transport', 'starcraft', 'building', 'splash', 'scout']
QUALITIES = ['ineffective', 'poor', 'good', 'excellent', 'superior']

for i in xrange(len(TARGETS)):
    targ = TARGETS[i]
    ret = '    "damage_vs_'+targ+'": '
    data = {'states':{}}
    for j in xrange(len(QUALITIES)):
        qual = QUALITIES[j]
        data['states'][qual] = {
            'images': ['art/ui/damage_vs_icons6.png'],
            'dimensions': [21,21],
            'load_priority': 70,
            'origins': [21*j,21*i]
            }
    ret += json.dumps(data)
    ret += ','
    print ret
