#!/usr/bin/env python

# make Closure Compiler warning output more useful by filtering irrelevant errors

import sys, re, os

warning_re = re.compile('(.+):([0-9]+): (WARNING|ERROR) - (.+)')
do_print = False
n_seen = {'WARNING': 0, 'ERROR': 0}

for line in sys.stdin:
    line = line[:-1] # strip newline
    match = warning_re.match(line)
    if match:
        do_print = False # turn off printing

        filepath, lineno, kind, msg = match.groups()

        # only look for messages in our code
        if not filepath.startswith('clientcode'): continue
        filename = os.path.split(filepath)[-1]
        if filename in ('buzz.js','Traceback.js'): continue

        do_print = True # print until we see the next warning
        print line

        n_seen[kind] += 1

    else: # not the beginning of a new warning
        if do_print:
            if line:
                print line

print 'total:', n_seen
