#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# migrate userdb/playerdb files from flat 100,000-file directory
# to hash-bucketed directories

# kind of like rsync, but hashes the files into the right place as it copies

import SpinConfig
import SpinUserDB
import os, shutil, sys

sys.exit(1) # this is obsolete, do not use

verbose = False

id_range = SpinUserDB.driver.get_user_id_range()

NHASH=100
def user_id_bucket(id):
        return id % NHASH

total = id_range[1]-id_range[0]+1

count = 0

for id in xrange(id_range[0], id_range[1]+1):
        print_every = 1 if verbose else 100
        if (count % print_every) == 0 or id == id_range[1]:
                print '%d/%d (%.2f%%)' % (count+1, total, 100.0*float(count+1)/total)

        src_user = SpinUserDB.driver.get_user_path(id)
        src_player = SpinUserDB.driver.get_player_path(id)

        bucket = user_id_bucket(id)

        dst_user = os.path.join('userdbNEW', 'user%02d' % bucket, str(id)+'.txt')
        dst_player = os.path.join('playerdbNEW', 'player%02d' % bucket, str(id)+'_'+SpinConfig.config['game_id']+'.txt')

        if verbose: print src_user, '->', dst_user,
        if os.path.exists(src_user) and (not os.path.exists(dst_user) or int(os.path.getmtime(src_user)) > int(os.path.getmtime(dst_user))):
                # NOTE: use copy2 to preserve permissions and times
                shutil.copy2(src_user, dst_user)
                if verbose: print 'COPY'
        else:
                if verbose: print 'SKIP'
        if verbose: print src_player, '->', dst_player,
        if os.path.exists(src_player) and (not os.path.exists(dst_player) or int(os.path.getmtime(src_player)) > int(os.path.getmtime(dst_player))):
                shutil.copy2(src_player, dst_player)
                if verbose: print 'COPY'
        else:
                if verbose: print 'SKIP'
        count += 1
