#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# automatically generate quarries_client.json from quarries.json

import SpinJSON
import AtomicFileWrite
import sys, os, getopt

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])

    quarries = SpinJSON.load(open(args[0]), 'quarries_compiled.json')
    out_fd = AtomicFileWrite.AtomicFileWrite(args[1], 'w', ident=str(os.getpid()))

    print >> out_fd.fd, "// AUTO-GENERATED BY make_quarries_client.py"

    out = {'templates':{}}

    if 'alliance_turf' in quarries:
        out['alliance_turf'] = quarries['alliance_turf']

    ids = sorted(quarries['templates'].keys())
    for id in ids:
        template = quarries['templates'][id]
        out['templates'][id] = {'ui_name': template['ui_name'],
                                'base_richness': template['base_richness'],
                                'icon': template['icon']}
        for FIELD in ('activation', 'show_if', 'turf_points', 'info_tip'):
            if FIELD in template: out['templates'][id][FIELD] = template[FIELD]

    SpinJSON.dump(out, out_fd.fd, pretty = True, newline = True)
    out_fd.complete()
