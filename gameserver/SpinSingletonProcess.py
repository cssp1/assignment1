#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os

# try to ensure we only run a given process once

class AlreadyRunning(Exception): pass

class SingletonProcess(object):
    def __init__(self, key):
        self.key = key
        # note: /var/run is not user-writable on OSX, so use /tmp instead
        self.path = '/tmp/spin-singleton-%s.pid' % self.key
    def __enter__(self):
        # XXX not really atomic
        if os.path.exists(self.path):
            raise AlreadyRunning('%s exists - not starting.' % self.path)
        open(self.path, 'w').write('%d\n' % os.getpid())
        return self.key
    def __exit__(self, type, value, traceback):
        os.unlink(self.path)

if __name__ == '__main__':
    with SingletonProcess('asdf'):
        print "testing 1 2 3"
        try:
            with SingletonProcess('asdf') as going_to_fail:
                print "should not get here"
        except AlreadyRunning:
            print "mutex worked"
    b = SingletonProcess('test')
    print "OK"
