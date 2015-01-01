#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Enforce strict whitespace conventions

import sys, os, re, getopt

# FILTERS that control which files we operate on

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

# PROCESSORS for finding and fixing problems

class Processor(object):
    def reset(self): pass
    def applicable(self, filename): return True
    def finalize(self): pass

class DOSLineEndings(Processor):
    ui_name = 'DOS LINE ENDINGS'
    bad_ending = re.compile('\r\n$')
    def fix(self, line):
        return self.bad_ending.sub('\n', line)

class TrailingWhitespace(Processor):
    ui_name = 'TRAILING WHITESPACE'
    trailing_whitespace = re.compile('[ \t]+$')
    def fix(self, line):
        return self.trailing_whitespace.sub('', line)

class Tabs(Processor):
    ui_name = 'TABS'
    tabs = re.compile('\t')
    def fix(self, line):
        return self.tabs.sub('    ', line)

def process(fullpath, do_fix, processors):
    fd = open(fullpath, 'r')
    linenum = 0
    need_fix = False

    for line in fd:
        if linenum == 0 and ('AUTO-GENERATED FILE' in line): # skip auto-generated files
            return

        for proc in processors:
            newline = proc.fix(line)
            if newline != line:
                print proc.ui_name, fullpath+':'+str(linenum)+': ', line,
                need_fix = True
                line = newline
        linenum += 1

    fd.close()
    for proc in processors: proc.finalize()

    # optional second pass to fix problems
    if do_fix and need_fix:
        for proc in processors: proc.reset()
        fd = open(fullpath, 'r')
        temp_filename = fullpath + '.inprogress'
        out = open(temp_filename, 'w')
        try:
            for line in fd:
                for proc in processors:
                    line = proc.fix(line)
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
    processors = []

    opts, args = getopt.gnu_getopt(sys.argv, '', ['fix','tabs','trailing-whitespace','dos-line-endings','all'])
    for key, val in opts:
        if key == '--fix': do_fix = True
        elif key == '--tabs': processors.append(Tabs())
        elif key == '--trailing-whitespace': processors.append(TrailingWhitespace())
        elif key == '--dos-line-endings': processors.append(DOSLineEndings())

    if not processors:
        processors = [Tabs(), TrailingWhitespace(), DOSLineEndings()]

    if len(args) >= 2:
        root = args[1]
    else:
        root = '.'

    if os.path.isfile(root):
        it = [('.', [], [root])]
    else:
        it = os.walk(root)

    for dirpath, dirnames, filenames in it:
        # note: have to modify dirnames in place
        dirnames[:] = filter(dir_filter, dirnames)
        filenames = filter(file_filter, filenames)
        for name in filenames:
            for proc in processors: proc.reset()
            process(dirpath+'/'+name, do_fix, filter(lambda proc: proc.applicable(name), processors))

