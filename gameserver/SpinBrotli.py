#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Wrapper for the "brotlipy" package that wraps Google's Brotli compressor

import sys

# optional brotli compression
try:
    import brotli
    has_brotli = True
except ImportError:
    sys.stderr.write('brotli module not found, br compression disabled\n')
    has_brotli = False

def enabled(): return has_brotli

if __name__ == '__main__':
    import getopt
    mode = 'compress'

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'cd')
    for key, val in opts:
        if key == '-d': mode = 'decompress'

    # stdin -> stdout
    input = sys.stdin.read()

    if mode == 'compress':
        output = brotli.compress(input)
    else:
        output = brotli.decompress(input)

    sys.stdout.write(output)
