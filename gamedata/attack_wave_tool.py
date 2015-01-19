#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# add security teams to an AI base

# with --level options, forces the force_levels on AI attack wave units to a specific level, or range of levels
# with --spread option, ensures that large waves are well-spread-out

import SpinJSON
import SpinConfig
import AtomicFileWrite
import sys, copy, getopt, os, random

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

if __name__ == '__main__':
    level_range = [-1,-1]
    spread = False
    opts, args = getopt.gnu_getopt(sys.argv, '', ['level=', 'min-level=', 'max-level=', 'spread'])

    for key, val in opts:
        if key == '--level': level_range = [int(val),int(val)]
        elif key == '--min-level': level_range[0] = int(val)
        elif key == '--max-level': level_range[1] = int(val)
        elif key == '--spread': spread = True

    for filename in args[1:]:
        base = SpinConfig.load(filename, stripped = True)

        for wavenum in xrange(len(base['units'])):
            wave = base['units'][wavenum]
            count = 0
            for key, val in wave.iteritems():
                if key not in gamedata['units']: continue
                if type(val) is not dict:
                    count += val
                    continue
                count += val.get('qty',1)
                if level_range[0] > 0 and level_range[1] > 0:
                    val['force_level'] = int(level_range[0] + int((level_range[1]-level_range[0]+1)*random.random()))

            # spread out waves containing large numbers of units
            if spread and count >= 7:
                wave['spread'] = 15
            print filename, "wave", wavenum, "units:", count

        atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
        atom.fd.write(SpinJSON.dumps(base, pretty = True)[1:-1]+'\n') # note: get rid of surrounding {}
        atom.complete()
