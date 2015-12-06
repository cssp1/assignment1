#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# fix AI base JSON files that are missing "force_level" on buildings

import SpinJSON
import SpinConfig
import AtomicFileWrite
import sys, getopt

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

if __name__ == '__main__':
    dry_run = False
    opts, args = getopt.gnu_getopt(sys.argv, '', ['dry-run'])

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True

    for filename in args[1:]:
        base = SpinConfig.load(filename, stripped = True)
        if 'buildings' not in base: continue

        for obj in base['buildings']:
            if obj['spec'] in ('barrier','minefield',): continue

            if 'force_level' in obj: continue # good
            level = obj.get('level', 1)
            if 'level' in obj:
                del obj['level']
            obj['force_level'] = level
            print '%s: fixing %s -> L%d' % (filename, obj['spec'], level)

        if not dry_run:
            atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
            atom.fd.write(SpinJSON.dumps(base, pretty = True)[1:-1]+'\n') # note: get rid of surrounding {}
            atom.complete()
