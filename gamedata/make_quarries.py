#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# From quarries_compiled.json, which contains everything about quarries,
# create cut-down versions quarries_client.json and quarries_server.json
# containing only the fields that the client and server need.

import SpinJSON
import AtomicFileWrite
import sys, os, getopt, copy

def make_client_quarry_template(template):
    out = {'ui_name': template['ui_name'],
           'base_richness': template['base_richness'],
           'icon': template['icon']}
    for FIELD in ('activation', 'show_if', 'turf_points', 'info_tip'):
        if FIELD in template: out[FIELD] = template[FIELD]
    return out

def make_server_quarry_template(template):
    out = copy.copy(template)
    for FIELD in ('units','scenery','buildings'):
        if FIELD in out:
            del out[FIELD]
    return out

MODE_CLIENT = 0
MODE_SERVER = 1

if __name__ == '__main__':
    mode = None
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['client','server'])

    for key, val in opts:
        if key == '--client': mode = MODE_CLIENT
        elif key == '--server': mode = MODE_SERVER

    if mode is None:
        raise Exception('specify --client or --server')

    quarries = SpinJSON.load(open(args[0]), 'quarries_compiled.json')
    out_fd = AtomicFileWrite.AtomicFileWrite(args[1], 'w', ident=str(os.getpid()))

    #print >> out_fd.fd, "// AUTO-GENERATED BY make_quarries.py %s" % (' '.join(sys.argv[1:]))

    if mode is MODE_CLIENT:
        out = {'templates':{}} # opt-in, include only 'templates'
    elif mode is MODE_SERVER:
        out = copy.copy(quarries)
        out['templates'] = {} # out-out, include everything, but clean out 'templates'

    for PROP in ('alliance_turf', 'alliance_bonuses'):
        if PROP in quarries:
            out[PROP] = quarries[PROP]

    ids = sorted(quarries['templates'].keys())
    for id in ids:
        template = quarries['templates'][id]
        if mode is MODE_CLIENT:
            out['templates'][id] = make_client_quarry_template(template)
        elif mode is MODE_SERVER:
            out['templates'][id] = make_server_quarry_template(template)

    SpinJSON.dump(out, out_fd.fd, pretty = True, newline = True)
    out_fd.complete()
