#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# reconstruct missing money_spent_by_day and last_purchase fields for players based on credits log

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

    # first read all credits logs to get money spent by user by day
    spend = {} # map from user_id to [(time,amount),...]
    file_list = glob.glob(SpinConfig.config['log_dir']+'/*-credits.json')
    sys.stderr.write('loading credits purchase data...\n')
    for filename in file_list:
        for line in open(filename).xreadlines():
            if not '1000_billed' in line:
                continue
            met = json.loads(line)
            evname = met['event_name']
            if evname == '1000_billed':
                user_id = int(met['user_id'])
                amount = float(met['Billing Amount'])
                if user_id not in spend:
                    spend[user_id] = []
                spend[user_id].append((int(met['time']), amount))

    file_list = [playerdb_dir+('/%d_%s.txt' % (uid, game_id)) for uid in spend.iterkeys()]
    counter = 0
    #TEMP = {}

    for filename in file_list:
        counter += 1
        sys.stderr.write('\rfile %d of %d (%.2f%%) user_id...' % (counter, len(file_list), 100.0*(counter/float(len(file_list)))))

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

            if 'history' not in player:
                player['history'] = {}

            if 'money_spent_by_day' in player['history'] and 'last_purchase_time' in player['history']:
                sys.stderr.write('user %d already has data, skipping' % user_id)
                continue

            if do_write:
                generation = player.get('generation', 0)
                if db_client.player_lock_acquire_attack(user_id, generation) < 0:
                    sys.stderr.write('could not acquire write lock on user_id %d, skipping\n' % user_id)
                    continue
                else:
                    #sys.stderr.write('user %d locked\n' % user_id)
                    locked = True

            # get corresponding user file
            try:
                user = json.load(open(userdb_dir+'/%d.txt' % (user_id,)))
            except:
                sys.stderr.write('user file missing for user_id %d!' % user_id)
                continue

            account_creation_time = user.get('account_creation_time', 0)
            if account_creation_time < 1:
                sys.stderr.write('no account_creation_time for user %d\n' % user_id)
                continue

            if user_id not in spend:
                sys.stderr.write('user id mismatch on file %s!' % filename)
                continue

            purchase_list = spend[user_id]
            last_purchase_time = -1
            spent_by_day = {}
            for purchase in purchase_list:
                last_purchase_time = max(last_purchase_time, purchase[0])
                daynum = int((purchase[0] - account_creation_time)/(60*60*24))
                key = str(daynum)
                if key not in spent_by_day:
                    spent_by_day[key] = 0.0
                spent_by_day[key] += purchase[1]

            #print 'user', user_id, 'spent_by_day', spent_by_day, 'last_purchase_time', last_purchase_time

            if do_write:
                player['history']['money_spent_by_day'] = spent_by_day
                if last_purchase_time > 0:
                    player['history']['last_purchase_time'] = last_purchase_time
                generation += 1
                player['generation'] = generation
                atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
                atom.fd.write(json.dumps(player, indent=2))
                atom.complete()
            #    db_client.player_cache_update(user_id, props)
            #TEMP[str(user_id)] = props

        except:
            sys.stderr.write('PROBLEM FILE: '+filename+'\n')
            raise
        finally:
            if locked:
                #sys.stderr.write('user %d unlocked\n' % user_id)
                db_client.player_lock_release(user_id, generation, 2)

    sys.stderr.write('\ndone'+('' if do_write else ' (dry run)')+'\n')
    #sys.stderr.write(repr(FIELDS)+'\n')
    #json.dump(TEMP, open('/tmp/zzz.json','w'), indent=2)
    sys.exit(0)


