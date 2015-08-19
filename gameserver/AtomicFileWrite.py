# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os

# replace a file on disk atomically
class AtomicFileWrite:
    def __init__(self, filename, mode, ident = ''):
        self.filename = filename
        self.temp_filename = filename + '.inprogress'
        if ident: self.temp_filename += '.' + ident
        self.fd = open(self.temp_filename, mode)
    def complete(self, fsync = True):
        self.fd.flush()
        if fsync:
            os.fsync(self.fd.fileno())
        os.rename(self.temp_filename, self.filename)
        self.fd.close()
    def abort(self):
        try:
            os.unlink(self.temp_filename)
        except:
            pass
        self.fd.close()
