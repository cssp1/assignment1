#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# manually send reacquisition Facebook Notifications to a list of users

import sys, time, random, urllib, urllib2, getopt
import SpinConfig, SpinUserDB, SpinJSON, SpinLog
import SpinNoSQL, SpinNoSQLLog, SpinETL
import SpinFacebook

time_now = int(time.time())

# main program
if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['dry-run', 'limit='])
    dry_run = False
    limit = -1
    game_id = SpinConfig.game()

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '-g':
            game_id = val
        elif key == '--limit':
            limit = int(val)

    db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'retention_incentive.py')
    db_client.set_time(time_now)
    fb_notifications_log = SpinLog.FBNotificationsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fb_notifications'))

    infile = open(args[0]) if args[0] != '-' else sys.stdin

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    seen = 0
    sent = 0

    for line in infile.xreadlines():
        if not line: break
        user_id = int(line)

        print user_id,
        sys.stdout.flush()

        player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))
        user = SpinJSON.loads(SpinUserDB.driver.sync_download_user(user_id))
        seen += 1

        if 0:
            pcache = db_client.player_cache_lookup_batch([user_id], fields = ['tutorial_complete',
                                                                              'facebook_id','social_id','frame_platform',
                                                                              'last_login_time','last_mtime',
                                                                          'last_fb_notification_time', 'LOCK_STATE'])[0]
            if not pcache:
                print 'no pcache entry!'
                continue
            if 'facebook_id' not in pcache or len(pcache['facebook_id']) <= 2:
                print 'invalid facebook_id!'
                continue
            facebook_id = pcache['facebook_id']
        else:
            if 'facebook_id' not in user:
                print 'user is on frame_platform', user.get('frame_platform', 'unknown')
                continue
            facebook_id = user['facebook_id']

        ref = 'reacq'
        ref_suffix = ''
        config = gamedata['fb_notifications']['notifications'][ref]
        ui_name = config['ui_name']
        if type(ui_name) is dict: # A/B test
            key_list = sorted(ui_name.keys())
            key = key_list[random.randint(0,len(key_list)-1)]
            assert key.startswith('ui_')
            ui_name = ui_name[key]
            ref_suffix += '_'+key[3:]
        text = ui_name

        history_key = 'fb_notification:'+ref+':sent'
        if player['history'].get(history_key,0) > 0:
            print 'already sent!'
            continue

        player['history'][history_key] = player['history'].get(history_key,0) + 1

        if not dry_run:
            generation = player.get('generation',0)
            if db_client.player_lock_acquire_attack(user_id, generation) < 0:
                print 'cannot write, player is logged in'
                continue
            try:
                player['generation'] = generation+1
                SpinUserDB.driver.sync_write_player(user_id, SpinJSON.dumps(player, pretty=True, newline=True, double_precision=5))
                print 'written!'

                if True:
                    postdata = urllib.urlencode({'access_token': SpinConfig.config['facebook_app_access_token'],
                                                 'href': '',
                                                 'ref': config['ref'] + ref_suffix,
                                                 'template': text.encode('utf-8') })
                    request = urllib2.Request(SpinFacebook.versioned_graph_endpoint('notification', str(facebook_id)+'/notifications'), data = postdata)
                    request.get_method = lambda: 'POST'
                    success = False
                    response = None
                    try:
                        conn = urllib2.urlopen(request)
                        response = conn.read()
                        print 'notification sent!'
                        success = True

                    except urllib2.HTTPError as e:
                        print 'FB API error', e, e.read()

                    if success:
                        sent += 1
                        fb_notifications_log.event(time_now, {'user_id': user_id,
                                                              'event_name': '7130_fb_notification_sent', 'code':7130,
                                                              'sum': SpinETL.get_denormalized_summary_props(gamedata, player, user, 'brief'),
                                                              'ref': config['ref'],
                                                              'fb_ref': config['ref'] + ref_suffix})

            finally:
                db_client.player_lock_release(user_id, player['generation'], 2)
        else:
            print '(would send, but this is a dry run)'

        if limit > 0 and sent >= limit:
            print 'hit send limit, stopping!'
            break

    print 'saw', seen, 'players in cohort,', sent, 'notifications sent'
