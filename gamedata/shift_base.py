#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinJSON
import SpinConfig
import AtomicFileWrite
import sys, copy, getopt, os, random

if __name__ == '__main__':
    dx = 0
    dy = 0
    opts, args = getopt.gnu_getopt(sys.argv, 'x:y:', ['x=', 'y='])

    for key, val in opts:
        if key == '-x' or key == '--x': dx = int(val)
        elif key == '-y' or key == '--y': dy = int(val)

    for filename in args[1:]:
        base = SpinConfig.load(filename, stripped = True)

        for obj in base['buildings'] + base.get('scenery',[]):
            obj['xy'][0] += dx; obj['xy'][1] += dy

        for obj in base['units']:
            obj['xy'][0] += dx; obj['xy'][1] += dy
            if 'orders' in obj:
                for o in obj['orders']:
                    if 'dest' in o:
                        o['dest'][0] += dx; o['dest'][1] += dy

        atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
        atom.fd.write(SpinJSON.dumps(base, pretty = True)[1:-1]+'\n') # note: get rid of surrounding {}
        atom.complete()
