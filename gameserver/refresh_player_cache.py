#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# refresh all entries in dbserver player cache

import sys
import getopt
import SpinJSON
import SpinNoSQL
import SpinUserDB
import SpinConfig
import multiprocessing
import functools

SEGMENTS = 50

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty

def get_dps(spec, level):
    if len(spec['spells']) < 1:
        return 0
    spell = gamedata['spells'][spec['spells'][0]]
    if spell['activation'] != 'auto' or spell.get('help', 0):
        return 0
    dps = get_leveled_quantity(spell.get('damage',0), level)

    if spell.get('targets_self',0):
        # count suicide attacks as half as much DPS
        dps *= 0.5
    elif 'splash_range' in spell:
        # count splash-capable attacks as twice as much DPS
        dps *= 2

    return dps

def calc_base_damage(player):
    base_hp_total = 0
    base_hp_max = 0.1
    for obj in player['my_base']:
        specname = obj['spec']
        if specname in gamedata['buildings']:
            spec = gamedata['buildings'][specname]
            base_hp_total += obj['hp']
            base_hp_max += get_leveled_quantity(spec['max_hp'], obj['level'])
    base_hp_total = int(base_hp_total)
    base_hp_max = int(base_hp_max)
    return float(base_hp_max - base_hp_total) / base_hp_max

def get_lootable_buildings(player):
    total = 0
    for obj in player['my_base']:
        if obj['hp'] > 0:
            specname = obj['spec']
            if specname in gamedata['buildings']:
                spec = gamedata['buildings'][specname]
                for rsrc in gamedata['resources']:
                    if 'storage_'+rsrc in spec:
                        total += 1
                        break
    return total

def update_user(user_id, db_client):
    if user_id < 1100:
        # AI users
        return

    if 0 or (user_id % 1000 == 0):
        sys.stderr.write('processing %d\n' % user_id)

    if 1:
#    try:
        try:
            user = SpinJSON.loads(SpinUserDB.driver.sync_download_user(user_id))
            player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))
        except:
            user = None
            player = None

        if (not user) or (not player):
            return

        props = {}

        for FIELD in ('social_id', 'facebook_id', 'bh_id', 'kg_id', 'ag_id', 'ag_avatar_url', 'kg_avatar_url'):
            if user.get(FIELD):
                props[FIELD] = user[FIELD]

        if user.get('alias', None):
            props['ui_name'] = user['alias']
        elif user.get('ag_username',None):
            props['ui_name'] = user['ag_username']
        elif user.get('kg_username',None):
            props['ui_name'] = user['kg_username']
        elif user.get('bh_username',None):
            props['ui_name'] = user['bh_username']
        elif user.get('facebook_first_name', None):
            props['ui_name'] = user['facebook_first_name']
        elif user.get('facebook_name', None):
            props['ui_name'] = user['facebook_name'].split(' ')[0]
        else:
            props['ui_name'] = 'unknown'

        props['last_login_time'] = user.get('last_login_time', -1)

        props['tutorial_complete'] = 1 if player.get('tutorial_state','START') == 'COMPLETE' else 0
        props['protection_end_time'] = player['resources']['protection_end_time']
        props['player_level'] = player['resources'].get('player_level',1)

        # COMPUTE PVP RATING
        props['lootable_buildings'] = get_lootable_buildings(player)

        #print props
        if db_client and do_write:
            db_client.player_cache_update(user_id, props)

#    except:
#        sys.stderr.write('PROBLEM USER: %d\n' % user_id)
#        raise

do_write = False

def g_update_user(seg):
    sys.stderr.write('seg %d/%d start\n' % (seg, SEGMENTS-1))
    db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    id_range = db_client.get_user_id_range()

    id_set = [id for id in xrange(id_range[0], id_range[1]+1) if (id % SEGMENTS) == seg]
    for user_id in id_set:
        update_user(user_id, db_client)
    sys.stderr.write('seg %d/%d DONE\n' % (seg, SEGMENTS-1))


if __name__ == "__main__":
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['write', 'file=', 'parallel='])
    args = sys.argv[1:]
    if len(args) < 0:
        print 'usage: %s [--write] [--file=userdb/1234.txt]' % sys.argv[0]
        sys.exit(1)

    parallel = 1

    for key, val in opts:
        if key == '--write':
            do_write = True
        elif key == '--parallel':
            parallel = int(val)

    func = functools.partial(g_update_user, do_write)

    if parallel == 1:
        for seg in xrange(SEGMENTS):
            g_update_user(seg)
    else:
        pool = multiprocessing.Pool(parallel)
        chunksize = 1
        pool.map(g_update_user, range(SEGMENTS), chunksize)
        pool.close()
        pool.join()


