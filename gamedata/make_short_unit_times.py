#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import simplejson as json

gamedata = json.load(open('gamedata.json'))
freetime = gamedata['store']['free_speedup_time']

def alter_time(t):
    newt = int(t/2)

    # do not create times that are close to the free production time limit
    # (which often causes order confusion), instead push it under
    if newt > (freetime-15) and newt < (freetime+15):
        newt = (freetime-15)
    return newt

if __name__ == '__main__':

    ret = {}
    for name, unit in gamedata['units'].iteritems():
        old_times = unit['build_time']
        if type(old_times) == list:
            new_times = map(alter_time, old_times)
        else:
            new_times = alter_time(old_times)

        ret[name] = {'build_time': new_times}

    print json.dumps(ret, separators=(',',':'))
