#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# reconstruct missing spent_by_day, and sessions fields for
# player.history based on metrics log

try: import simplejson as json
except: import json
import sys, os, time
import getopt
import glob
import SpinNoSQL
import SpinConfig
import AtomicFileWrite

time_now = int(time.time())

if __name__ == "__main__":
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['write'])
    args = sys.argv[1:]
    if len(args) < 3:
        print 'usage: %s userdb playerdb game_id' % sys.argv[0]
        sys.exit(1)

    userdb_dir = args[0]
    playerdb_dir = args[1]
    game_id = args[2]

    do_write = False
    for key, val in opts:
        if key == '--write':
            do_write = True

    if do_write:
        db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
        db_client.set_time(time_now)
    else:
        db_client = None

    # first read all metrics logs to get number of logins by day by user
    spend = {} # map from user_id to [(time, amount)]
    logins = {} # map from user_id to [time,time,time,...]
    sessions = {} # map from user_id to [[in,out], [in,out], ...]
    file_list = glob.glob(SpinConfig.config['log_dir']+'/*-credits.json') + glob.glob(SpinConfig.config['log_dir']+'/*-sessions.json')
    file_list.sort()

    for i in range(len(file_list)):
        filename = file_list[i]
        sys.stderr.write('\rloading metrics data %d of %d...' % (i+1, len(file_list)))

        # sort events by time (within each file)
        events = []
        for line in open(filename).xreadlines():
            if not (('1000_billed' in line) or ('0115_logged_in' in line) or ('_logged_out' in line)):
                continue
            events.append(json.loads(line))

        events.sort(key = lambda ev: int(ev['time']))

        for met in events:
            evname = met['event_name']
            user_id = int(met['user_id'])
            etime = int(met['time'])
            if evname == '1000_billed':
                amount = float(met['Billing Amount'])
                if user_id not in spend:
                    spend[user_id] = []
                spend[user_id].append((etime, amount))
            elif evname == '0115_logged_in':
                if user_id not in logins:
                    logins[user_id] = []
                    sessions[user_id] = []
                logins[user_id].append(etime)
                # detect unclosed sessions and cap them
                if len(sessions[user_id]) > 0:
                    if sessions[user_id][-1][1] == -1:
                        sessions[user_id][-1][1] = etime
                sessions[user_id].append([etime,-1])
            elif evname == '0910_logged_out' or evname == '0900_logged_out':
                if user_id in sessions:
                    if sessions[user_id][-1][1] == -1:
                        sessions[user_id][-1][1] = etime

    sys.stderr.write('done\n')

    # consistency-check sessions array
    for s in sessions.itervalues():
        try:
            for i in xrange(len(s)):
                if s[i][1] < 0:
                    assert i == len(s)-1
                else:
                    assert s[i][0] <= s[i][1]
                if i < len(s)-1:
                    if (not s[i+1][0] >= s[i][0]):
                        print 'backwards in time!'
                        print s[i]
                        print s[i+1]
                        assert 0
        except AssertionError:
            print s
            raise

    # XXX USERS = set(spend.keys() + logins.keys()) # refresh credits and sessions data
    USERS = list(set(spend.keys())) # only refresh credits data
    USERS.sort()

    file_list = [playerdb_dir+('/%d_%s.txt' % (uid, game_id)) for uid in USERS]
    counter = 0

    for filename in file_list:
        counter += 1
        sys.stderr.write('\rupdating user %d of %d (%.2f%%)...' % (counter+1, len(file_list), 100.0*(counter/float(len(file_list)))))

        if 'facebook_id_map' in filename: continue
        try:
            locked = False

            player = json.load(open(filename))

            if not player.has_key('user_id'):
                # handle old entries with no inline user_id
                player['user_id'] = int(os.path.basename(filename).split('.')[0])
            user_id = player['user_id']
            if user_id < 1100:
                # AI users
                continue

            if do_write:
                generation = player.get('generation', 0)
                if db_client.player_lock_acquire_attack(user_id, generation) < 0:
                    sys.stderr.write('could not acquire write lock on user_id %d, skipping\n' % user_id)
                    continue
                else:
                    #sys.stderr.write('user %d locked\n' % user_id)
                    locked = True

            if 'history' not in player:
                player['history'] = {}

            # get corresponding user file
            user_filename = userdb_dir+'/%d.txt' % (user_id,)
            try:
                user = json.load(open(user_filename))
            except:
                sys.stderr.write('user file missing for user_id %d!' % user_id)
                continue

            account_creation_time = user.get('account_creation_time', 0)
            if account_creation_time < 1 and (user_id in sessions) and len(sessions[user_id]) > 0:
                # fill in missing account_creation_time based on first session
                account_creation_time = sessions[user_id][0][0]
                if account_creation_time > 0:
                    sys.stderr.write('fixing account_creation_time for user %d\n' % user_id)
                    if do_write:
                        user['account_creation_time'] = account_creation_time
                        atom = AtomicFileWrite.AtomicFileWrite(user_filename, 'w')
                        atom.fd.write(json.dumps(user, indent=2))
                        atom.complete(fsync = False)
            if account_creation_time < 1:
                sys.stderr.write('no account_creation_time for user %d\n' % user_id)
                continue

            spent_by_day = {}
            spent_at_time = {}

            if user_id in spend:
                purchase_list = spend[user_id]
                for purchase in purchase_list:
                    daynum = int((purchase[0] - account_creation_time)/(60*60*24))
                    key = str(daynum)
                    if key not in spent_by_day:
                        spent_by_day[key] = 0.0
                    spent_by_day[key] += purchase[1]

                    atkey = str(purchase[0] - account_creation_time)
                    spent_at_time[atkey] = spent_at_time.get(atkey,0.0) + purchase[1]


            #print 'user', user_id, 'spent_by_day', spent_by_day, 'sessions', sessions[user_id]

            if 0:
                if 'money_spent_at_time' in player['history']:
                    OLD = sorted(player['history']['money_spent_at_time'].items(), key = lambda kv: int(kv[0]))
                    NEW = sorted(spent_at_time.items(), key = lambda kv: int(kv[0]))
                    if OLD != NEW:
                        print 'OLD', OLD
                        print 'NEW', NEW
                        print 'money_spent_at_time mismatch on user %d' % user_id

            if do_write:
                os.utime(user_filename, None) # update mtime so dump_userdb will refresh upcache
                player['history']['money_spent_by_day'] = spent_by_day
                player['history']['money_spent_at_time'] = spent_at_time
                player['history']['sessions'] = sessions[user_id]
                generation += 1
                player['generation'] = generation
                atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
                atom.fd.write(json.dumps(player, indent=2))
                atom.complete(fsync = False)
            #    db_client.player_cache_update(user_id, props)

        except:
            sys.stderr.write('PROBLEM FILE: '+filename+'\n')
            raise
        finally:
            if locked:
                #sys.stderr.write('user %d unlocked\n' % user_id)
                db_client.player_lock_release(user_id, generation, 2)

    sys.exit(0)
