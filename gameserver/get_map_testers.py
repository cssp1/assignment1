#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# sample script for dumping info out of playerdb file

import SpinUserDB
import SpinConfig
import SpinJSON

# load some standard Python libraries
import sys, time, getopt, csv, traceback

time_now = int(time.time())

def check_bloat(input, min_size = 1024, print_max = 20):
    sizes = []
    for key, val in input.iteritems():
        slen = len(SpinJSON.dumps(val, pretty=True))
        if slen > min_size:
            sizes.append([key, slen])
    sizes = sorted(sizes, key = lambda x: -x[1])
    for key, slen in sizes[0:print_max]:
        print '%-50s %-10.2f kB' % (key, slen/1024.0)

# main program
if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['bloat', 'abtests', 'get', 'put', 'get-user', 'put-user', 'stdio', 'stdin', 'stdout',
                                                      'ban', 'ban-days=', 'unban', 'gag', 'ungag', 'isolate', 'unisolate', 'make-chat-mod', 'unmake-chat-mod',
                                                      'db-host=', 'db-port=', 'db-secret=',
                                                      's3', 's3-key-file=', 's3-userdb-bucket=', 's3-playerdb-bucket=',
                                                      'user-id=', 'facebook-id=', 'game-id=',
                                                      'give-alloy=', 'give-protection-time=', 'give-item=', 'melt-hours=', 'item-stack=',
                                                      'give-item-subject=', 'give-item-body=',
                                                      'send-message', 'message-subject=', 'message-body=', 'message-sender=', 'message-expire-time=', 'message-expire-in=',
                                                      'fix-leaderboard',
                                                      'testers-n=', 'quiet'
                                                      ])


    fmt = '%-20s %-50s'
    game_id = SpinConfig.config['game_id']
    user_id = None
    facebook_id = None
    bloat = False
    abtests = False
    db_host = None
    db_port = None
    db_secret = None
    force_s3 = False
    s3_key_file = None
    s3_userdb_bucket = None
    s3_playerdb_bucket = None
    give_alloy = 0
    give_protection_time = 0
    do_get = False
    do_get_user = False
    do_put = False
    do_put_user = False
    use_stdio = False
    do_ban = False
    ban_days = 365*2
    do_unban = False
    do_gag = False
    do_ungag = False
    do_make_chat_mod = False
    do_unmake_chat_mod = False
    do_isolate = False
    do_unisolate = False
    do_leaderboard = False
    give_item = None
    send_message = False
    message_sender = 'SpinPunch'
    message_subject = ''
    message_body = ''
    message_expire_time = -1
    item_stack = 1
    item_melt_hours = -1
    testers_n = 99999999
    verbose = True

    for key, val in opts:
        if key == '--bloat':
            bloat = True
        elif key == '--abtests':
            abtests = True
        elif key == '--get':
            do_get = True
        elif key == '--get-user':
            do_get_user = True
        elif key == '--put':
            do_put = True
        elif key == '--put-user':
            do_put_user = True
        elif key in ('--stdio', '--stdin', '--stdout'):
            use_stdio = True
        elif key == '--db-host':
            db_host = val
        elif key == '--db-port':
            db_port = int(val)
        elif key == '--db-secret':
            db_secret = val
        elif key == '--s3':
            force_s3 = True
        elif key == '--s3-key-file':
            s3_key_file = val
        elif key == '--s3-userdb-bucket':
            s3_userdb_bucket = val
        elif key == '--s3-playerdb-bucket':
            s3_playerdb_bucket = val
        elif key == '--user-id':
            user_id = int(val)
        elif key == '--facebook-id':
            facebook_id = str(val)
        elif key == '--game-id':
            game_id = val
        elif key == '--testers-n':
            testers_n = int(val)
        elif key == '--quiet':
            verbose = False

    wufoo_filename = None
    if len(args) > 0:
        wufoo_filename = args[0]

    if not wufoo_filename:
        print 'usage: %s [options]' % sys.argv[0]

    if force_s3:
        driver = SpinUserDB.S3Driver(game_id = game_id, key_file = s3_key_file,
                                     userdb_bucket = s3_userdb_bucket,
                                     playerdb_bucket = s3_playerdb_bucket)
    else:
        driver = SpinUserDB.driver

    reader = csv.DictReader(open(wufoo_filename))
    user_id_list = [int(x['Player_ID']) for x in reader if x['Player_ID'].isdigit()]

    MIN_HOURS = -1 # min hours of gameplay in last 2 days
    MAX_SPEND = 999999.00 # spend cutoff
    ALLOW_COUNTRIES = ['ALL'] # ['gb','fr','ph','ro','hu','gr']
    BLACKLIST_COUNTRIES = [] # ['us','dk','fi','nl','no','se']
    ALLOW_ANY_TIER4 = True
    ALLOW_FOREMAN_BUSY = True
    MIN_CC_LEVEL = -1
    MIN_TRANSMITTER_LEVEL = -1

    accepted = []
    seen = set()

    for user_id in user_id_list:
        if user_id in seen: continue
        seen.add(user_id)

        user_filename = '%d.txt' % (user_id)
        player_filename = '%d_%s.txt' % (user_id, game_id)

        if verbose: print >> sys.stderr, 'checking', user_id, '...',

        try:
            player = SpinJSON.loads(driver.sync_download_player(user_id))
            user = SpinJSON.loads(driver.sync_download_user(user_id))
        except KeyboardInterrupt:
            break
        except:
            if verbose:
                print >> sys.stderr, 'error loading', user_id
                print >> sys.stderr, traceback.format_exc()
            continue

        gamedata = {'mf':{'townhall':'central_computer'},
                    'tr':{'townhall':'toc'}}[game_id]


        country = user.get('country', 'unknown')
        tier = SpinConfig.country_tier_map.get(country, 4)
        if ALLOW_ANY_TIER4 and tier == 4:
            pass # skip check
        else:
            if (('ALL' not in ALLOW_COUNTRIES) and (country not in ALLOW_COUNTRIES)) or \
               (country in BLACKLIST_COUNTRIES):
                if verbose: print >> sys.stderr, 'disallowed country', country
                continue

        if player['history'].get(gamedata['townhall']+'_level',1) < MIN_CC_LEVEL:
            if verbose: print >> sys.stderr, 'CC level not high enough'
            continue

        if player['history'].get('transmitter_level',0) < MIN_TRANSMITTER_LEVEL:
            if verbose: print >> sys.stderr, 'Transmitter level not high enough'
            continue

        spend = player['history'].get('money_spent',0)
        if spend > MAX_SPEND:
            if verbose: print >> sys.stderr, 'spent too much ($%.2f)' % spend
            continue

        if not ALLOW_FOREMAN_BUSY:
            is_busy = False
            for obj in player['my_base']:
                if obj['spec'] == gamedata['townhall'] or obj['spec'] == 'transmitter':
                    if 'upgrade_total_time' in obj:
                        if verbose: print >> sys.stderr, 'building is upgrading:', obj['spec']
                        is_busy = True; break
            if is_busy: continue

        price_region = SpinConfig.price_region_map.get(country, 'unknown')

        in_hrs = 0
        if 'sessions' in player['history']:
            sessions = player['history']['sessions']
            LAST_DAYS = 2
            begin_time = time_now - LAST_DAYS*24*60*60
            in_count = 0
            in_time = 0
            for s in sessions:
                if s[0] < begin_time:
                    continue
                if s[0] >= begin_time:
                    if s[1] > s[0]:
                        in_count += 1
                        in_time += s[1]-s[0]
            in_hrs = float(in_time)/3600.0
            in_pct = 100.0 * in_time / float(time_now - begin_time)

        if in_hrs < MIN_HOURS:
            if verbose: print >> sys.stderr, 'did not play enough (%.2f hrs)' % in_hrs
            continue

        if player.get('isolate_pvp',0) or player.get('banned_until',-1) > 0:
            if verbose: print >> sys.stderr, 'banned/isolated'
            continue

        if verbose: print >> sys.stderr, 'GOOD!'
        accepted.append(user_id)

        if len(accepted) >= testers_n:
            break

    if verbose: print >> sys.stderr, 'TOTAL', len(accepted)
    print ','.join(map(str, accepted))
