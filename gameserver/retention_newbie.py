#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# load some standard Python libraries
import sys, time, requests, getopt, traceback, random, re, functools
import SpinConfig, SpinUserDB, SpinS3, SpinJSON, SpinParallel, SpinLog
import SpinNoSQL, SpinNoSQLLog, SpinETL
import SpinFacebook
import SpinSingletonProcess

# load gamedata
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

critical_re = re.compile('([0-9]+)h')
retain_re = re.compile('retain_([0-9]+)h')

# skip users last modified a long time ago
MAX_MTIME_AGE = 3*24*60*60 # 3 days

# skip users last modified fewer than this many seconds ago
MIN_MTIME_AGE = 5*60

# process batches of this many users at once
BATCH_SIZE = 100

time_now = int(time.time())

def get_leveled_quantity(qty, level):
    if type(qty) == list:
        return qty[level-1]
    return qty

def check_harv_full(pcache, player, config):
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

def check_upgrade_complete(ref, building_type, specific_level, pcache, player, config):
    for obj in player['my_base']:
        if obj['spec'] not in gamedata['buildings']: continue
        if building_type != 'ALL' and obj['spec'] != building_type: continue
        if specific_level > 0 and obj.get('level',1) + 1 != specific_level: continue
        if ('upgrade_start_time' in obj) and ('upgrade_total_time' in obj) and (obj['upgrade_start_time'] > 0):
            if obj.get('upgrade_done_time',0) + (time_now - obj['upgrade_start_time']) >= obj['upgrade_total_time']:
                ui_name = gamedata['buildings'][obj['spec']]['ui_name']
                return ref, ui_name, None
    return None, None, None
def check_research_complete(pcache, player, config):
    for obj in player['my_base']:
        if obj['spec'] not in gamedata['buildings']: continue
        if ('research_item' in obj) and ('research_start_time' in obj) and ('research_total_time' in obj) and (obj['research_start_time'] > 0):
            if obj.get('research_done_time',0) + (time_now - obj['research_start_time']) >= obj['research_total_time']:
                ui_name = gamedata['tech'][obj['research_item']]['ui_name']
                return 'research_complete', ui_name, None
    return None, None, None
def check_production_complete(pcache, player, config):
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
def check_army_repaired(pcache, player, config):
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
def check_retain(pcache, player, config):
    num_hours = int(retain_re.match(config['ref']).group(1))
    if player['history'].get('fb_notification:'+config['ref']+':last_time',-1) > pcache.get('last_login_time',-1):
        return None, None, None # already sent this one since last login
    if (time_now - pcache.get('last_login_time',-1)) >= num_hours*3600:
        return config['ref'], '', None # send it
    return None, None, None
def check_fishing_complete(pcache, player, config):
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
def finish_fishing_complete(player, bus):
    LIMIT = 2
    if LIMIT >= 1:
        # if we're about to send a notification, see if the user has
        # not responded to several previous ones, and disable the
        # preference if so.
        prefs = player.get('player_preferences', {})
        if type(prefs) is dict and ('enable_fishing_notifications' not in prefs):
            if player['history'].get('fishing_notifications_sent',0) >= LIMIT:
                num_clicked = sum([v for k,v in player['history'].iteritems() if \
                                   k.startswith('fb_notification:fishing_complete_') and k.endswith(':clicked')], 0)
                if num_clicked < 1:
                    prefs['enable_fishing_notifications'] = 0
                    player['player_preferences'] = prefs
                    return False

    bus['notified'] = 1
    player['history']['fishing_notifications_sent'] = player['history'].get('fishing_notifications_sent',0) + 1
    return True

# functions to check if a notification applies
CHECKERS = {
    'harv_full': check_harv_full,
    'townhall_L3_upgrade_complete': functools.partial(check_upgrade_complete, 'townhall_L3_upgrade_complete', gamedata['townhall'], 3),
    'upgrade_complete': functools.partial(check_upgrade_complete, 'upgrade_complete', 'ALL', -1),
    'research_complete': check_research_complete,
    'production_complete': check_production_complete,
    'army_repaired': check_army_repaired,
    'fishing_complete': check_fishing_complete,
    'retain_': check_retain,
    }

# list of (-priority, ref, check_func) sorted in descending priority (increasing negative priority) order
CHECKERS_BY_PRIORITY = []

# separately collect the critical post-creation-time-window notifications
CRITICALS = {}

for key, val in gamedata['fb_notifications']['notifications'].iteritems():
    if val.get('enable_elder', True) or val.get('enable_newbie', True):
        match = critical_re.match(key)
        if match:
            # post-creation-time-window notification, handled specially
            num_hours = int(match.group(1))
            # time range to which this notification applies
            CRITICALS[key] = [num_hours*60*60, (num_hours+24)*60*60]
            continue
        match = retain_re.match(key)
        if match:
            # haven't-logged-in-for-a-while notification, handled regularly,
            # but raise MAX_MTIME_AGE if necessary
            num_hours = int(match.group(1))
            # widen the time window to make sure we catch everyone (max retain wait + 1 day)
            MAX_MTIME_AGE = max(MAX_MTIME_AGE, num_hours*60*60 + 24*60*60)
            CHECKERS_BY_PRIORITY.append((-val['priority'], key, CHECKERS['retain_']))
            continue
        if key in CHECKERS: # regular checker
            CHECKERS_BY_PRIORITY.append((-val['priority'], key, CHECKERS[key]))

CHECKERS_BY_PRIORITY.sort()

# functions to mutate player after sending a notification
FINISHERS = {'fishing_complete': finish_fishing_complete }

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
    def notify_user(self, user_id, pcache, index = -1, total_count = -1, only_frame_platform = None):

        self.seen += 1

        frame_platform = pcache.get('frame_platform',None)
        # for testing purposes, skip everything not on this platform
        if only_frame_platform is not None and frame_platform != only_frame_platform:
            return

        print >> self.msg_fd, '(%6.2f%%) %7d' % (100*float(index+1)/float(total_count), user_id),

        #print >> self.msg_fd, 'PCACHE:', repr(pcache)

        if not pcache.get('tutorial_complete',False):
            print >> self.msg_fd, '(player_cache says) tutorial not complete'
            return

        if frame_platform not in self.active_platforms:
            print >> self.msg_fd, '(player_cache says) frame_platform is not active'
            return

        platform_id = None
        if 'social_id' in pcache and pcache['social_id'].startswith(frame_platform):
            platform_id = pcache['social_id'][2:]
        elif frame_platform == 'fb' and 'facebook_id' in pcache:
            platform_id = str(pcache['facebook_id'])

        if (not platform_id) or (len(platform_id) < 3):
            print >> self.msg_fd, '(player_cache says) invalid platform_id: %r' % platform_id
            return

        if pcache.get('LOCK_STATE',0) != 0:
            print >> self.msg_fd, '(player_cache says) player is logged in or being modified right now'
            return

        if pcache.get('uninstalled',0):
            print >> self.msg_fd, '(player_cache says) player uninstalled'
            return

        if not pcache.get('enable_fb_notifications', True):
            print >> self.msg_fd, '(player_cache says) player turned off FB notifications'
            return


        if (time_now - pcache.get('last_fb_notification_time', -1)) < gamedata['fb_notifications']['min_interval']:
            print >> self.msg_fd, '(player_cache says) has already been notified less than min_interval seconds ago'
            return

        if ((time_now - pcache.get('last_mtime',-1)) < MIN_MTIME_AGE):
            print >> self.msg_fd, '(player_cache says) player cache data was modified less than %d minutes ago' % (MIN_MTIME_AGE/60)
            return

        # cannot re-notify a player notified since last login, except for critical windows
        if pcache.get('last_fb_notification_time', -1) >= pcache.get('last_login_time', -1):
            can_notify_again = False
            if 'account_creation_time' in pcache:
                for r in CRITICALS.itervalues():
                    if pcache['account_creation_time'] >= (time_now-r[1]) and \
                       pcache['account_creation_time'] <  (time_now-r[0]):
                        can_notify_again = True
                        break
            if not can_notify_again:
                print >> self.msg_fd, '(player_cache says) has already been notified since last login, and is not in critical window'
                return

        try:
            player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))

        except SpinS3.S3404Exception:
            # missing playerdb - might be due to an S3 failure
            print >> self.msg_fd, '(playerDB data missing)'
            return

#        if (player['abtests'].get("T125_newbie_notification", None) == "control"):
#            print >> self.msg_fd, '(player says) in non-notification control group'
#            return

        prefs = player.get('player_preferences', {})
        if type(prefs) is dict and (not prefs.get('enable_fb_notifications', gamedata['strings']['settings']['enable_fb_notifications']['default_val'])):
            print >> self.msg_fd, '(player says) enable_fb_notifications preference is OFF'
            # use pcache for this?
            # self.db_client.player_cache_update(user_id, {'enable_fb_notifications': 0})
            return

        last_logout_time = player['history']['sessions'][-1][1]

        if (last_logout_time < 0 or (time_now - last_logout_time) < MIN_MTIME_AGE):
            print >> self.msg_fd, '(player says) played less than %d mins ago' % (MIN_MTIME_AGE/60)
            return

        # check for applicable critical time window
        critical_ref = None
        if 'creation_time' in player:
            for key, r in CRITICALS.iteritems():
                if player['creation_time'] >= (time_now-r[1]) and \
                   player['creation_time'] <  (time_now-r[0]) and \
                   player['history'].get('fb_notification:'+key+':sent',0) < 1:
                    critical_ref = key

        if (not critical_ref) and player.get('last_fb_notification_time', -1) >= last_logout_time:
            print >> self.msg_fd, '(player says) has already been notified since last logout, and is not in critical window'
            # fix pcache entry
            self.db_client.player_cache_update(user_id, {'last_fb_notification_time': player.get('last_fb_notification_time',-1)})
            return

        elder = (len(player['history']['sessions']) >= gamedata['fb_notifications']['elder_threshold'])

        ref = None
        replace_s = ''
        checker_state = None

        for prio, key, func in CHECKERS_BY_PRIORITY:
            config = gamedata['fb_notifications']['notifications'].get(key, None)
            if not config: continue
            if frame_platform == 'bh' and 'email' not in config: continue
            if player.get('creation_time',-1) < config.get('min_account_creation_time',-1): continue

            min_interval = config.get('min_interval', -1)
            if (min_interval > 0) and (time_now - player.get('last_fb_notification_time', -1) < min_interval):
                #print >> self.msg_fd, 'too early to check for %s'
                continue

            if (elder and (not config.get('enable_elder', True))) or \
               ((not elder) and (not config.get('enable_newbie', True))):
                continue

            #print >> self.msg_fd, 'checking %s...' % key
            ref, replace_s, checker_state = func(pcache, player, config)
            if ref: break

        if (not ref) and critical_ref:
            # and (player['abtests'].get('T210_nnh_notification', None) == 'on'):
            # send critical notification
            config = gamedata['fb_notifications']['notifications'][critical_ref]
            if ((elder and config.get('enable_elder', True)) or \
               ((not elder) and config.get('enable_newbie', True))) and \
               (frame_platform != 'bh' or 'email' in config):
                ref = critical_ref
                replace_s = ''

        if not ref:
            print >> self.msg_fd, 'nothing to notify about (critical %s)' % critical_ref
            return

        self.eligible += 1

        ref_suffix = ''
        if gamedata['fb_notifications']['elder_suffix']:
            ref_suffix += '_e' if elder else '_n'

        config = gamedata['fb_notifications']['notifications'][ref]
        ui_name = config['ui_name']
        if type(ui_name) is dict: # A/B test
            key_list = sorted(ui_name.keys())
            key = key_list[random.randint(0,len(key_list)-1)]
            assert key.startswith('ui_')
            ui_name = ui_name[key]
            ref_suffix += '_'+key[3:]
        text = ui_name.replace('%s', replace_s)
        print >> self.msg_fd, 'eligible for: "%s"...' % (text)

        # userdb entry is necessary to find country for demographics dimensions
        # but ignore failures
        try:
            user = SpinJSON.loads(SpinUserDB.driver.sync_download_user(user_id))

        # October 2015 server bug caused some players to get written out without userdb entry. Ignore this.
        except SpinS3.S3404Exception:
            user = {}

        generation = player.get('generation',0)
        if not self.dry_run:
            if self.lock_client.player_lock_acquire_attack(user_id, generation) < 0:
                print >> self.msg_fd, 'cannot write, player is logged in'
                return

        try:
            if ref in FINISHERS:
                actually_send_it = FINISHERS[ref](player, checker_state)
                print >> self.msg_fd, 'mutator returned %r' % actually_send_it
                print >> self.msg_fd, repr(player['player_preferences'])
            else:
                actually_send_it = True

            if actually_send_it:
                # update last_fb_notification_time, but skip this for retain_* notifications,
                # since we might want to try more at different intervals
                if not retain_re.match(ref):
                    player['last_fb_notification_time'] = time_now
                player['history']['fb_notifications_sent'] = player['history'].get('fb_notifications_sent',0)+1
                player['history']['fb_notification:'+ref+':sent'] = player['history'].get('fb_notification:'+ref+':sent',0)+1
                player['history']['fb_notification:'+ref+':last_time'] = time_now

            # write player even if not sending the notification
            player['generation'] = generation+1

            if not self.dry_run:
                SpinUserDB.driver.sync_write_player(user_id, SpinJSON.dumps(player, pretty=True, newline=True, double_precision=5))
                print >> self.msg_fd, 'written!'

                if actually_send_it:
                    if frame_platform == 'fb':
                        url = SpinFacebook.versioned_graph_endpoint_secure('notification', str(platform_id)+'/notifications')
                        params = {'href': '',
                                  'ref': config['ref'] + ref_suffix,
                                  'template': text.encode('utf-8') }
                    elif frame_platform == 'bh':
                        url = SpinConfig.config['battlehouse_api_path'] + '/user/' + platform_id + '/notify'
                        email_conf = config['email']
                        params = {'service': SpinConfig.game(),
                                  'api_secret': SpinConfig.config['battlehouse_api_secret'],
                                  'ui_subject': email_conf['ui_subject'].encode('utf-8'),
                                  'ui_headline': email_conf['ui_headline'].encode('utf-8'),
                                  'ui_body': text.encode('utf-8'),
                                  'ui_cta': email_conf['ui_cta'].encode('utf-8'),
                                  'query': 'bh_source=notification&ref=%s&fb_ref=%s' % (config['ref'], config['ref'] + ref_suffix),
                                  'tags': SpinConfig.game()+'_'+config['ref']+ref_suffix,
                                  }

                        # temporary A/B test (with promising results)
                        if player['abtests'].get('T324_bh_fb_notifications', 'on') == 'on':
                            params['facebook'] = '1'

                    else:
                        raise Exception('unexpected frame_platform %r' % frame_platform)

                    print >> self.msg_fd, 'request:', url, params

                    try:
                        response = self.requests_session.post(url, data = params, timeout = 10)
                        if response.status_code == 200:
                            print >> self.msg_fd, 'notification sent!'
                            print >> self.msg_fd, 'GOT:', response.text
                        else:
                            raise Exception('unexpected response code %d body %r' % (response.status_code, response.text))
                    except:
                        print >> self.msg_fd, 'API error:', traceback.format_exc()

                    self.fb_notifications_log.event(time_now, {'user_id': user_id,
                                                               'event_name': '7130_fb_notification_sent', 'code':7130,
                                                               'sum': SpinETL.get_denormalized_summary_props(gamedata, player, user, 'brief'),
                                                               'ref': config['ref'],
                                                               'fb_ref': config['ref'] + ref_suffix})

                    # RETURN HITS WILL LOOK LIKE THIS:
                    # http://apps.facebook.com/marsfrontier/?fb_source=notification&fb_ref=harv_full&ref=notif&notif_t=app_notification

                    # tell player cache we mutated the player, so that upcache will pick it up on next sweep
                    self.db_client.player_cache_update(user_id, {'last_mtime': time_now,
                                                                 'last_fb_notification_time': player['last_fb_notification_time']})

        finally:
            if not self.dry_run:
                self.lock_client.player_lock_release(user_id, player['generation'], 2)

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


def run_batch(batch_num, batch, total_count, limit, dry_run, verbose, only_frame_platform):
    msg_fd = sys.stderr if verbose else NullFD()

    # reconnect to DB to avoid subprocesses sharing conenctions
    db_client = connect_to_db()
    if dry_run:
        lock_client = None
    else:
        lock_client = db_client

    sender = Sender(db_client, lock_client, dry_run = dry_run, msg_fd = msg_fd)
    pcache_list = db_client.player_cache_lookup_batch(batch, fields = ['tutorial_complete',
                                                                       'facebook_id','social_id','frame_platform',
                                                                       'last_login_time','last_mtime', 'uninstalled',
                                                                       'enable_fb_notifications',
                                                                       'last_fb_notification_time', 'LOCK_STATE'])
    for i in xrange(len(batch)):
        try:
            sender.notify_user(batch[i], pcache_list[i], index = BATCH_SIZE*batch_num + i, total_count = total_count, only_frame_platform = only_frame_platform)
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
    run_batch(input['batch_num'], input['batch'], input['total_count'], input['limit'], input['dry_run'], input['verbose'], input['only_frame_platform'])

# main program
if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(my_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['dry-run','test', 'limit=', 'parallel=', 'quiet', 'frame-platform='])
    dry_run = False
    test = False
    limit = -1
    parallel = -1
    verbose = True
    only_frame_platform = None

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '--test':
            test = True
        elif key == '--limit':
            limit = int(val)
        elif key == '--parallel':
            parallel = int(val)
        elif key == '--quiet':
            verbose = False
        elif key == '--frame-platform':
            only_frame_platform = val

    with SpinSingletonProcess.SingletonProcess('retention-newbie-%s' % (SpinConfig.config['game_id'],)):

        db_client = connect_to_db()

        id_list = []
        if test:
            id_list += [1112, 1114, 1115]

        if not test:
            if verbose: print 'querying player_cache...'
            id_list += db_client.player_cache_query_tutorial_complete_and_mtime_between_or_ctime_between([[time_now - MAX_MTIME_AGE, time_now - MIN_MTIME_AGE]],
                                                                                                         [[time_now - r[1], time_now - r[0]] for r in CRITICALS.itervalues()])

        id_list.sort(reverse=True)
        total_count = len(id_list)

        batches = [id_list[i:i+BATCH_SIZE] for i in xrange(0, len(id_list), BATCH_SIZE)]

        if verbose: print 'player_cache_query returned %d users -> %d batches' % (total_count, len(batches))

        if parallel <= 1:
            for batch_num in xrange(len(batches)):
                run_batch(batch_num, batches[batch_num], total_count, limit, dry_run, verbose, only_frame_platform)
        else:
            SpinParallel.go([{'batch_num':batch_num,
                              'batch':batches[batch_num],
                              'total_count':total_count,
                              'limit':limit, 'verbose':verbose, 'only_frame_platform': only_frame_platform,
                              'dry_run':dry_run} for batch_num in xrange(len(batches))],
                            [sys.argv[0], '--slave'],
                            on_error = 'break', nprocs=parallel, verbose = False)

