#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# example usage of SpinETL to pull old chat log messages from spinpunch-logs S3 bucket

import sys, time, getopt
import SpinConfig
import SpinETL

time_now = int(time.time())

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', [])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    for row in SpinETL.iterate_from_s3(game_id, 'spinpunch-logs', 'chat',
                                       time_now-10*86400, # start 10 days ago
                                       time_now-9*86400, # end 9 days ago
                                       verbose = verbose):
        # * make sure to check the row's "sender": { "type": ... }

        print row
        # put it in a text file?
        # stick it in a database?
