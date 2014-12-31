#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# This script compiles a JSON file with comments and #include
# directives into a flat (spec-conforming) JSON file. It is used to
# pre-process gamedata_main.json into the big flat gamedata.json used
# by the client and server.

try: import simplejson as json
except: import json

import AtomicFileWrite
import sys, re, traceback, os, time, getopt

# regular expression that matches C++-style comments
# this is kind of an ugly regex, basically it's hard to detect and ignore // that appear within quoted strings
# so we have a special exception that recognizes http://, https://, "//" (at beginning of JSON string), and href="//..." as NOT being comment starters
comment_remover = re.compile('(?<!tp:|ps:|: "|":"|=\\\\")//.*?$')

# regular expression that detects #include "foo" directives
include_detector = re.compile('^#include "(.+)"')
include_stripped_detector = re.compile('^#include_stripped "(.+)"')
build_info_detector = re.compile('\$GAMEDATA_BUILD_INFO\$')
spin_gameclient = os.getenv('SPIN_GAMECLIENT'); assert spin_gameclient

profile = False

def filename_replace_vars(filename, game_id):
    filename = filename.replace('$GAME_ID', game_id)
    filename = filename.replace('$SPIN_GAMECLIENT', spin_gameclient)
    return filename

# parse_input()

# Read JSON from Python file object 'fd', removing comments and
# processing include directives recursively. Returns the processed
# contents of the file as a string.

# If 'stripped' is true, then assume that the file contains the
# "inner" part of a JSON dictionary without the surounding curly
# braces. (this allows a master file to build a single dictionary by
# combining several different individual "stripped" JSON subfiles).

def parse_input_subfile(filename, game_id, build_info, depth = 0, stripped = False):
    start_time = time.time()

    filename = filename_replace_vars(filename, game_id)
#    if profile: print >> sys.stderr, 'subfile', '  '*depth, filename, '...'

    dir = os.path.dirname(filename) or '.'

    base = os.path.basename(filename)
    save_dir = os.getcwd()

    #sys.stderr.write('CWD %s FILENAME %s DIR %s BASE %s stripped %d\n' % (save_dir, filename, dir,base, int(stripped)))

    try:
        os.chdir(dir)
        fd = open(base)
        if filename.endswith('compiled.json'):
            ret = fd.read()
            direct = True
        else:
            ret = parse_input(fd, filename, game_id, build_info, depth = depth, stripped = stripped)
            direct = False
        end_time = time.time()

        if profile: print >> sys.stderr, 'subfile', '  '*depth, filename, '...', len(ret), 'bytes', '%.1f ms' % (1000.0*(end_time-start_time)), '(direct)' if direct else ''

    finally:
        os.chdir(save_dir)
    return ret

# in order to return location details on WHERE dupes occurred, we have
# to allow the dict to be created, then look at it later
def dict_mark_dupes(pairs):
    seen = set()
    dupes = {}
    ret = {}
    for k, v in pairs:
        if k not in seen:
            seen.add(k)
            ret[k] = v
            continue
        else:
            if k not in dupes: dupes[k] = [ret[k]]
            dupes[k].append(v)
            ret[k] = v
    if dupes:
        ret['_DUPES'] = dupes
    return ret

def dict_check_dupes(root, path=''):
    if type(root) is dict:
        if '_DUPES' in root:
            for k, vlist in root['_DUPES'].iteritems():
                raise ValueError('duplicate dictionary key: "%s": "%s" has multiple values: %s' % (path, k, str(vlist)))
        for k, v in root.iteritems():
            dict_check_dupes(v, '%s%s' % ((path+'/') if path else '',k))
    elif type(root) is list:
        [dict_check_dupes(root[i], '%s[%d]' % (path,i)) for i in xrange(len(root))]


def parse_input(fd, myname, game_id = None, build_info = None, stripped = False, depth = 0):
    # accumulate output here (with no whitespace)
    ret = ''

    # accumulate a version of output with whitespace and line breaks
    # preserved, *for syntax checking only* (to give accurate error messages)
    check_ret = ''
    if stripped: check_ret += '{'

    # read input one line at a time
    for line in fd.xreadlines():
        # remove trailing whitespace
        line = line.rstrip()

        # remove C++-style comments
        line = comment_remover.sub('', line)

        if build_info: line = build_info_detector.sub(build_info, line)

        check_line = line

        # remove leading whitespace
        line = line.lstrip()

        # detect #include directives
        match = include_detector.search(line)
        if match:
            # get the name of the file to include from the regular expression
            filename = match.group(1)

            # replace the line with the contents of the included file
            line = parse_input_subfile(filename, game_id, build_info, depth = depth+1)
            check_line = line

        match = include_stripped_detector.search(line)
        if match:
            filename = match.group(1)
            line = parse_input_subfile(filename, game_id, None, depth = depth+1, stripped = True) # do not pass build_info down into subfiles
            check_line = line

        # accumulate output
        ret += line

        # preserve line breaks in check_ret so that parsing errors
        # refer to the correct line number
        check_ret += check_line + '\n'

    if stripped: check_ret += '}'

    # test syntax by running the JSON parser on the string
    try:
        temp = json.loads(check_ret, object_pairs_hook = dict_mark_dupes)
        dict_check_dupes(temp)
    except ValueError as e:
        errmsg = 'JSON syntax error in \"'+myname+'\": '+str(e)
        raise Exception(errmsg)

    return ret

# DEPENDENCY EXTRACTION

# return a recursive dictionary of dependencies of this JSON file
def get_deps_from(fd, game_id, prefix = '.'):
    ret = {}
    for line in fd.xreadlines():
        # remove leading whitespace
        line = line.lstrip()
        # detect includes
        match = include_detector.search(line) or include_stripped_detector.search(line)
        if match:
            relative_filename = filename_replace_vars(match.group(1), game_id)
            relative_dir = os.path.dirname(relative_filename) or '.'
            base = os.path.basename(relative_filename)

            if relative_dir.startswith('/'): # absolute path
                child_prefix = relative_dir
                ret_key = relative_filename
            elif relative_dir == '.': # no change in path
                child_prefix = prefix
                ret_key = prefix + '/' + relative_filename
            else:
                child_prefix = prefix+'/'+relative_dir
                ret_key = prefix + '/' + relative_filename

            save_dir = os.getcwd()
            try:
                os.chdir(relative_dir)
                if relative_dir.endswith('built'): # or relative_filename.endswith('art_auto.json'):
                    child_deps = {} # do not recurse on built files
                else:
                    child_deps = get_deps_from(open(base), game_id, prefix = child_prefix)
                ret[ret_key] = child_deps
            finally:
                os.chdir(save_dir)
    return ret

def format_deps_tree(in_filename, tree, toplevel = False):
    ret = ''
    children = sorted(tree.keys())
    for child in children:
        if tree[child]:
            ret = ret + ('\n' if ret else '') + format_deps_tree(child, tree[child])

    ret += ('\n' if ret or toplevel else '')
    ret += '%s: ' % in_filename + ' '.join(children) + '\n'
    return ret

def flatten_deps(tree):
    ret = set(tree.iterkeys())
    for val in tree.itervalues():
        if val:
            ret.update(flatten_deps(val))
    return ret

def simplify_path(name, base_path):
    if '/' not in name: return name
    comps = os.path.normpath(os.path.join(base_path, name)).split('/')
    base = os.path.normpath(base_path).split('/')+['.']
    common = []
    remain = []
    dots = 0
    for i in xrange(min(len(comps),len(base))):
        if comps[i] == base[i]:
            common.append(comps[i])
        else:
            remain = comps[i:]
            dots = len(base) - i - 1
            break
    final = '../'*dots
    final += '/'.join(remain)
    #sys.stderr.write("HERE name %s base %s common %s dots %d final %s\n" % (comps, base, common, dots, final))
    return final

def format_deps_flat(in_filename, tree, base_path = None):
    deps = sorted(list(flatten_deps(tree)))
    deps = map(lambda x: simplify_path(x, base_path), deps)
    return '%s: ' % in_filename + ' \\\n\t'.join(deps) + '\n'

# by default, use stdin for input
if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'o:g:', ['game-id=','repeatable','get-deps','get-deps-as=','profile'])
    repeatable = False
    get_deps = False
    get_deps_as = None
    in_filename = '-'
    out_filename = '-'
    for key, val in opts:
        if key == '-g' or key == '--game-id': game_id = val
        elif key == '--repeatable': repeatable = True
        elif key == '--get-deps': get_deps = True
        elif key == '--get-deps-as': get_deps_as = val
        elif key == '-o': out_filename = val
        elif key == '--profile': profile = True

    time_now = int(time.time())
    ident = str(os.getpid())
    build_info = '{"date":"REPEATABLE","time":0}' if repeatable else json.dumps({'date': time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(time_now)), 'time': time_now})

    if args:
        assert len(args) == 1
        in_filename = args[0]

    save_dir = os.getcwd()

    try:
        if '/' in in_filename:
            in_dirname = os.path.dirname(in_filename)
            in_basename = os.path.basename(in_filename)
            os.chdir(in_dirname)
        else:
            in_dirname = '.'
            in_basename = in_filename

        in_file = sys.stdin if in_filename == '-' else open(in_basename)

        if get_deps:
            out = format_deps_flat(get_deps_as or in_filename, get_deps_from(in_file, game_id, prefix = in_dirname), base_path = save_dir)
        else:
            out = parse_input(in_file, in_filename, game_id, build_info)

        os.chdir(save_dir)

        if out_filename == '-':
            print out,
            if not get_deps: print
        else:
            atom = AtomicFileWrite.AtomicFileWrite(out_filename, 'w', ident=ident)
            atom.fd.write(out)
            if not get_deps: atom.fd.write('\n')
            atom.complete()
    except Exception as e:
        sys.stderr.write(str(e)+'\n')
        #sys.stderr.write(traceback.format_exc())
        os.chdir(save_dir)
        sys.exit(1)
