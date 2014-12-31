#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Enforce strict whitespace conventions

import sys, os, re, getopt
#import sys, cStringIO

# do not descend into directories with these names
IGNORE_DIRS = {'.svn','.git', # SCM data
               'userdb','playerdb','basedb','aistate','db','art','built', # server state
               'logs','ujson','pysvg','dowser','google', # third-party
               }

def dir_filter(name):
    return (name not in IGNORE_DIRS) and \
           (not is_ai_base_dir(name))

# don't bother checking raw AI base contents
def is_ai_base_dir(name):
    return ('_ai_bases_' in name) or ('_hives_' in name) or name.endswith('_quarries') or name.endswith('_hives')

# only process files named with these endings
FILE_EXTENSIONS = {'html','js','json','php','pl','po','pot','py','sh','skel','sql','txt'}
IGNORE_FILES = {'config.json', 'ses-send-email.pl'}

def file_filter(name):
    return ('.' in name) and \
           (name.split('.')[-1] in FILE_EXTENSIONS) and \
           (name not in IGNORE_FILES)

trailing_whitespace = re.compile('[ \t]+$')
tabs = re.compile('\t')

def process(fullpath, do_fix, check_tabs, check_trailing):
    fd = open(fullpath, 'r')
    linenum = 0
    need_fix = False
    for line in fd:
        if linenum == 0 and ('AUTO-GENERATED FILE' in line): # skip auto-generated files
            return

        if check_trailing:
            newline = trailing_whitespace.sub('', line)
            if newline != line:
                print 'TRAILING WHITESPACE', fullpath+':'+str(linenum)+': ', line,
                need_fix = True
        else:
            newline = line

        if check_tabs:
            newline2 = tabs.sub('    ', newline)
            if newline2 != newline:
                print 'TABS', fullpath+':'+str(linenum)+': ', line,
                need_fix = True
        else:
            newline2 = newline

        linenum += 1
    fd.close()

    if do_fix and need_fix:
        fd = open(fullpath, 'r')
        temp_filename = fullpath + '.inprogress'
        out = open(temp_filename, 'w')
        try:
            for line in fd:
                if check_trailing:
                    line = trailing_whitespace.sub('', line)
                if check_tabs:
                    line = tabs.sub('    ', line)
                out.write(line)
            out.flush()
            os.rename(temp_filename, fullpath)
            out.close()
            temp_filename = None
        finally:
            if temp_filename:
                os.unlink(temp_filename)

if __name__ == '__main__':
    do_fix = False
    check_tabs = True
    check_trailing = True

    opts, args = getopt.gnu_getopt(sys.argv, '', ['fix','tabs','trailing-whitespace'])
    for key, val in opts:
        if key == '--fix': do_fix = True
        elif key == '--tabs': check_tabs = True
        elif key == '--trailing-whitespace': check_trailing = True

    if not (check_tabs or check_trailing):
        print 'need at least one of: --tabs, --trailing-whitespace'
        sys.exit(1)

    if len(args) >= 2:
        root = args[1]
    else:
        root = '.'

    for dirpath, dirnames, filenames in os.walk(root):
        # note: have to modify dirnames in place
        dirnames[:] = filter(dir_filter, dirnames)
        filenames = filter(file_filter, filenames)
        for name in filenames:
            process(dirpath+'/'+name, do_fix, check_tabs, check_trailing)

