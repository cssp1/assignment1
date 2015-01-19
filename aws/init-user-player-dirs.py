#!/usr/bin/python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os

# initialize userdb/playerdb storage by creating user_id hash bucket directories
# split among the available volumes

VOLS=5
NHASH=100
dirs_per_vol = NHASH/VOLS
assert dirs_per_vol * VOLS == NHASH

# assign hash buckets to volumes by round-robin permutation
perm = [[] for i in xrange(VOLS)]
v = 0
for i in xrange(NHASH):
    perm[v].append(i)
    v = (v+1) % VOLS

for kind in ['user', 'player']:
    for vnum in xrange(VOLS):
        base = '/storage/mfprod-%sA%d' % (kind, vnum)
        for bucket in perm[vnum]:
            newdir = base + '/%s%02d' % (kind,bucket)
            if not os.path.exists(newdir):
                print 'MKDIR', newdir
                os.mkdir(newdir)
