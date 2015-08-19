#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# get_region_names.py - guess what this script does!

import SpinJSON, SpinConfig
gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

for name, data in gamedata['regions'].iteritems():
    if data.get('developer_only', False): continue
    print name,
print
