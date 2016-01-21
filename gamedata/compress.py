#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# make a JSON file as compact as possible
# WITHOUT changing the order of dictionary keys

# note: requires Python 2.7 :(

import sys

#try:
#    import simplejson as json
#except:
#    import json
#import collections

#try:
# json.dump(json.load(sys.stdin, object_pairs_hook=collections.OrderedDict), sys.stdout, separators=(',',':'))
#except:
#    sys.exit(1)

for line in sys.stdin.readline():
    sys.stdout.write(line)
