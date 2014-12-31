#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Add linebreaks to a very big JSON file to make it more browser-friendly,
# without changing the interpretation of the JSON data in any way.

# C-accelerated version of this is available under linebreak/

import sys, cStringIO

class State(object):
    NORMAL=0
    QUOTE=1
    QUOTE_SPECIALCHAR=2
    SYMBOL=3
    NUMBER=4

if __name__ == '__main__':
    limit = 500
    src = sys.stdin
    src = cStringIO.StringIO(src.read()); src.seek(0)
    dst = sys.stdout
    buf = cStringIO.StringIO()
    state = State.NORMAL

    while True:
        c = src.read(1)
        if not c: break

        if state == State.NORMAL and buf.tell() >= limit:
            buf.write('\n')
            dst.write(buf.getvalue())
            buf = cStringIO.StringIO()

        if state == State.NORMAL and c in (' ', '\t', '\n', '\r'):
            continue

        buf.write(c)

        if state == State.NORMAL:
            if c == '"':
                state = State.QUOTE
            elif c.isalpha():
                state = State.SYMBOL
            elif (c.isdigit() or c == '.'):
                state = State.NUMBER
        elif state == State.SYMBOL:
            if not c.isalpha():
                state = State.NORMAL
        elif state == State.NUMBER:
            if not (c.isdigit() or c == '.' or c == 'e'):
                state = State.NORMAL
        elif state == State.QUOTE:
            if c == '\\':
                state = State.QUOTE_SPECIALCHAR
            elif c == '"':
                state = State.NORMAL
        elif state == State.QUOTE_SPECIALCHAR:
            state = State.QUOTE

    if state != State.NORMAL:
        raise Exception('ended in non-normal state')

    if buf.tell() > 0:
        tail = buf.getvalue()
        if tail != '\n':
            dst.write(tail)

    dst.write('\n')

