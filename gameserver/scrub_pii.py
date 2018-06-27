#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Scrub personal information from old inactive accounts

# Note: this queries the live player cache to determine who is "inactive"
# and applies the scrubbing to the live userdb via CONTROLAPI.

# This will NOT clear any personal data left over in the analytics SQL database, or any backups.

import sys, getopt, traceback, time
import SpinConfig
import SpinNoSQL
import SpinSingletonProcess
import SpinParallel
import ControlAPI

# scrub PII when last login time was more than this many seconds ago
MAX_AGE = 365*86400 # 365 days

# break users into batches for parallel processing
BATCH_SIZE = 1000

time_now = int(time.time())

class Sender(object):
    def __init__(self, db_client, dry_run = True, msg_fd = None):
        self.db_client = db_client
        self.dry_run = dry_run
        self.seen = 0
        self.eligible = 0
        self.sent = 0
        self.msg_fd = msg_fd
        self.active_platforms = []
        if SpinConfig.config.get('enable_facebook', False): self.active_platforms.append('fb')
        if SpinConfig.config.get('enable_battlehouse', False): self.active_platforms.append('bh')
        if SpinConfig.config.get('enable_armorgames', False): self.active_platforms.append('ag')
        if SpinConfig.config.get('enable_kongregate', False): self.active_platforms.append('kg')

    # pass in the player_cache entry
    def notify_user(self, user_id, pcache, index = -1, total_count = -1, only_frame_platform = None, test_mode = False):
        global time_now

        self.seen += 1

        frame_platform = pcache.get('frame_platform', 'fb')
        # for testing purposes, skip everything not on this platform
        if only_frame_platform is not None and frame_platform != only_frame_platform:
            return

        print >> self.msg_fd, '(%6.2f%%) %7d' % (100*float(index+1)/float(total_count), user_id),

        if pcache.get('social_id') in (None, -1, '-1', 'ai'): # skip AIs
            print >> self.msg_fd, '(player_cache says) AI player'
            return

        if (not test_mode) and frame_platform not in self.active_platforms:
            print >> self.msg_fd, '(player_cache says) frame_platform is not active'
            return

        if pcache.get('uninstalled',0):
            print >> self.msg_fd, '(player_cache says) player already uninstalled'
            return

        # check the last seen time.
        # last_logout_time is most accurate, but we only started tracking it recently.
        # last_login_time is also missing on some old accounts.
        # last_mtime is reliable, but note it will include mutations to player data that happened for reasons other than a login.
        last_seen_time = pcache.get('last_logout_time', -1)
        if last_seen_time < 0:
            last_seen_time = pcache.get('last_login_time', -1)
            if last_seen_time < 0:
                last_seen_time = pcache.get('last_mtime', -1)

        if last_seen_time < 0:
            print >> self.msg_fd, '(player_cache says) no last_logout_time or last_login_time or last_mtime'
            return

        if (not test_mode) and (time_now - last_seen_time) < MAX_AGE:
            print >> self.msg_fd, '(player_cache says) player was playing less than %d days ago' % (MAX_AGE/86400)
            return

        self.eligible += 1

        if self.dry_run:
            print >> self.msg_fd, '(dry run, not sending)'
        if not self.dry_run:
            try:
                response = ControlAPI.CONTROLAPI({'method': 'mark_uninstalled', 'user_id': user_id,
                                                  'reason': 'scrub_pii.py', 'ui_reason': 'Has not logged in for %d days' % (MAX_AGE/86400)},
                                                 'scrub_pii', max_tries = 1)
                print >> self.msg_fd, 'CONTROLAPI Sent! Response:', response

            except ControlAPI.ControlAPIException as e:
                print >> self.msg_fd, 'ControlAPIException', e
            except ControlAPI.ControlAPIGameException as e:
                print >> self.msg_fd, 'ControlAPIGameException', e

            self.sent += 1

    def finish(self):
        print >> self.msg_fd, 'saw', self.seen, 'players,', self.eligible, 'eligible,', self.sent, 'sent'

def connect_to_db():
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'scrub_pii.py')
    nosql_client.set_time(time_now)
    return nosql_client

class NullFD(object):
    def write(self, stuff): pass

def run_batch(batch_num, total_batches, batch, total_count, limit, dry_run, verbose, only_frame_platform, test_mode):
    msg_fd = sys.stderr if verbose else NullFD()

    # reconnect to DB to avoid subprocesses sharing conenctions
    db_client = connect_to_db()

    sender = Sender(db_client, dry_run = dry_run, msg_fd = msg_fd)
    pcache_list = db_client.player_cache_lookup_batch(batch, fields = ['frame_platform', 'social_id', 'country', 'last_login_time', 'last_logout_time', 'last_mtime', 'uninstalled'])
    for i in xrange(len(batch)):
        try:
            sender.notify_user(batch[i], pcache_list[i], index = BATCH_SIZE*batch_num + i, total_count = total_count, only_frame_platform = only_frame_platform, test_mode = test_mode)
        except KeyboardInterrupt:
            raise # allow Ctrl-C to abort
        except Exception as e:
            sys.stderr.write('error processing user %d: %r\n%s\n'% (batch[i], e, traceback.format_exc()))

        if limit >= 0 and ((not dry_run and sender.sent >= limit) or (dry_run and sender.eligible >= limit)):
            print >> msg_fd, 'limit reached'
            break

    print >> msg_fd, 'batch %d of %d done' % (batch_num+1, total_batches)
    sender.finish()

def my_slave(input):
    run_batch(input['batch_num'], input['total_batches'], input['batch'], input['total_count'], input['limit'], input['dry_run'], input['verbose'], input['only_frame_platform'], input['test_mode'])

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

    with SpinSingletonProcess.SingletonProcess('scrub-pii-%s' % (SpinConfig.config['game_id'],)):

        db_client = connect_to_db()

        if test_mode:
            id_list = [1111, 1112, 1114, 1115, 1179934, 1179935, 1179943]

        else:
            if verbose: print 'querying player_cache...'
            id_list = db_client.player_cache_query_not_uninstalled_and_not_logged_in_since(time_now - MAX_AGE)

        id_list.sort(reverse=True)
        total_count = len(id_list)

        batches = [id_list[i:i+BATCH_SIZE] for i in xrange(0, len(id_list), BATCH_SIZE)]

        if verbose: print 'player_cache_query returned %d users -> %d batches' % (total_count, len(batches))

        if parallel <= 1:
            for batch_num in xrange(len(batches)):
                run_batch(batch_num, len(batches), batches[batch_num], total_count, limit, dry_run, verbose, only_frame_platform, test_mode)
        else:
            SpinParallel.go([{'batch_num':batch_num,
                              'total_batches':len(batches),
                              'batch':batches[batch_num],
                              'total_count':total_count,
                              'limit':limit, 'verbose':verbose, 'only_frame_platform': only_frame_platform,
                              'test_mode': test_mode,
                              'dry_run':dry_run} for batch_num in xrange(len(batches))],
                            [sys.argv[0], '--slave'],
                            on_error = 'break', nprocs=parallel, verbose = False)

