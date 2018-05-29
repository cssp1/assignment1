#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os

# replace a file on disk atomically
class AtomicFileWrite(object):
    def __init__(self, filename, mode, ident = None):
        self.filename = filename
        self.temp_filename = filename + '.inprogress'
        if ident is not None:
            if ident:
                self.temp_filename += '.' + ident
            else:
                # if ident is the empty string, then use the old behavior
                # where the temp_filename is just "filename.inprogres"
                pass
        else:
            self.temp_filename = '%s.%d' % (self.temp_filename, os.getpid())
        self.fd = open(self.temp_filename, mode)
        self.completed = False
    def complete(self, fsync = True):
        self.fd.flush()
        if fsync:
            os.fsync(self.fd.fileno())
        os.rename(self.temp_filename, self.filename)
        self.fd.close()
        self.completed = True
    def abort(self):
        try:
            os.unlink(self.temp_filename)
        except:
            pass
        self.fd.close()

    def __enter__(self): return self
    def __exit__(self, type, value, traceback):
        if not self.completed:
            self.abort()

# test code
if __name__ == '__main__':
    filename = 'zzz'
    with AtomicFileWrite(filename, 'w', ident = '') as atom:
        print >> atom.fd, 'test'
    # abort
    assert not os.path.exists(filename+'.inprogress')
    with AtomicFileWrite(filename, 'w', ident = '') as atom:
        print >> atom.fd, 'test'
        atom.complete()
    assert not os.path.exists(filename+'.inprogress')
    assert os.path.exists(filename)
    os.unlink(filename)
    print "OK"
