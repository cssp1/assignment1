#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Enforce strict whitespace conventions

import sys, os, stat, re, getopt, cStringIO, traceback

# FILTERS that control which files we operate on

# do not descend into directories with these names
IGNORE_DIRS = set(['.svn','.git', # SCM data
                   'userdb','playerdb','basedb','aistate','db','art','built', # server state
                   'logs','ujson','pysvg','dowser','google', # third-party
                   ])

def dir_filter(name):
    return (name not in IGNORE_DIRS) and \
           (not is_ai_base_dir(name))

# don't bother checking raw AI base contents
def is_ai_base_dir(name):
    return ('_ai_bases_' in name) or ('_hives_' in name) or name.endswith('_quarries') or name.endswith('_hives') \
           or name == 'ai_base_generator'

# only process files named with these endings
FILE_EXTENSIONS = set(['html','js','json','php','pl','po','pot','py','sh','skel','sql','txt'])
IGNORE_FILES = set(['config.json', 'ses-send-email.pl'])

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

class JSONIndent(Processor):
    ui_name = 'INDENT'
    comment_remover = re.compile('(?<!tp:|ps:|: "|":"|=\\\\")//.*?$')

    class State(object):
        NORMAL=0
        QUOTE=1
        QUOTE_SPECIALCHAR=2
#        SYMBOL=3
#        NUMBER=4
        TRAILING_COMMENT=5
    def applicable(self, filename): return filename.endswith('.json')
    def __init__(self): self.reset()
    def reset(self):
        self.state = self.State.NORMAL # lexer state
        self.last_stack = []
        self.stack = [['init',0,0]]
        self.last_indent = 0

    def fix(self, line):
        # horribly, horribly complex state machine that exactly matches Emacs "indent-region" behavior

        if line.startswith('#include'): return line
        src = cStringIO.StringIO(line)
        buf = cStringIO.StringIO()
        old_indent = 0
        indent_ended = False
        begins_with_closer = False
        closer_count = 0

        temp = self.comment_remover.sub('', line).strip()
        ends_with_opener = (temp and temp[-1] in ('[','{')) # XXX bad way to do this
        last_opener = max(line.rfind('['), line.rfind('{')) # XXX bad way to do this

        last_quote_start = -1
        last_key_start = -1

        starting_stack = self.stack[:]
        new_indent = starting_stack[-1][2]

        while True:
            c = src.read(1)
            if not c: break

            peek = src.read(1)
            src.seek(-1, 1)

            # count leading indent characters, but don't append to buf
            if self.state == self.State.NORMAL and (not indent_ended):
                if c == '\t':
                    raise Exception('tab found - fix those first')
                elif c == ' ':
                    old_indent += 1
                    continue # count leading indent characters, but don't append to buf
                else:
                    indent_ended = True

            buf.write(c) # buf will accumulate everything except the leading indent (but including trailing carriage return)
            if c == '\n': break

            pos = old_indent + buf.tell() - 1

            if self.state == self.State.NORMAL:
                if c == '"':
                    self.state = self.State.QUOTE
                    if last_quote_start < 0:
                        last_quote_start = pos
                elif c == '/':
                    assert peek == '/'
                    src.read(1)
                    buf.write('/')
                    self.state = self.State.TRAILING_COMMENT
            elif self.state == self.State.QUOTE:
                if c == '\\':
                    self.state = self.State.QUOTE_SPECIALCHAR
                elif c == '"':
                    self.state = self.State.NORMAL
            elif self.state == self.State.QUOTE_SPECIALCHAR:
                self.state = self.State.QUOTE

            if self.state == self.State.NORMAL:
                jump = 0
                if c in ('[','{'):

                    # check if this is the last non-comment thing OR there's a net depth increase
                    is_final = True
                    while True:
                        ahead = src.read(1)
                        if (not ahead): break
                        jump += 1
                        if ahead in (' ','\t'):
                            continue
                        elif ahead == '\n':
                            break
                        elif ahead == '/': # XXX assumes comment start
                            break
                        else:
                            is_final = False
                            break
                    src.seek(-jump, 1)
                is_final = ends_with_opener

                if c == ':':
                    if last_quote_start >= 0 and last_key_start < 0:
                        last_key_start = last_quote_start
                elif c in ('[','{'):
                    if last_key_start < 0:
                        last_key_start = pos

                    if is_final: # and (pos <= last_opener):
                        if pos < last_opener:
                            q = pos + jump
                        else:
                            q = starting_stack[-1][2] + 4
                    else:
                        q = pos + jump
                    if is_final and (pos >= last_opener) and last_key_start >= 0:
                        p = last_key_start # can't use this if there is a following opener on the same line
                    else:
                        p = pos
                        if last_key_start < 0:
                            last_key_start = p # mark for future openers on this line
                    self.stack.append((c, p, q, is_final, last_key_start))

                elif c in (']','}'):
                    if (not begins_with_closer) and buf.tell() == 1:
                        begins_with_closer = True
                    if begins_with_closer:
                        #sys.stderr.write('PICKING %d %s\n' % (-1, repr(starting_stack[-1])))

                        # note: Emacs actually seems buggy and uses the innermost group instead of outermost here
                        #new_indent = starting_stack[-1-closer_count][1]
                        new_indent = starting_stack[-1][1]

                        closer_count += 1
                    self.stack.pop()


        # done parsing one line
        if self.state == self.State.TRAILING_COMMENT: self.state = self.State.NORMAL

        if buf.tell() > 1:
            new_line = ' '*(new_indent) + buf.getvalue()
        else: # just a blank
            assert buf.getvalue() == '\n'
            new_line = '\n'

        if 0: # or new_line != line:
            sys.stderr.write('in  '+repr(line)+' last %d old %d new %d last %s starting %s stack %s\n' % (self.last_indent, old_indent, new_indent, repr(self.last_stack), repr(starting_stack), repr(self.stack)))
            sys.stderr.write('buf '+repr(buf.getvalue())+'\n')
            sys.stderr.write('out '+repr(new_line)+'\n')

        self.last_indent = new_indent
        self.last_stack = starting_stack

        return new_line

    def finalize(self):
        if self.state != self.State.NORMAL:
            raise Exception('ended in non-normal state')


def process(fullpath, *args, **kwargs):
    try:
        do_process(fullpath, *args, **kwargs)
        return 0
    except:
        sys.stderr.write('error in "%s": %s' % (fullpath, traceback.format_exc()))
    return 1

def do_process(fullpath, do_fix, processors):
    fd = open(fullpath, 'r')
    linenum = 0
    need_fix = False

    for line in fd:
        if linenum == 0 and ('AUTO-GENERATED FILE' in line): # skip auto-generated files
            return

        for proc in processors:
            newline = proc.fix(line)
            if newline != line:
                print proc.ui_name, fullpath+':'+str(linenum+1)+': ', repr(line), ' -> ', repr(newline)
                need_fix = True
                line = newline
        linenum += 1

    fd.close()
    for proc in processors: proc.finalize()

    # optional second pass to fix problems
    if do_fix and need_fix:
        for proc in processors: proc.reset()
        fd = open(fullpath, 'r')
        file_mode = stat.S_IMODE(os.fstat(fd.fileno()).st_mode)
        temp_filename = fullpath + '.inprogress'
        out = open(temp_filename, 'w')
        os.fchmod(out.fileno(), file_mode)
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

    opts, args = getopt.gnu_getopt(sys.argv, '', ['fix','tabs','trailing-whitespace','dos-line-endings','json-indent','all'])
    for key, val in opts:
        if key == '--fix': do_fix = True
        elif key == '--tabs': processors.append(Tabs())
        elif key == '--trailing-whitespace': processors.append(TrailingWhitespace())
        elif key == '--dos-line-endings': processors.append(DOSLineEndings())
        elif key == '--json-indent': processors.append(JSONIndent())

    if not processors:
        processors = [Tabs(), TrailingWhitespace(), DOSLineEndings(), JSONIndent()]

    if len(args) >= 2:
        roots = args[1:]
    else:
        roots = ['.']

    for root in roots:
        if os.path.isfile(root):
            it = [('.', [], [root])]
        else:
            it = os.walk(root, followlinks = True)

        for dirpath, dirnames, filenames in it:
            # note: have to modify dirnames in place
            dirnames[:] = filter(dir_filter, dirnames)
            filenames = filter(file_filter, filenames)
            abort = False
            for name in filenames:
                for proc in processors: proc.reset()
                if process(dirpath+'/'+name, do_fix, filter(lambda proc: proc.applicable(name), processors)) != 0:
                    abort = True
                    break
            if abort:
                break

