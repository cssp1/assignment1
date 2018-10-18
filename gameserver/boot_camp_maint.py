#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Script that runs externally to main server process to manage "Boot Camp" clan membership
# by kicking inactive players

import sys, time, getopt
import SpinConfig, SpinJSON
import SpinNoSQL
import SpinSingletonProcess
import ControlAPI

time_now = int(time.time())
dry_run = False
verbose = 1
identity = 'BootCampMaint'

def do_CONTROLAPI(args):
    args['ui_reason'] = identity # for CustomerSupport action log entries
    return ControlAPI.CONTROLAPI(args, identity, max_tries = 3) # allow some retries

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'vq', ['dry-run'])

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '-v':
            verbose = 2
        elif key == '-q':
            verbose = 0
        elif key == '--non-incremental':
            incremental = False

    # partial gamedata load
    gamedata = {'server': SpinConfig.load(SpinConfig.gamedata_component_filename("server_compiled.json"))}

    # check what the Boot Camp clan ID is
    alliance_id_list = []
    if 'recommend_alliance' in gamedata['server']:
        for pred, value in gamedata['server']['recommend_alliance']:
            if value != -1:
                alliance_id_list.append(value)

    if not alliance_id_list:
        if verbose >= 1:
            print 'did not find any recommend_alliance IDs for this game'
        sys.exit(0)

    if 0:
        # load all of gamedata
        new_gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
        new_gamedata['server'] = gamedata['server']
        gamedata = new_gamedata

    with SpinSingletonProcess.SingletonProcess('%s-%s' % (identity, SpinConfig.config['game_id'],)):

        db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = identity)
        db_client.set_time(time_now)

        for alliance_id in alliance_id_list:
            to_kick = []

            # get list of current members
            user_id_list = db_client.get_alliance_member_ids(alliance_id)

            if verbose >= 1:
                print 'current alliance members:', len(user_id_list)

            # get pcache data on these users
            pcache_list = db_client.player_cache_lookup_batch(user_id_list, fields = ['last_login_time', 'account_creation_time', 'uninstalled', 'developer'])

            # check each player to see if we want to kick them
            for user_id, pcache in zip(user_id_list, pcache_list):
                if pcache.get('developer', False):
                    if verbose >= 2:
                        print user_id, 'is developer'
                    continue
                if pcache.get('uninstalled', False):
                    if verbose >= 2:
                        print user_id, 'uninstalled, kicking!'
                    to_kick.append(user_id)
                    continue
                if time_now - pcache['account_creation_time'] < 48*3600:
                    if verbose >= 2:
                        print user_id, 'account created less than 48 hours ago'
                    continue
                if time_now - pcache['last_login_time'] < 48*3600:
                    if verbose >= 2:
                        print user_id, 'has logged in within the last 48 hours'
                    continue

                if verbose >= 2:
                    print user_id, 'kicking!'
                to_kick.append(user_id)

            if to_kick:
                if verbose >= 1:
                    print 'will kick these members:', to_kick
                if not dry_run:
                    for user_id in to_kick:
                        do_CONTROLAPI({'user_id':user_id, 'method':'kick_alliance_member'})
                        if verbose >= 2:
                            print 'kicked', user_id
