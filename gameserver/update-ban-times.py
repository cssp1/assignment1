#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Go through the live PlayerDB and find accounts that need to be re-banned
# because they were originally banned for only 1 year, and never un-banned.

import sys, getopt, traceback, time
import SpinConfig
import SpinUserDB, SpinJSON, SpinS3
import SpinNoSQL
import SpinSingletonProcess
import SpinParallel
import ControlAPI

time_now = int(time.time())

BAN_TIME = 98*365*86400 # 98 years

class Sender(object):
    def __init__(self, db_client, dry_run = True, msg_fd = None):
        self.db_client = db_client
        self.dry_run = dry_run
        self.seen = 0
        self.eligible = 0
        self.sent = 0
        self.msg_fd = msg_fd

    def update_user(self, user_id, index = -1, total_count = -1, test_mode = False):
        global time_now

        print >> self.msg_fd, '(%6.2f%%) %7d' % (100*float(index+1)/float(total_count), user_id),

        self.seen += 1

        try:
            player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))

        except SpinS3.S3404Exception:
            # missing data - might be due to an S3 failure
            print >> self.msg_fd, '(playerDB data missing)'
            return

        if player.get('banned_until', -1) <= 0:
            print >> self.msg_fd, '(not banned)'
            return
        elif player['banned_until'] >= time_now + BAN_TIME:
            print >> self.msg_fd, '(already banned for a long time)'
            return

        self.eligible += 1

        if self.dry_run:
            print >> self.msg_fd, '(dry run, not sending)'
        if not self.dry_run:
            try:
                response = ControlAPI.CONTROLAPI({'method': 'ban', 'user_id': user_id,
                                                  'reason': 'update-ban-times.py', 'ui_reason': 'Extension of original 1-year ban time'},
                                                 'update-ban-times.py', max_tries = 1)
                print >> self.msg_fd, 'CONTROLAPI Sent! Response:', response

            except ControlAPI.ControlAPIException as e:
                print >> self.msg_fd, 'ControlAPIException', e
            except ControlAPI.ControlAPIGameException as e:
                if 'user not found' in e.ret_error or \
                   'player not found' in e.ret_error:
                    # userdb/playerdb entry not found. Mark uninstalled in pcache so we don't attempt to process this user again.
                    self.db_client.player_cache_update(user_id, {'uninstalled': time_now})
                else:
                    print >> self.msg_fd, 'ControlAPIGameException', e

            self.sent += 1

    def finish(self):
        print >> self.msg_fd, 'saw', self.seen, 'players,', self.eligible, 'eligible,', self.sent, 'sent'

def connect_to_db():
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']), identity = 'update-ban-times.py')
    nosql_client.set_time(time_now)
    return nosql_client

class NullFD(object):
    def write(self, stuff): pass

def run_batch(batch_num, total_batches, batch, batch_size, total_count, limit, dry_run, verbose, test_mode):
    msg_fd = sys.stderr if verbose else NullFD()

    # reconnect to DB to avoid subprocesses sharing connections
    db_client = connect_to_db()

    sender = Sender(db_client, dry_run = dry_run, msg_fd = msg_fd)
    for i in xrange(len(batch)):
        try:
            sender.update_user(batch[i], index = batch_size*batch_num + i, total_count = total_count, test_mode = test_mode)
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
    run_batch(input['batch_num'], input['total_batches'], input['batch'], input['batch_size'], input['total_count'], input['limit'], input['dry_run'], input['verbose'], input['test_mode'])

# main program
if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(my_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['dry-run','test', 'limit=','parallel=','quiet'])
    dry_run = False
    test_mode = False
    limit = -1
    parallel = -1
    verbose = True

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

    with SpinSingletonProcess.SingletonProcess('update-ban-times-%s' % (SpinConfig.config['game_id'],)):

        db_client = connect_to_db()

        if test_mode:
            id_list = [1111, 1112, 1114, 1115, 1179934, 1179935, 1179943]

        else:
            user_id_range = db_client.get_user_id_range()
            if verbose: print 'user_id_range', user_id_range
            id_list = range(user_id_range[0], user_id_range[1]+1)

        total_count = len(id_list)

        batch_size = total_count // 20 # break into batches for parallelism
        batch_size = min(max(batch_size, 1), 1000) # never less than 1 or more than 1000

        batches = [id_list[i:i+batch_size] for i in xrange(0, len(id_list), batch_size)]

        if verbose: print 'total_count %d users -> %d batches' % (total_count, len(batches))

        if parallel <= 1:
            for batch_num in xrange(len(batches)):
                run_batch(batch_num, len(batches), batches[batch_num], batch_size, total_count, limit, dry_run, verbose, test_mode)
        else:
            SpinParallel.go([{'batch_num':batch_num,
                              'total_batches':len(batches),
                              'batch':batches[batch_num],
                              'batch_size':batch_size,
                              'total_count':total_count,
                              'limit':limit, 'verbose':verbose,
                              'test_mode': test_mode,
                              'dry_run':dry_run} for batch_num in xrange(len(batches))],
                            [sys.argv[0], '--slave'],
                            on_error = 'break', nprocs=parallel, verbose = False)

