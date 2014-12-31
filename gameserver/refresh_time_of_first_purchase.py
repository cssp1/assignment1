#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# reconstruct missing time_of_first_purchase field for player.history based on credits log

try:
    import simplejson as json
except:
    import json
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
    spend = {} # map from user_id to time
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
                t = int(met['time'])
                if user_id not in spend:
                    spend[user_id] = t
                else:
                    spend[user_id] = min(spend[user_id], t)


    file_list = [playerdb_dir+('/%d_%s.txt' % (uid, game_id)) for uid in spend.iterkeys()]
    counter = 0
    #TEMP = {}

    for filename in file_list:
        counter += 1
        sys.stderr.write('file %d of %d (%.2f%%) user_id...\n' % (counter, len(file_list), 100.0*(counter/float(len(file_list)))))

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
                if db_client.player_lock_acquire_attack(user_id) < 0:
                    sys.stderr.write('could not acquire write lock on user_id %d, skipping\n' % user_id)
                    continue
                else:
                    sys.stderr.write('user %d locked\n' % user_id)
                    locked = True

            if 'history' not in player:
                player['history'] = {}

            if 'time_of_first_purchase' in player['history']:
                sys.stderr.write('user %d already has time_of_first_purchase data, skipping\n' % user_id)
                continue

            if user_id not in spend:
                sys.stderr.write('user id mismatch on file %s!' % filename)
                continue

            print 'user', user_id, 'time_of_first_purchase', spend[user_id]

            if do_write:
                player['history']['time_of_first_purchase'] = spend[user_id]
                atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
                atom.fd.write(json.dumps(player, indent=2))
                atom.fd.write('\n')
                atom.complete()

        except:
            sys.stderr.write('PROBLEM FILE: '+filename+'\n')
            raise
        finally:
            if locked:
                sys.stderr.write('user %d unlocked\n' % user_id)
                db_client.player_lock_release(user_id, 2)

    #sys.stderr.write(repr(FIELDS)+'\n')
    #json.dump(TEMP, open('/tmp/zzz.json','w'), indent=2)
    sys.exit(0)


