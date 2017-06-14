#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# load some standard Python libraries
import sys, time, requests, getopt, traceback, random, re, functools
import SpinConfig, SpinUserDB, SpinS3, SpinJSON, SpinParallel, SpinLog
import SpinNoSQL, SpinNoSQLLog
import SpinSingletonProcess
import ControlAPI
import Notification2

# load gamedata
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

retain_re = re.compile('^retain_([0-9]+)h(_incentive)?$')

# skip users last modified a long time ago
MAX_MTIME_AGE = 8*86400 # 8+ days

# skip users last modified fewer than this many seconds ago
MIN_MTIME_AGE = 60*60 # 60min

# process batches of this many users at once
BATCH_SIZE = 100

time_now = int(time.time())

def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty

def check_harv_full(pcache, n2_class, player, config):
    if n2_class is Notification2.USER_NEW:
        return None, None, None # not for tutorial-incomplete newbies

    total_harvesters = 0
    full_harvesters = 0

    for obj in player['my_base']:
        if obj['spec'] not in gamedata['buildings']: continue
        spec = gamedata['buildings'][obj['spec']]
        if 'production_capacity' not in spec: continue
        total_harvesters += 1
        contents = obj.get('contents',0)
        if 'produce_start_time' in obj and 'produce_rate' in obj:
            contents += int(obj['produce_rate']*(time_now - obj['produce_start_time'])/3600.0)
        cap = get_leveled_quantity(spec['production_capacity'], obj.get('level',1))
        if contents >= cap:
            full_harvesters += 1

    if full_harvesters < total_harvesters or total_harvesters < 1:
        #print 'not all harvesters are full'
        return None, None, None

    return 'harv_full', '', None

def check_upgrade_complete(ref, building_type, specific_level, pcache, n2_class, player, config):
    if n2_class is Notification2.USER_NEW:
        return None, None, None # not for tutorial-incomplete newbies

    for obj in player['my_base']:
        if obj['spec'] not in gamedata['buildings']: continue
        if building_type != 'ALL' and obj['spec'] != building_type: continue
        if specific_level > 0 and obj.get('level',1) + 1 != specific_level: continue
        if ('upgrade_start_time' in obj) and ('upgrade_total_time' in obj) and (obj['upgrade_start_time'] > 0):
            if obj.get('upgrade_done_time',0) + (time_now - obj['upgrade_start_time']) >= obj['upgrade_total_time']:
                ui_name = gamedata['buildings'][obj['spec']]['ui_name']
                return ref, ui_name, None
    return None, None, None
def check_research_complete(pcache, n2_class, player, config):
    if n2_class is Notification2.USER_NEW:
        return None, None, None # not for tutorial-incomplete newbies

    for obj in player['my_base']:
        if obj['spec'] not in gamedata['buildings']: continue
        if ('research_item' in obj) and ('research_start_time' in obj) and ('research_total_time' in obj) and (obj['research_start_time'] > 0):
            if obj.get('research_done_time',0) + (time_now - obj['research_start_time']) >= obj['research_total_time']:
                ui_name = gamedata['tech'][obj['research_item']]['ui_name']
                return 'research_complete', ui_name, None
    return None, None, None
def check_production_complete(pcache, n2_class, player, config):
    if n2_class is Notification2.USER_NEW:
        return None, None, None # not for tutorial-incomplete newbies

    any_manuf = False
    all_complete = True
    for obj in player['my_base']:
        if obj['spec'] not in gamedata['buildings']: continue
        if ('manuf_queue' in obj) and len(obj['manuf_queue'])>0 and ('manuf_start_time' in obj) and (obj['manuf_start_time'] > 0):
            any_manuf = True
            prog = obj.get('manuf_done_time',0) + (time_now - obj['manuf_start_time'])
            total = sum([item.get('total_time',0) for item in obj['manuf_queue']])
            if prog < total:
                all_complete = False
                break
    if any_manuf and all_complete:
        return 'production_complete', '', None
    return None, None, None
def check_army_repaired(pcache, n2_class, player, config):
    if n2_class is Notification2.USER_NEW:
        return None, None, None # not for tutorial-incomplete newbies

    if 'unit_repair_queue' in player and len(player['unit_repair_queue']) > 0:
        tags = dict([(item.get('tag',0), 1) for item in player['unit_repair_queue']])
        item = player['unit_repair_queue'][-1]
        if time_now >= item['finish_time']:

            # repair queue is complete, now check if any non-queued units are damaged
            for obj in player['my_base']:
                if obj['spec'] not in gamedata['units']: continue
                if ('tag' in obj) and (obj['tag'] in tags): continue # accounted for in repair queue
                if ('hp_ratio' in obj) and (obj['hp_ratio'] < 1):
                    return None, None, None # damaged
                spec = gamedata['units'][obj['spec']]
                max_hp = get_leveled_quantity(spec['max_hp'], obj.get('level',1))
                if ('hp' in obj) and (obj['hp'] < max_hp):
                    return None, None, None # damaged
            return 'army_repaired', '', None
    return None, None, None

def check_retain(pcache, n2_class, player, config):
    num_hours = int(retain_re.match(config['ref']).group(1))

    if n2_class is Notification2.USER_NEW and num_hours > 48:
        # FB best practice: don't send >48h retention notification to non-tutorial-completers
        return None, None, None

    if num_hours <= 24:
        if player['history'].get('notification2:login_incentive_expiring:last_time',-1) > pcache.get('last_logout_time',-1):
            return None, None, None # login_incentive_expiring replaces the <24h retention notification, if sent

    # inhibit if this num_hours notification was already sent (non-incentive or _incentive variant)
    for key in ('retain_%dh' % num_hours, 'retain_%dh_incentive' % num_hours):
        if player['history'].get('notification2:'+key+':last_time',-1) > pcache.get('last_logout_time',-1):
            return None, None, None # already sent this one since last logout

    if (time_now - pcache.get('last_logout_time',-1)) >= num_hours*3600:
        return config['ref'], '', None # send it

    return None, None, None

def check_login_incentive_expiring(pcache, n2_class, player, config):
    aura_list = player.get('player_auras', [])
    for aura in aura_list:
        if aura['spec'] == 'login_incentive_ready' and \
           time_now >= aura.get('start_time',-1) and \
           time_now < aura['end_time'] and \
           time_now >= aura['end_time'] - 4 * 3600: # XXX A/B test how soon to start sending these
            ui_time_togo = '%.1f hrs' % ((aura['end_time']-time_now)/3600.0)
            return config['ref'], ui_time_togo, None
    return None, None, None

def check_fishing_complete(pcache, n2_class, player, config):
    if n2_class is Notification2.USER_NEW:
        return None, None, None # not for tutorial-incomplete newbies

    prefs = player.get('player_preferences', {})
    if type(prefs) is dict and (not prefs.get('enable_fishing_notifications',True)): return None, None, None
    for obj in player['my_base']:
        spec = gamedata['buildings'].get(obj['spec'], None)
        if not spec: continue
        if 'fishing' not in spec.get('crafting_categories',[]): continue
        if ('crafting' in obj) and len(obj['crafting'].get('queue',[]))>0:
            for bus in obj['crafting']['queue']:
                if bus.get('notified',0): continue
                MIN_TIME = 4*3600 # dispatches that take shorter than this do not cause a notification
                if bus.get('start_time',-1) >= 0 and bus.get('total_time',-1) > 0 and bus['total_time'] >= MIN_TIME:
                    prog = bus.get('done_time',0) + (time_now - bus['start_time'])
                    if prog >= bus['total_time']:
                        return 'fishing_complete', gamedata['crafting']['recipes'][bus['craft']['recipe']]['ui_name'], bus
    return None, None, None

# functions to check if a notification applies
CHECKERS = {
    'harv_full': check_harv_full,
    'townhall_L3_upgrade_complete': functools.partial(check_upgrade_complete, 'townhall_L3_upgrade_complete', gamedata['townhall'], 3),
    'upgrade_complete': functools.partial(check_upgrade_complete, 'upgrade_complete', 'ALL', -1),
    'research_complete': check_research_complete,
    'production_complete': check_production_complete,
    'army_repaired': check_army_repaired,
    'fishing_complete': check_fishing_complete,
    'login_incentive_expiring': check_login_incentive_expiring,
    'retain_': check_retain,
    }

# list of (-priority, ref, check_func) sorted in descending priority (increasing negative priority) order
CHECKERS_BY_PRIORITY = []

for key, val in gamedata['fb_notifications']['notifications'].iteritems():
    if val.get('enable_elder', True) or val.get('enable_newbie', True):
        match = retain_re.match(key)
        if match:
            CHECKERS_BY_PRIORITY.append((-val['priority'], key, CHECKERS['retain_']))
            continue
        elif key in CHECKERS: # regular checker
            CHECKERS_BY_PRIORITY.append((-val['priority'], key, CHECKERS[key]))

CHECKERS_BY_PRIORITY.sort()

class Sender(object):
    def __init__(self, db_client, lock_client, dry_run = True, msg_fd = None):
        self.db_client = db_client
        self.lock_client = lock_client
        self.dry_run = dry_run
        self.seen = 0
        self.eligible = 0
        self.sent = 0
        self.sent_now = 0
        self.msg_fd = msg_fd
        self.fb_notifications_log = SpinLog.FBNotificationsLogFilter(SpinNoSQLLog.NoSQLJSONLog(self.db_client, 'log_fb_notifications'))
        self.enable_fb = SpinConfig.config.get('enable_facebook', False)
        self.enable_bh = SpinConfig.config.get('enable_battlehouse', False)
        self.active_platforms = []
        if self.enable_fb: self.active_platforms.append('fb')
        if self.enable_bh: self.active_platforms.append('bh')
        self.requests_session = requests.Session()

    # pass in the player_cache entry
    def notify_user(self, user_id, pcache, index = -1, total_count = -1, only_frame_platform = None, test_mode = False):
        global time_now

        self.seen += 1

        frame_platform = pcache.get('frame_platform',None)
        # for testing purposes, skip everything not on this platform
        if only_frame_platform is not None and frame_platform != only_frame_platform:
            return

        print >> self.msg_fd, '(%6.2f%%) %7d' % (100*float(index+1)/float(total_count), user_id),

        #print >> self.msg_fd, 'PCACHE:', repr(pcache)

        if pcache.get('social_id') in (None, -1, '-1', 'ai'): # skip AIs
            print >> self.msg_fd, '(player_cache says) AI player'
            return

        if (not test_mode) and frame_platform not in self.active_platforms:
            print >> self.msg_fd, '(player_cache says) frame_platform is not active'
            return

        platform_id = None
        if 'social_id' in pcache and pcache['social_id'].startswith(frame_platform):
            platform_id = pcache['social_id'][2:]
        else:
            print >> self.msg_fd, '(player_cache says) social_id not available for platform %s!' % frame_platform
            return

        if (not platform_id) or (len(platform_id) < 3):
            print >> self.msg_fd, '(player_cache says) invalid platform_id: %r' % platform_id
            return

        if pcache.get('LOCK_STATE',0) != 0:
            print >> self.msg_fd, '(player_cache says) player is logged in or being modified right now'
            return

        if frame_platform == 'fb' and pcache.get('uninstalled',0):
            print >> self.msg_fd, '(player_cache says) player uninstalled from FB'
            return

        if not pcache.get('enable_fb_notifications', True):
            print >> self.msg_fd, '(player_cache says) player turned off FB notifications'
            return

        # do not perform country tier exclusion if player is a payer or high level
        apply_exclusions = True
        if 'force_eligible_money_spent' in gamedata['fb_notifications']:
            if pcache.get('money_spent',0) >= gamedata['fb_notifications']['force_eligible_money_spent']:
                apply_exclusions = False
        if 'force_eligible_player_level' in gamedata['fb_notifications']:
            if pcache.get('player_level',0) >= gamedata['fb_notifications']['force_eligible_player_level']:
                apply_exclusions = False

        if apply_exclusions:
            # country tier exclusion
            if 'eligible_country_tiers' in gamedata['fb_notifications']:
                eligible_country_tiers = gamedata['fb_notifications']['eligible_country_tiers']
                if 'country' in pcache:
                    country_tier = SpinConfig.country_tier_map.get(pcache['country'], 4)
                    if country_tier not in eligible_country_tiers:
                        print >> self.msg_fd, '(player_cache says) not in eligible country tier'
                        return

        last_logout_time = pcache.get('last_logout_time', -1)
        if last_logout_time < 0:
            print >> self.msg_fd, '(player_cache says) no last_logout_time'
            return
        if (not test_mode) and (time_now - last_logout_time) < MIN_MTIME_AGE:
            print >> self.msg_fd, '(player_cache says) player logged out less than %d minutes ago' % (MIN_MTIME_AGE/60)
            return

#        if ((time_now - pcache.get('last_mtime',-1)) < MIN_MTIME_AGE):
#            print >> self.msg_fd, '(player_cache says) player cache data was modified less than %d minutes ago' % (MIN_MTIME_AGE/60)
#            return

        try:
            player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))

        except SpinS3.S3404Exception:
            # missing data - might be due to an S3 failure
            print >> self.msg_fd, '(playerDB data missing)'
            return

        time_now = int(time.time()) # update time after possible long download

        if (not test_mode) and (player['abtests'].get('T330_notification2', None) != "on") and gamedata['game_id'] not in ('dv','fs','bfm'):
            print >> self.msg_fd, '(player says) is not in T330_notification2, skipping'
            return

        n2_class = Notification2.get_user_class(player['history'], gamedata['townhall'])

        # note: trust pcache on timezone - it's not really critical
        timezone = pcache.get('timezone', Notification2.DEFAULT_TIMEZONE)

        if (not test_mode) and (last_logout_time < 0 or (time_now - last_logout_time) < MIN_MTIME_AGE):
            print >> self.msg_fd, '(player says) played less than %d mins ago' % (MIN_MTIME_AGE/60)
            return

        ref = None
        replace_s = ''
        checker_state = None

        for prio, key, func in CHECKERS_BY_PRIORITY:
            config = gamedata['fb_notifications']['notifications'].get(key, None)
            if not config: continue

            if frame_platform == 'bh' and 'email' not in config: continue
            if player.get('creation_time',-1) < config.get('min_account_creation_time',-1): continue

            can_send, reason = Notification2.can_send(time_now, timezone,
                                                      Notification2.ref_to_stream(key), key, player['history'],
                                                      player['cooldowns'], n2_class)
            if not can_send:
                if test_mode and key == 'login_incentive_expiring':
                    can_send = True
                    ref, replace_s, checker_state = config['ref'], '1.0 hrs', None
                    break
                #print >> self.msg_fd, '%s: Notification2.can_send False because %s...' % (key, reason)
                continue

            #print >> self.msg_fd, 'checking %s...' % key
            ref, replace_s, checker_state = func(pcache, n2_class, player, config)
            if ref: break

        if not ref:
            print >> self.msg_fd, 'nothing to notify about'
            return

        self.eligible += 1

        config = gamedata['fb_notifications']['notifications'][ref]
        ui_name = config['ui_name']
        ref_suffix = ''
        if type(ui_name) is dict: # A/B test
            key_list = sorted(ui_name.keys())
            key = key_list[random.randint(0,len(key_list)-1)]
            assert key.startswith('ui_')
            ui_name = ui_name[key]
            ref_suffix += '_'+key[3:]
        text = ui_name.replace('%s', replace_s)
        print >> self.msg_fd, 'eligible for: %s_%s%s "%s"...' % (config['ref'], n2_class, ref_suffix, text)

        if not self.dry_run:
            try:
                response = ControlAPI.CONTROLAPI({'method': 'send_notification', 'user_id': user_id,
                                                  'text': text.encode('utf-8'),
                                                  'ref_suffix': ref_suffix,
                                                  'config': config['ref']},
                                                 'send_player_notifications', max_tries = 1)
                print >> self.msg_fd, 'Sent! Response:', response

            except ControlAPI.ControlAPIException as e:
                print >> self.msg_fd, 'ControlAPIException', e
            except ControlAPI.ControlAPIGameException as e:
                print >> self.msg_fd, 'ControlAPIGameException', e

        # RETURN HITS WILL LOOK LIKE THIS:
        # Facebook:
        # https://apps.facebook.com/marsfrontier/?fb_source=notification&fb_ref=harv_full&ref=notif&notif_t=app_notification
        # Battlehouse:
        # https://www.battlehouse.com/play/firestrike?bh_source=notification&ref=REF&fb_ref=REF_n

        self.sent += 1
        self.sent_now += 1

    def finish(self):
        print >> self.msg_fd, 'saw', self.seen, 'players,', self.eligible, 'eligible,', self.sent, 'sent,', self.sent_now, 'sent this run'

def connect_to_db():
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'retention_newbie.py')
    nosql_client.set_time(time_now)
    return nosql_client

class NullFD(object):
    def write(self, stuff): pass


def run_batch(batch_num, batch, total_count, limit, dry_run, verbose, only_frame_platform, test_mode):
    msg_fd = sys.stderr if verbose else NullFD()

    # reconnect to DB to avoid subprocesses sharing conenctions
    db_client = connect_to_db()
    if dry_run:
        lock_client = None
    else:
        lock_client = db_client

    sender = Sender(db_client, lock_client, dry_run = dry_run, msg_fd = msg_fd)
    pcache_list = db_client.player_cache_lookup_batch(batch, fields = ['tutorial_complete',
                                                                       'social_id','frame_platform',
                                                                       'country', 'money_spent', 'player_level',
                                                                       'last_logout_time',
                                                                       'last_mtime', 'uninstalled',
                                                                       'enable_fb_notifications',
                                                                       'last_fb_notification_time',
                                                                       'LOCK_STATE'])
    for i in xrange(len(batch)):
        try:
            sender.notify_user(batch[i], pcache_list[i], index = BATCH_SIZE*batch_num + i, total_count = total_count, only_frame_platform = only_frame_platform, test_mode = test_mode)
        except KeyboardInterrupt:
            raise # allow Ctrl-C to abort
        except Exception as e:
            sys.stderr.write('error processing user %d: %r\n%s\n'% (batch[i], e, traceback.format_exc()))

        if limit >= 0 and sender.sent_now >= limit:
            print >> msg_fd, 'limit reached'
            break

    print >> msg_fd, 'batch %d done' % batch_num
    sender.finish()

def my_slave(input):
    run_batch(input['batch_num'], input['batch'], input['total_count'], input['limit'], input['dry_run'], input['verbose'], input['only_frame_platform'], input['test_mode'])

# main program
if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(my_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['dry-run','test', 'limit=', 'parallel=', 'quiet', 'frame-platform='])
    dry_run = False
    test_mode = False
    limit = -1
    parallel = -1
    verbose = True
    only_frame_platform = None

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '--test':
            test_mode = True
        elif key == '--limit':
            limit = int(val)
        elif key == '--parallel':
            parallel = int(val)
        elif key == '--quiet':
            verbose = False
        elif key == '--frame-platform':
            only_frame_platform = val

    with SpinSingletonProcess.SingletonProcess('send-player-notifications-%s' % (SpinConfig.config['game_id'],)):

        db_client = connect_to_db()

        id_list = []
        if test_mode:
            id_list += [1111, 1112, 1114, 1115, 1179934, 1179935]

        if not test_mode:
            if verbose: print 'querying player_cache...'
            id_list += db_client.player_cache_query_mtime_or_ctime_between([[time_now - MAX_MTIME_AGE, time_now - MIN_MTIME_AGE]],
                                                                           [],
                                                                           require_tutorial_complete = False)

        id_list.sort(reverse=True)
        total_count = len(id_list)

        batches = [id_list[i:i+BATCH_SIZE] for i in xrange(0, len(id_list), BATCH_SIZE)]

        if verbose: print 'player_cache_query returned %d users -> %d batches' % (total_count, len(batches))

        if parallel <= 1:
            for batch_num in xrange(len(batches)):
                run_batch(batch_num, batches[batch_num], total_count, limit, dry_run, verbose, only_frame_platform, test_mode)
        else:
            SpinParallel.go([{'batch_num':batch_num,
                              'batch':batches[batch_num],
                              'total_count':total_count,
                              'limit':limit, 'verbose':verbose, 'only_frame_platform': only_frame_platform,
                              'test_mode': test_mode,
                              'dry_run':dry_run} for batch_num in xrange(len(batches))],
                            [sys.argv[0], '--slave'],
                            on_error = 'break', nprocs=parallel, verbose = False)

