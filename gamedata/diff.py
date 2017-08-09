#!/usr/bin/env python

import GameDataUtil

if __name__ == '__main__':
    import sys, os, getopt
    import SpinJSON

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])
    for key, val in opts:
        pass

    if len(args) < 2:
        print 'usage: diff.py gamedata-a.json gamedata-b.json'
        sys.exit(1)

    gamedata_a = SpinJSON.load(open(args[0]))
    gamedata_b = SpinJSON.load(open(args[1]))

    TOPLEVELS = ['buildings','units','tech','enhancements']
    ret = {}

    for top in TOPLEVELS:
        diff = GameDataUtil.diff_game_objects(gamedata_a[top], gamedata_b[top])
        if diff:
            ret[top] = diff

    SpinJSON.dump(ret, sys.stdout, pretty = True, newline = True)
