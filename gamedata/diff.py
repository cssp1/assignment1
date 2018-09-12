#!/usr/bin/env python

# this tool compares two gamedata.json files and reports any differences found.

import GameDataUtil

def diff_recursive(a, b):
    ret = None
    if isinstance(a, dict):
        if not isinstance(b, dict):
            return 'type mismatch, type(a)=%s, type(b)=%s' % (type(a), type(b))
        ret = {}
        for k, v in a.iteritems():
            x = diff_recursive(a[k], b.get(k, None))
            if x:
                ret[k] = x
        return ret
    elif isinstance(a, list):
        if not isinstance(b, list):
            return 'type mismatch, type(a)=%s, type(b)=%s' % (type(a), type(b))
        if len(b) != len(a):
            return 'list length mismatch, len(a)=%d len(b)=%d' % (len(a), len(b))
        ret = {}
        for i, elem in enumerate(a):
            x = diff_recursive(a[i], b[i])
            if x:
                ret['[%d]' % i] = x
        return ret
    else:
        if a != b:
            return '%s != %s' % (a, b)

if __name__ == '__main__':
    import sys, getopt
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

    diff = diff_recursive(gamedata_a['store'], gamedata_b['store'])
    if diff:
        ret['store'] = diff

    crafting_recipes_diff = GameDataUtil.diff_game_objects(gamedata_a['crafting']['recipes'], gamedata_b['crafting']['recipes'])
    if crafting_recipes_diff:
        ret['crafting'] = {'recipes': crafting_recipes_diff}

    if ret:
        print 'Differences found:'
        SpinJSON.dump(ret, sys.stdout, pretty = True, newline = True)
        sys.exit(1)
    else:
        print 'Files are identical!'
        sys.exit(0)
