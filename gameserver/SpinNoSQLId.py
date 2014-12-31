#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# GUID generator that uses the MongoDB ObjectID format
# see https://github.com/mongodb/mongo-python-driver/blob/master/bson/objectid.py

# This is broken out from pymongo so that the server can be run without Mongo or pymongo installed

from random import randint
from socket import gethostname
from hashlib import md5
from os import getpid

def is_valid(s): return len(str(s)) == 24

# extract the UNIX timestamp from the first 4 bytes of a MongoDB ObjectID
# XXX Year 2038 problem here
def id_creation_time(_id): return int(str(_id)[0:8],16)
# create a MongoDB ObjectID string that corresponds to UNIX time 'ts'
def creation_time_id(ts, pid=0, serial=0): return '%08x000000%04x%06x' % (ts, pid & 0xFFFF, serial & 0xFFFFFF)

class Generator (object):
    def __init__(self):
        self.seed = randint(0, 0xFFFFFF)
        machine_bytes = md5(gethostname()).digest()[0:3]
        self.machine_str = '%02x%02x%02x' % tuple(map(ord, machine_bytes))
        self.pid_str = '%04x' % (getpid() % 0xFFFF)
    # note: set_time must be called manually
    def set_time(self, time):
        self.time_str = '%08x' % time
    def generate(self):
        self.seed = (self.seed+1) % 0xFFFFFF
        ret = ''.join([self.time_str, self.machine_str, self.pid_str, '%06x' % self.seed])
        assert len(ret) == 24
        return ret

if __name__ == '__main__':
    import bson, time

    print str(bson.objectid.ObjectId())
    print str(bson.objectid.ObjectId())
    g = Generator()
    g.set_time(int(time.time()))

    print g.generate()
    print g.generate()
    print bson.objectid.ObjectId(g.generate())
