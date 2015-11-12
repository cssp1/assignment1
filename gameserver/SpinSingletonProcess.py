#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os, errno, time

# try to ensure we only run a given process once

class AlreadyRunning(Exception): pass

class SingletonProcess(object):
    def __init__(self, key):
        self.key = key
        # note: /var/run is not user-writable on OSX, so use /tmp instead
        self.path = '/tmp/spin-singleton-%s.pid' % self.key

    def __enter__(self, max_age = 86400): # ignore lock files older than max_age seconds
        # XXX not really atomic
        mtime = -1
        try:
            mtime = os.path.getmtime(self.path)
        except OSError as e:
            if e.errno == errno.ENOENT:
                pass # file not found
            else:
                raise
        if mtime > 0 and (max_age < 0 or mtime > time.time() - max_age):
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
