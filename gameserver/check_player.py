#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# command-line customer support tool

import SpinUserDB
import SpinNoSQL
import SpinConfig
import SpinJSON
import SpinS3

# load some standard Python libraries
import sys, time, getopt, string
import requests, urllib, socket

time_now = int(time.time())

# convert a floating-point number of seconds into a string like '10d 4h 5m 10s'
# 'limit' limits how many "words" are in the result
time_unit_table = {
    'd': 'Day', 'h': 'Hour', 'm': 'Min', 's': 'Sec'
}

def do_pretty_print_time_unit(qty, abbrev, spell_it):
    if spell_it:
        u = time_unit_table[abbrev]
        if qty != 1:
            u = u + 's'
        return ('%d' % qty) + ' ' + u
    return ('%d' % qty) + abbrev

def pretty_print_time(sec, limit = 99, spell_units = False):
    if sec < 1: # includes negative
        return '0'

    ret = []
    show_seconds = True

    if sec >= 24*60*60:
        days = sec//(24*60*60)
        ret.append(do_pretty_print_time_unit(days, 'd', spell_units))
        sec -= days * (24*60*60);
        show_seconds = False

    if sec >= (60*60):
        hours = sec//(60*60)
        ret.append(do_pretty_print_time_unit(hours, 'h', spell_units))
        sec -= hours * (60*60)

    if sec >= 60:
        mins = sec // 60;
        ret.append(do_pretty_print_time_unit(mins, 'm', spell_units))
        sec -= mins * 60

    if sec >= 1 and show_seconds:
        secs = sec // 1;
        ret.append(do_pretty_print_time_unit(secs, 's', spell_units))

    ret = ret[0:limit]
    return (', ' if spell_units else ' ').join(ret)

# display end time for auras/cooldowns
def ui_end_time(end_time, time_now, negate = False):
    if end_time > 0:
        if end_time > time_now:
            ui_dur =  '%.1f hrs' % ((end_time - time_now)/3600.0)
            if negate:
                return 'in '+ui_dur
            else:
                return 'for '+ui_dur
        else: return None # expired
    else:
        return 'Never' if negate else 'Permanently'

def check_bloat(input, min_size = 1024, print_max = 20):
    sizes = []
    for key, val in input.iteritems():
        slen = len(SpinJSON.dumps(val, pretty=True))
        if slen > min_size:
            sizes.append([key, slen])
    sizes = sorted(sizes, key = lambda x: -x[1])
    for key, slen in sizes[0:print_max]:
        print '%-50s %-10.2f kB' % (key, slen/1024.0)

def do_CONTROLAPI(args):
    host = SpinConfig.config['proxyserver'].get('external_listen_host','localhost')
    proto = 'http' if host in ('localhost', socket.gethostname()) else 'https'
    url = '%s://%s:%d/CONTROLAPI' % (proto, host, SpinConfig.config['proxyserver']['external_http_port' if proto == 'http' else 'external_ssl_port'])
    args['spin_user'] = 'check_player.py'
    args['secret'] = SpinConfig.config['proxy_api_secret']
    response = requests.post(url+'?'+urllib.urlencode(args))
    assert response.status_code == 200
    ret = SpinJSON.loads(response.text)
    if 'error' in ret:
        raise Exception('CONTROLAPI error: %r' % ret['error'])
    return ret['result']

# main program
if __name__ == '__main__':
    import codecs
    sys.stdout = codecs.getwriter('utf8')(sys.stdout)

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['bloat', 'abtests', 'get', 'put', 'get-user', 'put-user', 'stdio', 'stdin', 'stdout',
                                                      'ban', 'ban-days=', 'unban', 'gag', 'ungag', 'isolate', 'unisolate', 'make-chat-mod', 'unmake-chat-mod',
                                                      'db-host=', 'db-port=', 'db-secret=', 'live',
                                                      's3', 's3-key-file=', 's3-userdb-bucket=', 's3-playerdb-bucket=',
                                                      'user-id=', 'facebook-id=', 'game-id=',
                                                      'give-alloy=', 'give-protection-time=', 'give-item=', 'melt-hours=', 'item-stack=', 'item-log-reason=',
                                                      'give-item-subject=', 'give-item-body=',
                                                      'send-message', 'message-subject=', 'message-body=', 'message-sender=', 'message-expire-time=', 'message-expire-in=',
                                                       ])


    fmt = '%-22s %-50s'
    game_id = SpinConfig.config['game_id']
    user_id = None
    facebook_id = None
    bloat = False
    abtests = False
    db_host = None
    db_port = None
    db_secret = None
    use_controlapi = False
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
    give_item = None
    send_message = False
    message_sender = 'Customer Support'
    message_subject = ''
    message_body = ''
    message_expire_time = -1
    item_stack = 1
    item_melt_hours = -1
    item_log_reason = None

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
        elif key == '--ban':
            do_ban = True
        elif key == '--ban-days':
            do_ban = True
            ban_days = int(val)
        elif key == '--unban':
            do_unban = True
        elif key == '--isolate':
            do_isolate = True
        elif key == '--unisolate':
            do_unisolate = True
        elif key == '--gag':
            do_gag = True
        elif key == '--ungag':
            do_ungag = True
        elif key == '--make-chat-mod':
            do_make_chat_mod = True
        elif key == '--unmake-chat-mod':
            do_unmake_chat_mod = True
        elif key == '--db-host':
            db_host = val
        elif key == '--db-port':
            db_port = int(val)
        elif key == '--db-secret':
            db_secret = val
        elif key == '--live':
            use_controlapi = True
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
        elif key == '--game-id' or key == '-g':
            game_id = val
        elif key == '--give-alloy':
            # give_alloy = int(val) # obsolete
            give_item = 'gamebucks'
            item_stack = max(1, int(val))
            if not message_subject: message_subject = 'Special Item'
            if not message_body: message_body = 'Commander, the Customer Support team sent us a special item.'
        elif key == '--give-protection-time':
            give_protection_time = 3600*int(val)
        elif key == '--give-item':
            give_item = val
            if not message_subject: message_subject = 'Special Item'
            if not message_body: message_body = 'Commander, the Customer Support team sent us a special item.'
        elif key == '--melt-hours':
            item_melt_hours = max(-1, int(val))
        elif key == '--item-stack':
            item_stack = max(1, int(val))
        elif key == '--give-item-subject' or key == '--message-subject':
            message_subject = val
        elif key == '--give-item-body' or key == '--message-body':
            message_body = val
        elif key == '--item-log-reason':
            item_log_reason = val
        elif key == '--message-sender':
            message_sender = val
        elif key == '--message-expire-time':
            message_expire_time = max(-1, int(val))
        elif key == '--message-expire-in':
            message_expire_time = time_now + int(val)
        elif key == '--send-message':
            send_message = True

    if len(args) > 0:
        user_id = int(args[0])

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = SpinConfig.game(game_id))))

    # hack - MF's gamebucks item is called "alloy"
    if give_item == 'gamebucks' and SpinConfig.game(game_id) == 'mf': give_item = 'alloy'

    if give_item and (give_item not in gamedata['items']):
        print 'error! item "%s" not found in gamedata.items' % give_item
        sys.exit(1)

    if user_id is None and facebook_id is None:
        print 'usage: %s [options]' % sys.argv[0]
        print 'options:'
        print '    --user-id ID        choose player by game player ID'
        print '    --facebook-id ID    choose player by Facebook user ID'
        print ''
        print '    --game-id ID        look up users for game ID (either mf or tr)'
        print ''
        print '    --live                       use CustomerSupport API where applicable instead of manipulating backing store'
        print '    --s3                         force usage of S3 userdb/playerdb'
        print '    --s3-key-file FILE           get S3 credentials from this file'
        print '    --s3-userdb-bucket BUCKET    specify S3 bucket used for userdb'
        print '    --s3-playerdb-bucket BUCKET  specify S3 bucket used for playerdb'
        print
        print '    --abtests           display player\'s A/B test membership'
        print '    --bloat             display space usage of db fields'
        print '    --get               retrieve playerdb to local disk file (USERID_GAMEID.txt)'
        print '    --put               overwrite playerdb with local disk file (USERID_GAMEID.txt)'
        print '    --get-user          retrieve userdb to local disk file (USERID.txt)'
        print '    --put-user          overwrite userdb with local disk file (USERID.txt)'
        print '    --stdio             get/put I/O to stdio rather than disk files'
        print
        print 'MODIFICATIONS:  (requires S3 key with write access, and does not work if player is logged in)'
        print '    --give-alloy NUM              add NUM alloy'
        print '    --give-protection-time NUM    add NUM hours of protection time'
        print '    --give-item ITEM              give item ITEM (where ITEM is an entry in items.json)'
        print '    --item-stack NUN              give NUM copies of the item (default 1)'
        print '    --melt-hours HOURS            given item will melt in HOURS hours (default 48)'
        print '    --ban                         ban player (for two years)'
        print '    --ban-days NUM                make ban last NUM days (implies --ban)'
        print '    --unban                       unban player'
        print '    --isolate                     enable "cheater" isolated PvP mode (player cannot PvP except against other cheaters)'
        print '    --unisolate                   disable isolated PvP mode'
        print '    --gag                         do not allow player to talk in chat'
        print '    --ungag                       allow player to chat again'
        print '    --make-chat-mod               allow player to moderate chat (mute/unmute other players)'
        print '    --unmake-chat-mod             remove permission to moderate chat'
        print '    --send-message --message-sender SENDER --message-subject SUBJECT --message-body BODY send an in-game message'

        sys.exit(1)

    need_lock = (give_alloy > 0) or (give_protection_time > 0) or do_put or do_ban or do_unban or do_gag or do_ungag or do_make_chat_mod or do_unmake_chat_mod or do_isolate or do_unisolate or do_put_user
    locked = False

    db_client = None

    if (user_id is None and facebook_id) or need_lock or give_item or send_message:
        # need DB client
        db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
        db_client.set_time(time_now)

    if force_s3:
        driver = SpinUserDB.S3Driver(game_id = game_id, key_file = s3_key_file,
                                     userdb_bucket = s3_userdb_bucket,
                                     playerdb_bucket = s3_playerdb_bucket)
    else:
        driver = SpinUserDB.driver

    if user_id is None and facebook_id:
        print 'looking up user by Facebook ID...'
        user_id = db_client.facebook_id_to_spinpunch_single(facebook_id, False)
        if user_id < 0:
            raise Exception('No user found for this Facebook ID')

    try:
        user_filename = '%d.txt' % (user_id)
        player_filename = '%d_%s.txt' % (user_id, game_id)

        if do_put:
            player = SpinJSON.load(open(player_filename))
        else:
            try:
                if use_controlapi:
                    # requesting "stringify" is faster in the logged-out case (since the server doesn't parse/unparse) and probably same speed in logged-in case
                    player = SpinJSON.loads(do_CONTROLAPI({'method':'get_raw_player', 'stringify': '1', 'user_id': user_id}))
                else:
                    player = SpinJSON.loads(driver.sync_download_player(user_id))
            except Exception as e:
                print 'Error: Unable to access playerdb for %s player ID %d' % (gamedata['strings']['game_name'], user_id), '(%s)' % repr(e)
                print 'Possible reasons for this error:'
                print ' - Did you choose the right game? (-g GAME_ID on command line)'
                print ' - The player ID might not exist in this game'
                print ' - The player might not have logged out of the game for the first time yet'
                print ' - The S3 settings passed on the command line or in config.json may be incorrect'
                sys.exit(1)

        if do_put_user:
            user = SpinJSON.load(open(user_filename))
        else:
            if use_controlapi:
                user = SpinJSON.loads(do_CONTROLAPI({'method': 'get_raw_user', 'stringify': '1', 'user_id': user_id}))
            else:
                try:
                    user = SpinJSON.loads(driver.sync_download_user(user_id))
                # October 2015 server bug caused some players to get written out without userdb entry. Ignore this.
                except SpinS3.S3404Exception:
                    user = {}

        if do_get:
            SpinJSON.dump(player, sys.stdout if use_stdio else open(player_filename,'w'), pretty=True)
            print 'dumped player to %s' % player_filename

        if do_get_user:
            SpinJSON.dump(user, sys.stdout if use_stdio else open(user_filename,'w'), pretty=True)
            print 'dumped user to %s' % user_filename

        if need_lock:
            generation = player.get('generation', 0)
            if db_client.player_lock_acquire_attack(user_id, generation) < 0:
                print 'cannot overwrite player state while player is logged in, try back later! (gen %d)' % generation
                sys.exit(1)
            else:
                locked = True

        if 'creation_time' in player:
            creat = player['creation_time']
        elif 'account_creation_time' in user:
            creat = user['account_creation_time']
        else:
            creat = -1

        print fmt % ('User ID:', str(user_id))
        if player.get('alias', None):
            print fmt % ('Alias (Call Sign):', player['alias'])

        if user.get('frame_platform', None):
            print fmt % ('Frame Platform:', {'fb':'Facebook','kg':'Kongregate','ag':'Armor Games'}[user['frame_platform']])

        if user.get('ag_id', None):
            print fmt % ('Armor Games ID:', '"'+str(user['ag_id'])+'"')
        if user.get('ag_username', None):
            print fmt % ('Armor Games Name:', '"'+str(user['ag_username'])+'"')

        if user.get('kg_id', None):
            print fmt % ('Kongregate ID:', '"'+str(user['kg_id'])+'"')
        if user.get('kg_username', None):
            print fmt % ('Kongregate Name:', '"'+str(user['kg_username'])+'"')

        if user.get('facebook_id', None):
            print fmt % ('Facebook ID:', '"'+str(user['facebook_id'])+'"')
        if user.get('facebook_name', None):
            print fmt % ('Facebook Name:', user['facebook_name'])


        print fmt % ('Level:', str(player['resources']['player_level']))
        print fmt % ('CC Level:', str(player['history'].get(gamedata['townhall']+'_level',1)))

        def pretty_spend(spend): return '$%0.2f' % spend if (spend > 0) else 'ZERO'

        spend = player['history'].get('money_spent',0)
        print fmt % ('Receipts:', pretty_spend(spend))

        if creat > 0:
            spend_lastN = 0
            LIMIT = 30*24*60*60
            for sage, amt in player['history'].get('money_spent_at_time',{}).iteritems():
                if time_now - (int(sage)+creat) < LIMIT:
                    spend_lastN += amt
            print fmt % ('Receipts Last 30d:', pretty_spend(spend_lastN))

        refunds = player['history'].get('money_refunded',0)
        if refunds > 0:
            print fmt % ('REFUNDS:', pretty_spend(refunds))

        print fmt % ('Alloy balance:', str(player['resources'].get('gamebucks',0)))

        print fmt % ('Email', user.get('facebook_profile',{}).get('email', '-'))

        if creat > 0:
            age = time_now - creat
            creat_str = time.strftime('%a, %d %b %Y %H:%M:%S UTC', time.gmtime(creat))
            print fmt % ('Acct age:', '%0.1f days (created %s)' % (float(age)/(24*60*60), creat_str))
        else:
            print fmt % ('Acct age:', 'UNKNOWN')

        country = user.get('country', 'unknown')
        tier = SpinConfig.country_tier_map.get(country, 4)
        price_region = SpinConfig.price_region_map.get(country, 'unknown')
        print fmt % ('Country:', ('"%s" (tier %d region %s)' % (country, tier, price_region)))

        if 'acquisition_campaign' in user:
            print fmt % ('Acq. campaign:', user['acquisition_campaign'])
        if 'acquisition_type' in user:
            print fmt % ('Acq. type:', user['acquisition_type'])

        if player.get('facebook_permissions',None):
            print fmt % ('Facebook perms:', string.join(player['facebook_permissions'],','))

        if 'last_login_ip' in user:
            print fmt % ('Last IP:', user['last_login_ip'])

        if 'browser_os' in user and 'browser_name' in user and 'browser_version' in user:
            print fmt % ('Browser:', '%s %s (%s)' % (user['browser_name'], user['browser_version'], user['browser_os']))

        if 'sessions' in player['history']:
            sessions = player['history']['sessions']

            LAST_DAYS = 2
            begin_time = time_now - LAST_DAYS*24*60*60
            in_count = 0
            in_time = 0
            longest = -1
            for i in xrange(len(sessions)-1, -1, -1):
                s = sessions[i]
                if s[0] < 0 or s[1] < 0: continue
                if s[1] < begin_time:
                    break

                login_time = max(begin_time, s[0])

                in_count += 1
                in_time += s[1]-login_time

                if (s[1]-s[0]) > longest: # count full session
                    longest = s[1]-s[0]

            in_hrs = float(in_time)/3600.0
            in_pct = 100.0 * in_time / float(time_now - begin_time)

            print fmt % ('Logins:', len(sessions))
            print fmt % ('Recent play:', '%.2f hrs in %d logins during last %d days: %.1f%%%s' % (in_hrs, in_count, LAST_DAYS, in_pct, ' (longest session %.2f hrs)' % (longest/3600.0) if longest>0 else ''))

        prot = 0
        if player['resources']['protection_end_time'] > time_now:
            prot = player['resources']['protection_end_time'] - time_now
        print fmt % ('Protection timer:', ('ON for %.1f hrs' % (prot/3600.0) if prot > 0 else 'off'))

        if player.get('home_region'):
            ui_region = player['home_region']
            if player['home_region'] in gamedata['regions']:
                ui_region += ' ("%s")' % gamedata['regions'][player['home_region']]['ui_name']
        else:
            ui_region = '(not on map)'
        print fmt % ('Home region:', ui_region)

        if player.get('isolate_pvp',0):
            print fmt % ('ISOLATED from making attacks against others', '')

        if player.get('banned_until',-1) > time_now:
            print fmt % ('BANNED for:', '%.1f hrs' % ( (player['banned_until']-time_now)/3600.0))
        if player.get('lockout_until', -1) > time_now:
            print fmt % ('Locked out for:', '%.1f hrs' % ( (player['lockout_until']-time_now)/3600.0))
        if player.get('login_pardoned_until', -1) > time_now:
            print fmt % ('Pardoned for:', '%.1f hrs' % ( (player['login_pardoned_until']-time_now)/3600.0))

        if user.get('chat_gagged',0):
            print fmt % ('GAGGED - player cannot talk in chat (permanently - user.chat_gagged)', '')

        for aura in player.get('player_auras',[]):
            ui_duration = ui_end_time(aura.get('end_time',-1), time_now)
            if not ui_duration: continue

            if aura['spec'] == 'chat_gagged':
                print fmt % ('GAGGED (by chat_gagged aura) - player cannot talk in chat:', ui_duration)
            elif aura['spec'] == 'region_banished' and ('tag' in aura.get('data',{})):
                print fmt % ('Banished from regions with "%s" tag:' % aura['data']['tag'], ui_duration)

        for cdname, cooldown in player.get('cooldowns', {}).iteritems():
            ui_duration = ui_end_time(cooldown.get('end',-1), time_now, negate = True)
            if not ui_duration: continue
            stack = cooldown.get('stack',1)
            if cdname == 'idle_check_violation':
                print fmt % ('Anti-refresh offender:', ('%d violation(s), expires %s' % (stack, ui_duration)))
            elif cdname == 'alt_account_violation':
                print fmt % ('Alt-account offender:', ('%d violation(s), expires %s' % (stack, ui_duration)))
            elif cdname == 'chat_abuse_violation':
                print fmt % ('Chat abuse offender:', ('%d violation(s), expires %s' % (stack, ui_duration)))

        if user.get('chat_mod',0):
            print fmt % ('Player is a chat moderator', '')
        if user.get('developer',0):
            print fmt % ('DEVELOPER account', '')
        if player.get('chat_official',0):
            print fmt % ('CHAT OFFICIAL (blue text) account', '')

        if 'idle_check' in player and len(player['idle_check'].get('history',[])) > 0:
            successes = len(filter(lambda x: x['result'] == 'success', player['idle_check']['history']))
            fails = len(filter(lambda x: x['result'] == 'fail', player['idle_check']['history']))
            ui_captcha = '%d Passes, %d Fails (%.1f%% fail rate) within last %s' % (successes, fails, (100.0*fails)/(fails+successes), pretty_print_time(time_now - player['idle_check']['history'][0]['time']))
            if fails > 0:
                ui_captcha += ' (last fail %s ago)' % pretty_print_time(time_now - max(x['time'] for x in player['idle_check']['history'] if x['result'] == 'fail'))
            print fmt % ('Anti-Bot CAPTCHA:', ui_captcha)

        if 'known_alt_accounts' in player and player['known_alt_accounts']:
            print fmt % ('Known alt accounts:', '')
            for s_other_id in sorted(player['known_alt_accounts'].iterkeys(), key = int):
                entry = player['known_alt_accounts'][s_other_id]
                if entry.get('logins',1) == 0:
                    continue # ignore
                elif entry.get('logins',1) < 0 or entry.get('ignore',False): # marked non-alt
                    print fmt % ('', 'ID: %7d, IGNORED (marked as non-alt)' % (int(s_other_id)))
                    continue
                print fmt % ('', 'ID: %7d, #Logins: %4d, Last simultanous login: %s' % (int(s_other_id), entry.get('logins',1),
                                                                         pretty_print_time(time_now - entry['last_login'], limit = 2)+' ago' if 'last_login' in entry else 'Unknown'))

        if 'customer_support' in player['history']:
            print fmt % ('Customer Support history', '')
            for entry in player['history']['customer_support']:
                if entry['method'] in ('record_alt_login', 'reset_idle_check_state'): continue # don't bother printing these
                print '    At %s by %s: %s %s' % (time.strftime('%Y%m%d %H:%M GMT', time.gmtime(entry['time'])), entry['spin_user'], entry['method'].upper(), SpinJSON.dumps(entry.get('args',{})))
                print '        Reason: %s' % entry['ui_reason']

        if bloat:
            # check for bloat
            print 'PLAYERDB BLOAT:'
            check_bloat(player)

            if 'history' in player:
                print 'HISTORY BLOAT:'
                check_bloat(player['history'])

            print 'USERDB BLOAT:'
            check_bloat(user)

        if abtests:
            tests = []
            for key, val in player.get('abtests',{}).iteritems():
                tests.append([key,val])
            tests = sorted(tests, key = lambda x: x[0])
            print 'A/B Tests:'
            for key, val in tests:
                print '    %-40s %-40s' % (key, val)

        if give_item:
            if item_melt_hours < 0:
                expire_time = -1
            else:
                expire_time = time_now + 60*60*item_melt_hours
            item = {'spec':give_item}
            if item_stack > 1:
                item['stack'] = item_stack
            if expire_time > 0:
                item['expire_time'] = expire_time

            if give_item in ('gamebucks','alloy'):
                item['undiscardable'] = 1
            if item_log_reason:
                item['log'] = item_log_reason

            msg = {'type':'mail',
                   'expire_time': expire_time,
                   'from_name': message_sender, 'to': [user_id],
                   'subject': message_subject,
                   'attachments': [item],
                   'body': message_body + ('\n\nIMPORTANT: Activate this item quickly! Its time is limited.' if expire_time > 0 else '')}
            db_client.msg_send([msg])
            print 'Gave player %dx %s' % (item_stack, give_item) + ('(will melt in %d hours)' % item_melt_hours if expire_time > 0 else '')

        elif send_message:
            msg = {'type':'mail',
                   'expire_time': message_expire_time,
                   'from_name': message_sender, 'to': [user_id],
                   'subject': message_subject,
                   'body': message_body}
            db_client.msg_send([msg])
            print 'Sent player this message:'
            print 'FROM:', message_sender
            print 'SUBJECT:', message_subject
            print 'BODY:', message_body

        if need_lock:
            if give_alloy > 0:
                balance = player['resources'].get('gamebucks',0)
                print 'OLD alloy balance:', balance
                balance += give_alloy
                print 'NEW alloy balance:', balance
                player['resources']['gamebucks'] = balance
                print 'Gave %d alloy!' % give_alloy
            if give_protection_time > 0:
                end_time = player['resources'].get('protection_end_time',-1)
                if end_time <= time_now: end_time = time_now
                player['resources']['protection_end_time'] = end_time + give_protection_time
                print 'Gave %d additional hour(s) of protection!' % (give_protection_time/3600)
            if do_ban:
                player['banned_until'] = time_now + ban_days*24*60*60
                print 'Banned player for %d days!' % ban_days
            if do_unban:
                player['banned_until'] = -1
                print 'Unbanned player!'
            if do_isolate:
                player['isolate_pvp'] = 1
                print 'Isolated player from making PvP attacks'
            if do_unisolate:
                player['isolate_pvp'] = 0
                print 'Unisolated player from making PvP attacks'
            if do_gag:
                user['chat_gagged'] = 1
                print 'Gagged user, chat disabled'
            if do_ungag:
                user['chat_gagged'] = 0
                print 'Ungagged user, chat enabled'
            if do_make_chat_mod:
                user['chat_mod'] = 1
                print 'User can now moderate chat'
            if do_unmake_chat_mod:
                del user['chat_mod']
                print 'User cannot moderate chat anymore'
            generation += 1
            player['generation'] = generation
            driver.sync_write_player(user_id, SpinJSON.dumps(player, pretty=True, newline=True, double_precision=5))
            if do_put_user or do_gag or do_ungag or do_make_chat_mod or do_unmake_chat_mod:
                driver.sync_write_user(user_id, SpinJSON.dumps(user, pretty=True, newline=True, double_precision=5))
            print 'Changes to user %d updated successfully!' % user_id
    finally:
        if locked:
            db_client.player_lock_release(user_id, generation, 2)

