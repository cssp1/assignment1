#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# From ai_bases_compiled.json, which contains everything about AI bases,
# create cut-down versions ai_bases_client.json and ai_bases_server.json
# containing only the fields that the client and server need.

import SpinJSON
import AtomicFileWrite
import sys, os, getopt, copy

def copy_display_message_consequent(cons):
    if cons['consequent'] == "DISPLAY_MESSAGE":
        return cons
    elif 'subconsequents' in cons:
        for sub in cons['subconsequents']:
            ret = copy_display_message_consequent(sub)
            if ret: return ret
    return None

def make_client_base(strid, base):
    # client is "opt-in" to be as bare-bones as possible
    client_base =  {'portrait': base['portrait'],
                    'resources': base['resources'],
                    'ui_name': base['ui_name'],
                    'activation': base['activation'] }

    for FIELD in ('kind', 'show_if', 'persistent', 'attack_time', 'base_resource_loot',
                  'ui_priority', 'ui_category', 'ui_info', 'ui_info_url', 'ui_resets', 'ui_instance_cooldown', 'ui_spy_button', 'ui_map_name', 'ui_progress', 'ui_difficulty', 'ui_difficulty_index',
                  'ui_battle_stars_key', 'ui_fancy_victory_text',
                  'challenge_icon', 'challenge_item',
                  'map_portrait'
                  ):
        if FIELD in base: client_base[FIELD] = base[FIELD]

    # awkward - on_visit DISPLAY_MESSAGE consequents must be known client-side for
    # AI attacks, since the code to round-trip them from the sever would be ugly.
    if base.get('kind', 'ai_base') == 'ai_attack':
        if 'on_visit' in base:
            cons = copy_display_message_consequent(base['on_visit'])
            if cons:
                client_base['on_visit'] = cons
    return client_base

def make_server_base(strid, base):
    # server is "opt-out", omitting only the base contents
    server_base = copy.copy(base)

    if base.get('kind', 'ai_base') != 'ai_attack':
        # 'units' still need to be present for ai_attacks
        if 'units' in server_base:
            del server_base['units']

    for FIELD in ('scenery', 'buildings'):
        if FIELD in server_base:
            del server_base[FIELD]
    return server_base

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

    ai_bases = SpinJSON.load(open(args[0]), 'ai_bases_compiled.json')
    out_fd = AtomicFileWrite.AtomicFileWrite(args[1], 'w', ident=str(os.getpid()))

    print >> out_fd.fd, "// AUTO-GENERATED BY make_ai_bases.py %s" % (' '.join(sys.argv[1:]))

    if mode is MODE_CLIENT:
        out = {'bases':{}} # opt-in, include only 'bases'
    elif mode is MODE_SERVER:
        out = copy.copy(ai_bases)
        out['bases'] = {} # out-out, include everything, but clean out 'bases'

    for strid, base in ai_bases['bases'].iteritems():
        if mode is MODE_CLIENT:
            out_base = make_client_base(strid, base)
        elif mode is MODE_SERVER:
            out_base = make_server_base(strid, base)

        out['bases'][strid] = out_base

    SpinJSON.dump(out, out_fd.fd, pretty = True, newline = True)
    out_fd.complete()
