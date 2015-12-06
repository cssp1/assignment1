#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# reconstruct userdb acquisition_campaign and acquisition_secondary fields for old users
# acquired before the server could trace secondary acquisitions

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

# list of indeterminate acquisition campaigns that we want to get rid of
UNASSIGNED = (None, '', 'facebook_friend_invite', 'facebook_app_request', 'feed_level_up', 'feed_thanks')

MAXDEPTH = 50

time_now = int(time.time())

def get_campaign(user, is_secondary, depth):
    data = user.get('acquisition_data', [])
    for d in data:
        if d['type'] == 'ad_click' and 'campaign_name' in d:
            return (d['campaign_name'], is_secondary)
    for d in data:
        if d['type'] == 'facebook_friend_invite' and 'sender_user_id' in d:
            if depth > MAXDEPTH:
                break
            return get_friend_campaign(int(d['sender_user_id']), depth+1)

    for d in data:
        if d['type'] in ('feed_level_up', 'feed_thanks') and 'referring_user_id' in d:
            if depth > MAXDEPTH:
                break
            return get_friend_campaign(int(d['referring_user_id']), depth+1)

    if len(data) > 0:
        return (data[0]['type'], None)
    return (None, None)

def get_friend_campaign(friend_id, depth):
    try:
        fr = json.load(open(userdb_dir+'/%d.txt' % (friend_id,)))
        return get_campaign(fr, 1, depth)
    except:
        sys.stderr.write('user file missing for user_id %d!' % friend_id)
        return (None, None)

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

    file_list = glob.glob(userdb_dir+'/*.txt')
    file_list = filter(lambda x: 'facebook_id_map' not in x, file_list)
    file_list.sort(key = lambda x: int(x.split('.')[0].split('/')[-1]))
    file_list.reverse() # begin at end

    counter = 0

    for filename in file_list:
        counter += 1
        try:
            locked = False

            user = json.load(open(filename))

            if not user.has_key('user_id'):
                # handle old entries with no inline user_id
                user['user_id'] = int(os.path.basename(filename).split('.')[0])
            user_id = user['user_id']
            if user_id < 1100:
                # AI users
                continue

            sys.stderr.write('\rupdating user %5d of %5d (%6.2f%%) %5d...' % (counter, len(file_list), 100.0*(counter/float(len(file_list))), user_id))

            old_campaign = user.get('acquisition_campaign', None)
            old_secondary = user.get('acquisition_secondary', None)

            if old_campaign not in UNASSIGNED:
                continue

            if do_write:
                if db_client.player_lock_acquire_attack(user_id) < 0:
                    sys.stderr.write('could not acquire write lock on user_id %d, skipping\n' % user_id)
                    continue
                else:
                    sys.stderr.write('user %d locked\n' % user_id)
                    locked = True

            acquisition_campaign, acquisition_secondary = get_campaign(user, 0, 0)

            if old_campaign == 'facebook_app_request' and acquisition_campaign in UNASSIGNED:
                sys.stderr.write('untraceable facebook_app_request!\n')

            if old_campaign != acquisition_campaign and acquisition_campaign not in UNASSIGNED:
                sys.stderr.write(' OLD campaign %-28s secondary %s' % (repr(old_campaign), repr(old_secondary)))
                sys.stderr.write(' NEW campaign %-28s secondary %s\n' % (repr(acquisition_campaign), repr(acquisition_secondary)))

                if do_write:
                    if acquisition_campaign is None:
                        if 'acquisition_campaign' in user:
                            del user['acquisition_campaign']
                    else:
                        user['acquisition_campaign'] = acquisition_campaign

                    if acquisition_secondary is None:
                        if 'acquisition_secondary' in user:
                            del user['acquisition_secondary']
                    else:
                        user['acquisition_secondary'] = acquisition_secondary

                    atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
                    json.dump(user, atom.fd, indent=2)
                    atom.fd.write('\n')
                    atom.complete()

        except:
            sys.stderr.write('PROBLEM FILE: '+filename+'\n')
            raise
        finally:
            if locked:
                sys.stderr.write('user %d unlocked\n' % user_id)
                db_client.player_lock_release(user_id, 2)

    sys.stderr.write('\nDONE\n')
    sys.exit(0)
