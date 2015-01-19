#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Sobol sequence generator
# super-cheesy, it just uses a table

import gzip

class Sobol (object):
    TABLES = {0: 'sobol_02_10000.txt.gz',
              16384: 'sobol_02_10000_a.txt.gz'}

    def __init__(self, dimensions=1, skip=0):
        # make sure the table has what we need
        assert dimensions == 2
        assert skip in self.TABLES
        self.dimensions = dimensions
        self.skip = skip
        self.table = []
        for line in gzip.GzipFile(self.TABLES[skip]).readlines():
            if line[0] == '#': continue
            point = map(float, filter(lambda x: len(x)>0, line.split(' ')))
            self.table.append(point)
        assert len(self.table) == 10000

    def get(self, num):
        assert num >= 0 and num < 10000
        return self.table[num]


if __name__ == '__main__':
    s = Sobol(dimensions=2, skip=0)
    print [s.get(x) for x in xrange(16)]
    s = Sobol(dimensions=2, skip=16384)
    print [s.get(x) for x in xrange(16)]
