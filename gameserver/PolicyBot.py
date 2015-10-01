#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Script that runs externally to main server process to enforce alt-account policy.

import sys, time, urllib, requests, getopt, traceback, random
import SpinConfig, SpinJSON, SpinParallel
import SpinNoSQL, SpinLog, SpinNoSQLLog
import SpinSingletonProcess

# min number of simultaneous logins to trigger action
MIN_LOGINS = 10
# ignore simultaneous logins that last happened over a week ago
IGNORE_AGE = 7*86400

# load gamedata
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

# process batches of this many users at once
BATCH_SIZE = 5

# cooldown that identifies a player as a repeat offender
REPEAT_OFFENDER_COOLDOWN_NAME = 'alt_account_violation'
REPEAT_OFFENDER_COOLDOWN_DURATION = 30*86400

# duration of banishment from anti-alt regions
REGION_BANISH_DURATION=30*86400

time_now = int(time.time())

def do_CONTROLAPI(args):
    host = SpinConfig.config['proxyserver'].get('external_listen_host','localhost')
    proto = 'http' if host == 'localhost' else 'https'
    url = '%s://%s:%d/CONTROLAPI' % (proto, host, SpinConfig.config['proxyserver']['external_http_port' if proto == 'http' else 'external_ssl_port'])
    args['ui_reason'] = 'PolicyBot'
    args['spin_user'] = 'PolicyBot'
    args['secret'] = SpinConfig.config['proxy_api_secret']
    response = requests.post(url+'?'+urllib.urlencode(args))
    assert response.status_code == 200
    ret = SpinJSON.loads(response.text)
    if 'error' in ret:
        raise Exception('CONTROLAPI error: %r' % ret['error'])

    return ret

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

class Sender(object):
    def __init__(self, db_client, dry_run = True, test = False, msg_fd = None, verbose = 0):
        self.db_client = db_client
        self.dry_run = dry_run
        self.test = test
        self.seen = 0
        self.msg_fd = msg_fd
        self.verbose = verbose
        self.policy_bot_log = open_log(self.db_client)

    def check_user(self, user_id, index = -1, total_count = -1):

        self.seen += 1
        print >> self.msg_fd, '(%6.2f%%) %7d' % (100*float(index+1)/float(total_count), user_id)

        player = do_CONTROLAPI({'user_id':user_id, 'method':'get_raw_player'})['result']

        if self.test:
            alt_accounts = {str(user_id+1): {'logins': 99, 'last_login': time_now-60}}
        else:
            alt_accounts = player.get('known_alt_accounts', {})

        if not alt_accounts or not isinstance(alt_accounts, dict): return

        alt_ids = []

        for salt_id, alt_data in alt_accounts.iteritems():
            if alt_data.get('ignore',0): continue
            if alt_data.get('logins',0) < MIN_LOGINS: continue
            if alt_data.get('last_login',0) < time_now - IGNORE_AGE: continue
            alt_ids.append(int(salt_id))

        if self.verbose >= 2:
            print >> self.msg_fd, 'alt_ids %r alt_accounts %r' % (alt_ids, alt_accounts)

        if not alt_ids: return

        # query player cache on alts to determine if they are in the same region, and compare spend/account creation time
        alt_pcaches = self.db_client.player_cache_lookup_batch(alt_ids, fields = ['home_region','money_spent','account_creation_time'])
        our_pcache = {'user_id': user_id, 'money_spent': player['history'].get('money_spent',0), 'account_creation_time': player['creation_time']}

        if self.verbose >= 2:
            print >> self.msg_fd, 'player %d has possible alts: %r' % (user_id, alt_pcaches)

        interfering_alt_pcaches = []

        for alt_pcache in alt_pcaches:
            if self.test or alt_pcache.get('home_region', None) == player['home_region']:
                # check to see whether this is the "master" account - if not, we'll be taking action when scanning the other account
                if master_account(our_pcache, alt_pcache) is not our_pcache:
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
                new_region_name = self.punish_user(alt_pcache['user_id'], user_id, player['home_region'], other_alt_region_names,
                                                   [pc['user_id'] for pc in interfering_alt_pcaches]+[user_id,])

                alt_pcache['home_region'] = new_region_name
                print >> self.msg_fd, 'moved to region %s' % (new_region_name)

            except:
                sys.stderr.write(('error punishing user %d: '%(alt_pcache['user_id'])) + traceback.format_exc())

    def punish_user(self, user_id, master_id, cur_region_name, other_alt_region_names, all_alt_ids):

        cur_region = gamedata['regions'][cur_region_name]
        cur_continent_id = cur_region.get('continent_id',None)

        # find pro- and anti-alt regions in the same continent
        anti_alt_regions = filter(lambda x: is_anti_alt_region(x) and x.get('continent_id',None) == cur_continent_id, gamedata['regions'].itervalues())
        pro_alt_regions = filter(lambda x: not is_anti_alt_region(x) and x.get('continent_id',None) == cur_continent_id, gamedata['regions'].itervalues())

        assert len(anti_alt_regions) >= 1 and len(pro_alt_regions) >= 1
        is_majority_anti_alt_game = len(anti_alt_regions) > len(pro_alt_regions)

        # check repeat offender status via cooldown
        togo = do_CONTROLAPI({'user_id':user_id, 'method':'cooldown_togo', 'name':REPEAT_OFFENDER_COOLDOWN_NAME})['result']
        is_repeat_offender = (togo > 0)

        # pick destination region
        new_region = None

        if is_majority_anti_alt_game and (not is_repeat_offender):
            # pick any other region, including anti-alt regions, as long as player has no OTHER alts there
            candidate_regions = filter(lambda x: x.get('continent_id',None) == cur_continent_id and \
                                       x.get('auto_join',1) and x.get('enable_map',1) and \
                                       not x.get('developer_only',0) and \
                                       x['id'] not in other_alt_region_names, gamedata['regions'].itervalues())
            if len(candidate_regions) >= 1:
                new_region = candidate_regions[random.randint(0, len(candidate_regions)-1)]

        if new_region is None:
            # pick any pro-alt region (which will be prison in a majority anti-alt game)
            candidate_regions = filter(lambda x: x.get('continent_id',None) == cur_continent_id and \
                                       (is_majority_anti_alt_game or x.get('auto_join',1)) and \
                                       x.get('open_join',1) and x.get('enable_map',1) and \
                                       not x.get('developer_only',0),
                                       pro_alt_regions)
            assert len(candidate_regions) >= 1
            new_region = candidate_regions[random.randint(0, len(candidate_regions)-1)]

        if not self.test:
            assert new_region['id'] != cur_region_name

        if not self.dry_run:
            assert do_CONTROLAPI({'user_id':user_id, 'method':'trigger_cooldown', 'name':REPEAT_OFFENDER_COOLDOWN_NAME, 'duration': REPEAT_OFFENDER_COOLDOWN_DURATION})['result'] == 'ok'

            if is_repeat_offender:
                # only repeat offenders get the banishment aura
                assert do_CONTROLAPI({'user_id':user_id, 'method':'apply_aura', 'aura_name':'region_banished',
                                      'duration': REGION_BANISH_DURATION,
                                      'data':SpinJSON.dumps({'tag':'anti_alt'})})['result'] == 'ok'

            assert do_CONTROLAPI({'user_id':user_id, 'method':'change_region', 'new_region':new_region['id']})['result'] == 'ok'


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
                                  })['result'] == 'ok'

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

def my_slave(input):
    msg_fd = sys.stderr if input['verbose'] else NullFD()

    # reconnect to DB to avoid subprocesses sharing conenctions
    db_client = connect_to_db()

    sender = Sender(db_client, dry_run = input['dry_run'], msg_fd = msg_fd, test = input['test'], verbose = input['verbose'])

    for i in xrange(len(input['batch'])):
        time_now = int(time.time())
        db_client.set_time(time_now)

        try:
            sender.check_user(input['batch'][i], index = input['batch_start_index'] + i, total_count = input['total_count'])
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

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['dry-run','test', 'parallel=', 'quiet', 'verbose', 'user-id='])
    dry_run = False
    test = False
    parallel = -1
    verbose = 1
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

    anti_alt_region_names = [name for name, data in gamedata['regions'].iteritems() if is_anti_alt_region(data)]

    if not manual_user_list and not anti_alt_region_names:
        sys.exit(0) # nothing to do

    with SpinSingletonProcess.SingletonProcess('PolicyBot-%s' % (SpinConfig.config['game_id'],)):

        db_client = connect_to_db()
        db_client.set_time(time_now)

        run_start_time = time_now
        start_time = time_now - IGNORE_AGE

        if manual_user_list:
            id_list = manual_user_list

        else:
            # if we can find a recent run in the log, start from where it left off
            if verbose: print 'checking for recent completed run...'
            for last_run in db_client.log_retrieve('log_policy_bot', time_range = [time_now - IGNORE_AGE, time_now], code = 7300, sort_direction = -1, limit = 1):
                start_time = max(start_time, last_run['time'])
                if verbose: print 'found previous run - starting at', start_time

            id_list = []

            if test:
                id_list += [1112,]
            else:
                if verbose: print 'querying player_cache...'
                id_list += db_client.player_cache_query_tutorial_complete_and_mtime_between_or_ctime_between([[start_time, time_now]], [],
                                                                                                             townhall_name = gamedata['townhall'],
                                                                                                             min_townhall_level = 3,
                                                                                                             include_home_regions = anti_alt_region_names,
                                                                                                             min_known_alt_count = 1)

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

            if verbose: print 'player_cache_query returned %d users -> %d batches' % (len(id_list), len(batches))

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
