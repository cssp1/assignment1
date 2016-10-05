#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Script that runs externally to main server process to enforce anti-alt/anti-refresh policies.

import sys, time, getopt, traceback, random
import SpinConfig, SpinJSON, SpinParallel
import SpinNoSQL, SpinLog, SpinNoSQLLog
import SpinSingletonProcess
import ControlAPI

# load gamedata
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
gamedata['server'] = SpinConfig.load(SpinConfig.gamedata_component_filename("server_compiled.json"))

# process batches of this many users at once
BATCH_SIZE = 5

time_now = int(time.time())

def do_CONTROLAPI(args):
    args['ui_reason'] = 'PolicyBot' # for CustomerSupport action log entries
    return ControlAPI.CONTROLAPI(args, 'PolicyBot', max_tries = 3) # allow some retries

# given two pcache entries for an alt pair, return the entry that is the more senior "master" account
def master_account(a, b):
    aspent = a.get('money_spent',0)
    bspent = b.get('money_spent',0)
    if aspent > bspent:
        return a
    elif aspent < bspent:
        return b
    acreat = a.get('account_creation_time',0)
    bcreat = b.get('account_creation_time',0)
    if acreat > bcreat:
        return b
    elif acreat < bcreat:
        return a
    # break ties
    if a['user_id'] > b['user_id']:
        return b
    return a

def is_anti_alt_region(region): return 'anti_alt' in region.get('tags',[])
def is_anti_refresh_region(region): return 'anti_refresh' in region.get('tags',[])

anti_alt_region_names = [name for name, data in gamedata['regions'].iteritems() if is_anti_alt_region(data)]
allow_refresh_region_names = [name for name, data in gamedata['regions'].iteritems() if not is_anti_refresh_region(data)]

class Policy(object):
    # duration of repeat-offender state
    REPEAT_OFFENDER_COOLDOWN_DURATION = 30*86400

    # duration of banishment from prohibited regions
    REGION_BANISH_DURATION = 90*86400

    def __init__(self, db_client, dry_run = True, test = False, msg_fd = None, verbose = 0):
        self.db_client = db_client
        self.dry_run = dry_run
        self.test = test
        self.msg_fd = msg_fd
        self.verbose = verbose
        self.policy_bot_log = open_log(self.db_client)

class AntiRefreshPolicy(Policy):
    # ignore anything that happened more than a week ago
    # note: server.json idle_check keep_history_for setting should be at least this long
    IGNORE_AGE = 7*86400

    # don't take action until this many tests (regardless of success or failure)
    MIN_TESTS = 4

    # don't take action until this many failures
    MIN_FAILS = 2

    # don't take action unless failure rate is this high
    MIN_FAIL_RATE = 0.51

    # cooldown that identifies a player as a repeat offender
    REPEAT_OFFENDER_COOLDOWN_NAME = 'idle_check_violation'

    # query for candidate violators from player cache
    @classmethod
    def player_cache_query(cls, db_client, time_range):
        return db_client.player_cache_query_tutorial_complete_and_mtime_between_or_ctime_between([time_range], [],
                                                                                                 townhall_name = gamedata['townhall'],
                                                                                                 min_townhall_level = 3,
                                                                                                 # use exclude to catch un-regioned players
                                                                                                 exclude_home_regions = allow_refresh_region_names,
                                                                                                 min_idle_check_fails = cls.MIN_FAILS,
                                                                                                 min_idle_check_last_fail_time = time_now - cls.IGNORE_AGE)
    def check_player(self, user_id, player):

        # possible race condition after player cache lookup (?)
        if player['home_region'] in allow_refresh_region_names: return

        if self.test:
            idle_check = {'history': [
                {'time': time_now - 6000, 'result': 'fail', 'seen': 1},
                {'time': time_now - 5000, 'result': 'fail'},
                {'time': time_now - 4000, 'result': 'fail'},
                {'time': time_now - 3000, 'result': 'fail'},
                {'time': time_now - 2000, 'result': 'fail'},
                {'time': time_now - 1000, 'result': 'success'},
                ]}
        else:
            idle_check = player.get('idle_check', {})

        history = idle_check.get('history', [])

        num_tests = sum((1 for x in history if x['time'] >= time_now - self.IGNORE_AGE and not x.get('seen',0)), 0)
        if num_tests < self.MIN_TESTS:
            return # not enough tests

        num_fails = sum((1 for x in history if x['time'] >= time_now - self.IGNORE_AGE and not x.get('seen',0) and x['result'] == 'fail'), 0)
        num_successes = sum((1 for x in history if x['time'] >= time_now - self.IGNORE_AGE and not x.get('seen',0) and x['result'] == 'success'), 0)
        if num_fails < self.MIN_FAILS:
            return # not enough fails
        fail_rate = (1.0*num_fails) / (num_fails + num_successes)

        last_fail_time = -1
        for i in xrange(len(history)-1, -1, -1):
            if not history[i].get('seen',0) and history[i]['result'] == 'fail':
                last_fail_time = history[i]['time']
                break

        if self.verbose >= 2:
            print >> self.msg_fd, 'num_fails %d num_successes %d fail_rate %.1f last_fail_time %d' % (num_fails, num_successes, fail_rate, last_fail_time)

        if last_fail_time < time_now - self.IGNORE_AGE:
            return # last failure was too long ago

        if fail_rate < self.MIN_FAIL_RATE:
            return # not enough failures to worry about

        try:
            new_region_name = self.punish_player(user_id, player['home_region'])
            if self.verbose >= 2:
                print >> self.msg_fd, 'moved to region %s' % (new_region_name)

        except:
            sys.stderr.write(('error punishing player %d: '%(user_id)) + traceback.format_exc())

    def punish_player(self, user_id, cur_region_name):

        # check repeat offender status via cooldown
        # note: anti-refresh uses a stacked cooldown for repeat offenses

        active_stacks = do_CONTROLAPI({'user_id':user_id, 'method':'cooldown_active', 'name':self.REPEAT_OFFENDER_COOLDOWN_NAME})
        repeat_offender_level = max(active_stacks, 0)

        # things we might do to the player...
        message_body = None
        do_banish = False
        event_name = None
        new_region = None
        clear_repeat_stacks = False
        add_repeat_stack = False

        if not gamedata['server']['idle_check'].get('enforce',False): # flag only, don't act
            event_name = '7305_policy_bot_flagged'

        elif repeat_offender_level >= 2:
            # full punishment - removal from region and banishment

            cur_region = gamedata['regions'][cur_region_name]
            cur_continent_id = cur_region.get('continent_id',None)

            # find pro-refresh regions in the same continent
            pro_refresh_regions = filter(lambda x: not is_anti_refresh_region(x) and x.get('continent_id',None) == cur_continent_id, gamedata['regions'].itervalues())

            assert len(pro_refresh_regions) >= 1

            # pick any pro-refresh region (which will usually be prison)
            candidate_regions = filter(lambda x: x.get('continent_id',None) == cur_continent_id and \
                                       x.get('open_join',1) and x.get('enable_map',1) and \
                                       not x.get('developer_only',0),
                                       pro_refresh_regions)
            assert len(candidate_regions) >= 1
            new_region = candidate_regions[random.randint(0, len(candidate_regions)-1)]

            if not self.test:
                assert new_region['id'] != cur_region_name

            clear_repeat_stacks = True
            message_body = 'Our systems have again detected that you may be using a browser plugin or script to stay logged in to the game for long periods of time, and therefore relocated your base to %s and locked you out of the main map regions due to repeated violations of our Terms of Service. If you would like to appeal your case, please contact support and our team will be able to assist you.' % (new_region['ui_name'])
            do_banish = True
            event_name = '7301_policy_bot_punished'

        elif repeat_offender_level >= 1:
            message_body = 'Our systems have again detected that you may be using a browser plugin or script to stay logged in to the game for long periods of time. Please note that unattended gameplay - also known as \"auto-refreshing\" or \"botting\" - is strictly prohibited in our Terms of Service. Continued abuse may result in a permanent ban. Thank you in advance for your cooperation and understanding.'
            add_repeat_stack = True
            event_name = '7304_policy_bot_warned'

        else:
            message_body = 'Our systems have detected that you may be using a browser plugin or script to stay logged in to the game for long periods of time. Please note that unattended gameplay - also known as \"auto-refreshing\" or \"botting\" - is strictly prohibited in our Terms of Service. Continued abuse may result in a permanent ban. Thank you in advance for your cooperation and understanding.'
            add_repeat_stack = True
            event_name = '7304_policy_bot_warned'

        print >> self.msg_fd, 'punishing player %d... %r' % (user_id, {'repeat_offender_level': repeat_offender_level,
                                                                       'message_body': message_body,
                                                                       'do_banish': do_banish,
                                                                       'event_name': event_name,
                                                                       'new_region': new_region['id'] if new_region else None,
                                                                       'clear_repeat_stacks': clear_repeat_stacks,
                                                                       'add_repeat_stack': add_repeat_stack})

        if not self.dry_run:
            # region change should go first, since if it fails, we don't want to leave player in a strange state
            if new_region:
                assert do_CONTROLAPI({'user_id':user_id, 'method':'change_region', 'new_region':new_region['id']}) == 'ok'

            if clear_repeat_stacks:
                assert do_CONTROLAPI({'user_id':user_id, 'method':'clear_cooldown', 'name':self.REPEAT_OFFENDER_COOLDOWN_NAME}) == 'ok'

            if add_repeat_stack:
                assert do_CONTROLAPI({'user_id':user_id, 'method':'trigger_cooldown', 'add_stack': 1, 'name':self.REPEAT_OFFENDER_COOLDOWN_NAME, 'duration': self.REPEAT_OFFENDER_COOLDOWN_DURATION}) == 'ok'

            if do_banish:
                assert do_CONTROLAPI({'user_id':user_id, 'method':'apply_aura', 'aura_name':'region_banished',
                                      'duration': self.REGION_BANISH_DURATION,
                                      'data':SpinJSON.dumps({'tag':'anti_refresh'})}) == 'ok'

            # always give player a fresh start on the idle check
            assert do_CONTROLAPI({'user_id':user_id, 'method':'reset_idle_check_state'}) == 'ok'

            if message_body:
                assert do_CONTROLAPI({'user_id':user_id, 'method':'send_message',
                                      'message_body': message_body,
                                      'message_subject': 'Anti-Refresh Policy',
                                      }) == 'ok'

        event_props = {'user_id': user_id, 'event_name': event_name, 'code': int(event_name[0:4]),
                       'reason':'anti_refresh_violation', 'repeat_offender': repeat_offender_level}
        if new_region:
            event_props['old_region'] = cur_region_name
            event_props['new_region'] = new_region['id']

        if not self.dry_run:
            self.policy_bot_log.event(time_now, event_props)
        else:
            print >> self.msg_fd, event_props

        return new_region['id'] if new_region else None


class AntiAltPolicy(Policy):
    # min number of simultaneous logins to trigger action
    MIN_LOGINS = 10

    # ignore alt-account logins that last happened over a week ago
    IGNORE_AGE = 7*86400

    # cooldown that identifies a player as a repeat offender
    REPEAT_OFFENDER_COOLDOWN_NAME = 'alt_account_violation'

    # query for candidate violators from player cache
    @classmethod
    def player_cache_query(cls, db_client, time_range):
        return db_client.player_cache_query_tutorial_complete_and_mtime_between_or_ctime_between([time_range], [],
                                                                                                 townhall_name = gamedata['townhall'],
                                                                                                 min_townhall_level = 3,
                                                                                                 include_home_regions = anti_alt_region_names,
                                                                                                 min_known_alt_count = 1)


    def check_player(self, user_id, player):

        # special case for BFM on BH - disregard BH accounts
        if SpinConfig.game() == 'bfm':
            user = do_CONTROLAPI({'user_id':user_id, 'method':'get_raw_user'})
            if (not user) or (user.get('frame_platform') == 'bh'):
                return

        # possible race condition after player cache lookup (?)
        if player['home_region'] not in anti_alt_region_names: return

        if self.test:
            alt_accounts = {str(user_id+1): {'logins': 99, 'last_login': time_now-60}}
        else:
            # ignore bad old data
            if player['history'].get('alt_account_data_epoch',-1) < gamedata['server'].get('alt_account_data_epoch',-1):
                return

            alt_accounts = player.get('known_alt_accounts', {})

        if not alt_accounts or not isinstance(alt_accounts, dict): return

        alt_ids = []

        for salt_id, alt_data in alt_accounts.iteritems():
            if alt_data.get('ignore',0): continue
            if alt_data.get('logins',0) < self.MIN_LOGINS: continue
            if alt_data.get('last_login',0) < time_now - self.IGNORE_AGE: continue

            # last-chance check for any IGNORE_ALT instructions that were dumped out of alt_account_data
            # but still logged in customer support history
            if any(x['method'] == 'ignore_alt' and \
                   int(x['args']['other_id']) == int(salt_id) \
                   for x in player['history'].get('customer_support',[])): continue

            alt_ids.append(int(salt_id))

        if self.verbose >= 2:
            print >> self.msg_fd, 'alt_ids %r alt_accounts %r' % (alt_ids, alt_accounts)

        if not alt_ids: return

        # query player cache on alts to determine if they are in the same region, and compare spend/account creation time
        alt_pcaches = self.db_client.player_cache_lookup_batch(alt_ids, fields = ['home_region','money_spent','account_creation_time'])
        our_pcache = {'user_id': user_id, 'money_spent': player['history'].get('money_spent',0), 'account_creation_time': player['creation_time']}

        if self.verbose >= 2:
            print >> self.msg_fd, 'player %d in %s has possible alts: %r' % (user_id, player['home_region'], alt_pcaches)

        interfering_alt_pcaches = []

        for alt_pcache in alt_pcaches:
            if self.test or alt_pcache.get('home_region', None) == player['home_region']:
                # check to see whether this is the "master" account - if not, we'll be taking action when scanning the other account
                if master_account(our_pcache, alt_pcache) is not our_pcache:
                    continue

                # special case for BFM on BH - disregard BH accounts
                if SpinConfig.game() == 'bfm':
                    other_user = do_CONTROLAPI({'user_id':alt_pcache['user_id'], 'method':'get_raw_user'})
                    if (not other_user) or (other_user.get('frame_platform') == 'bh'):
                        continue

                interfering_alt_pcaches.append(alt_pcache)

        if not interfering_alt_pcaches:
            return

        print >> self.msg_fd, 'player %d has violating alts: %r' % (user_id, interfering_alt_pcaches)

        for alt_pcache in interfering_alt_pcaches:
            print >> self.msg_fd, 'punishing player %d (alt of %d)...' % (alt_pcache['user_id'], user_id),

            try:

                # list of region names where player has OTHER alts (including the master account)
                other_alt_region_names = set([pc['home_region'] for pc in interfering_alt_pcaches if pc is not alt_pcache] + [player['home_region'],])

                # update the alt's home region so next pass will get the right data
                new_region_name = self.punish_player(alt_pcache['user_id'], user_id, player['home_region'], other_alt_region_names,
                                                     [pc['user_id'] for pc in interfering_alt_pcaches]+[user_id,])

                alt_pcache['home_region'] = new_region_name
                print >> self.msg_fd, 'moved to region %s' % (new_region_name)

            except:
                sys.stderr.write(('error punishing user %d: '%(alt_pcache['user_id'])) + traceback.format_exc())

    def punish_player(self, user_id, master_id, cur_region_name, other_alt_region_names, all_alt_ids):

        cur_region = gamedata['regions'][cur_region_name]
        cur_continent_id = cur_region.get('continent_id',None)

        # find pro- and anti-alt regions in the same continent
        anti_alt_regions = filter(lambda x: is_anti_alt_region(x) and x.get('continent_id',None) == cur_continent_id, gamedata['regions'].itervalues())
        pro_alt_regions = filter(lambda x: not is_anti_alt_region(x) and x.get('continent_id',None) == cur_continent_id, gamedata['regions'].itervalues())

        assert len(anti_alt_regions) >= 1 and len(pro_alt_regions) >= 1
        is_majority_anti_alt_game = (len(anti_alt_regions) > len(pro_alt_regions)) or \
                                    (SpinConfig.game() == 'bfm') # special-purpose hack for BFM during migration

        # check repeat offender status via cooldown
        togo = do_CONTROLAPI({'user_id':user_id, 'method':'cooldown_togo', 'name':self.REPEAT_OFFENDER_COOLDOWN_NAME})
        is_repeat_offender = (togo > 0)

        # pick destination region
        new_region = None

        if is_majority_anti_alt_game and (not is_repeat_offender):
            # pick any other region, including anti-alt regions, as long as player has no OTHER alts there
            candidate_regions = filter(lambda x: x.get('continent_id',None) == cur_continent_id and \
                                       x.get('auto_join',1) and x.get('enable_map',1) and \
                                       not x.get('developer_only',0) and \
                                       x['id'] not in other_alt_region_names, gamedata['regions'].itervalues())
            if self.verbose >= 2:
                print >> self.msg_fd, 'continent %r first-pass candidate_regions %r' % (cur_continent_id, [x['id'] for x in candidate_regions])

            if len(candidate_regions) >= 1:
                new_region = candidate_regions[random.randint(0, len(candidate_regions)-1)]

        if new_region is None:
            # pick any pro-alt region (which will be prison in a majority anti-alt game)
            candidate_regions = filter(lambda x: x.get('continent_id',None) == cur_continent_id and \
                                       (is_majority_anti_alt_game or x.get('auto_join',1)) and \
                                       x.get('open_join',1) and x.get('enable_map',1) and \
                                       not x.get('developer_only',0),
                                       pro_alt_regions)
            if self.verbose >= 2:
                print >> self.msg_fd, 'continent %r second-pass candidate_regions %r' % (cur_continent_id, [x['id'] for x in candidate_regions])

            assert len(candidate_regions) >= 1
            new_region = candidate_regions[random.randint(0, len(candidate_regions)-1)]

        if not self.test:
            assert new_region['id'] != cur_region_name

        if not self.dry_run:
            assert do_CONTROLAPI({'user_id':user_id, 'method':'trigger_cooldown', 'name':self.REPEAT_OFFENDER_COOLDOWN_NAME, 'duration': self.REPEAT_OFFENDER_COOLDOWN_DURATION}) == 'ok'

            if is_repeat_offender:
                # only repeat offenders get the banishment aura
                assert do_CONTROLAPI({'user_id':user_id, 'method':'apply_aura', 'aura_name':'region_banished',
                                      'duration': self.REGION_BANISH_DURATION,
                                      'data':SpinJSON.dumps({'tag':'anti_alt'})}) == 'ok'

            assert do_CONTROLAPI({'user_id':user_id, 'method':'change_region', 'new_region':new_region['id']}) == 'ok'


        # player messages are slightly different depending on whether the game is majority anti-alt (DV) or not (WSE,TR,etc).
        if not is_repeat_offender:
            if is_majority_anti_alt_game:
                message_body = 'We identified an alternate account (ID %d) with you in %s and therefore relocated your base to %s. If we falsely identified your account as an alternate account, please contact support and our team will be able to assist you with the case. However, note that a repeated violation of our anti-alt policy will result in a permanent ban from map regions.' % (master_id, cur_region['ui_name'], new_region['ui_name'])
            else:
                message_body = 'We identified an alternate account (ID %d) with you in the anti-alt region %s and therefore relocated your base to %s. If we falsely identified your account as an alternate account, please contact support and our team will be able to assist you with the case. However, note that a repeated violation of our anti-alt policy will result in a permanent ban from anti-alt maps.' % (master_id, cur_region['ui_name'], new_region['ui_name'])
        else: # repeat offender
            if is_majority_anti_alt_game:
                message_body = 'We identified an alternate account (ID %d) with you in %s and therefore relocated your base to %s and locked you out of the main map regions due to repeated violations of our anti-alt policy. If you would like to appeal your case, please contact support and our team will be able to assist you.' % (master_id, cur_region['ui_name'], new_region['ui_name'])
            else:
                message_body = 'We identified an alternate account (ID %d) with you in the anti-alt region %s and therefore relocated your base to %s. Moreover, your account has been locked from anti-alt map regions due to repeated violations of our anti-alt policy. If you would like to appeal your case, please contact support and our team will be able to assist you.' % (master_id, cur_region['ui_name'], new_region['ui_name'])

        if not self.dry_run:
            assert do_CONTROLAPI({'user_id':user_id, 'method':'send_message',
                                  'message_body': message_body,
                                  'message_subject': 'Alt Account Policy',
                                  }) == 'ok'

        event_props = {'user_id': user_id, 'event_name': '7301_policy_bot_punished', 'code':7301,
                       'old_region': cur_region_name, 'new_region': new_region['id'],
                       'reason':'alt_account_violation', 'repeat_offender': is_repeat_offender,
                       'other_alt_region_names': list(other_alt_region_names),
                       'all_alt_ids': list(all_alt_ids),
                       'master_id': master_id}
        if not self.dry_run:
            self.policy_bot_log.event(time_now, event_props)
        else:
            print >> self.msg_fd, event_props

        return new_region['id']

def connect_to_db():
    return SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'PolicyBot')

def open_log(db_client):
    return SpinLog.MultiLog([SpinLog.DailyJSONLog(SpinConfig.config.get('log_dir', 'logs')+'/', '-policy_bot.json'),
                             SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_policy_bot')])

class NullFD(object):
    def write(self, stuff): pass

POLICIES = [AntiAltPolicy, AntiRefreshPolicy]

def my_slave(input):
    msg_fd = sys.stderr if input['verbose'] else NullFD()

    # reconnect to DB to avoid subprocesses sharing conenctions
    db_client = connect_to_db()

    checks = [pol(db_client, dry_run = input['dry_run'], msg_fd = msg_fd, test = input['test'], verbose = input['verbose']) \
              for pol in POLICIES]

    for i in xrange(len(input['batch'])):
        time_now = int(time.time())
        db_client.set_time(time_now)

        user_id = input['batch'][i]
        index = input['batch_start_index'] + i
        total_count = input['total_count']

        print >> msg_fd, '(%6.2f%%) %7d' % (100*float(index+1)/float(total_count), user_id)

        try:
            player = do_CONTROLAPI({'user_id':user_id, 'method':'get_raw_player'})
            for check in checks:
                check.check_player(user_id, player)
        except KeyboardInterrupt:
            raise # allow Ctrl-C to abort
        except:
            sys.stderr.write(('error processing user %d: '%(input['batch'][i])) + traceback.format_exc())

    print >> msg_fd, 'batch %d done' % input['batch_num']

# main program
if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(my_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['dry-run','test', 'parallel=', 'quiet', 'verbose', 'user-id=', 'non-incremental'])
    dry_run = False
    test = False
    parallel = -1
    verbose = 1
    incremental = True
    manual_user_list = []

    for key, val in opts:
        if key == '--dry-run':
            dry_run = True
        elif key == '--test':
            test = True
        elif key == '--parallel':
            parallel = int(val)
        elif key == '--quiet':
            verbose = 0
        elif key == '--user-id':
            manual_user_list.append(int(val))
        elif key == '-v' or key == '--verbose':
            verbose = 2
        elif key == '--non-incremental':
            incremental = False

    if not manual_user_list and not anti_alt_region_names:
        sys.exit(0) # nothing to do

    with SpinSingletonProcess.SingletonProcess('PolicyBot-%s' % (SpinConfig.config['game_id'],)):

        db_client = connect_to_db()
        db_client.set_time(time_now)

        run_start_time = time_now
        start_time = time_now - max(pol.IGNORE_AGE for pol in POLICIES)

        if manual_user_list:
            id_list = manual_user_list

        else:
            if incremental:
                # if we can find a recent run in the log, start from where it left off
                if verbose: print 'checking for recent completed run...'
                for last_run in db_client.log_retrieve('log_policy_bot', time_range = [start_time, time_now], code = 7300, sort_direction = -1, limit = 1):
                    start_time = max(start_time, last_run['time'])
                    if verbose: print 'found previous run - starting at', start_time

            id_list = []

            if test:
                id_list += [1112,]
            else:
                if verbose: print 'querying player_cache...'
                id_list += sum((pol.player_cache_query(db_client, [start_time, time_now]) for pol in POLICIES), [])

        id_list = list(set(id_list)) # uniquify
        id_list.sort(reverse=True)

        if not dry_run and not manual_user_list:
            policy_bot_log = open_log(db_client)
            policy_bot_log.event(time_now, {'event_name': '7300_policy_bot_run_started', 'code': 7300, 'num_users': len(id_list)})

        try:

            batches = [{'batch_num':i//BATCH_SIZE, 'batch_start_index':i,
                        'batch':id_list[i:i+BATCH_SIZE],
                        'total_count':len(id_list),
                        'verbose':verbose, 'test':test,
                        'dry_run':dry_run} for i in xrange(0, len(id_list), BATCH_SIZE)]

            if verbose: print 'candidate set of %d users -> %d batches' % (len(id_list), len(batches))

            if parallel <= 1:
                for batch_num in xrange(len(batches)):
                    my_slave(batches[batch_num])
            else:
                SpinParallel.go(batches,
                                [sys.argv[0], '--slave'],
                                on_error = 'continue', nprocs=parallel, verbose = False)

            time_now = int(time.time())
            db_client.set_time(time_now)

            if not dry_run and not manual_user_list:
                policy_bot_log.event(time_now, {'event_name': '7302_policy_bot_run_finished', 'code': 7302, 'start_time':run_start_time})

        except:
            if not dry_run and not manual_user_list:
                time_now = int(time.time())
                db_client.set_time(time_now)
                policy_bot_log.event(time_now, {'event_name': '7303_policy_bot_run_aborted', 'code': 7303, 'start_time':run_start_time})
            raise
