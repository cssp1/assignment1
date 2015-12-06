#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Map: implements a JSON-based mapping from string keys to arbitrary data structure values
# intended to hold a lot of keys (one per player) and update the backing-store file efficiently
# used for Facebook ID -> game ID mapping

import SpinJSON
import AtomicFileWrite
import os, time, glob, copy, sys
import traceback


class Map (object):
    def __init__(self, name, filename, verbose = False, allow_write = True, sort_numeric = False):
        self.name = name
        self.filename = filename
        self.verbose = verbose
        self.allow_write = allow_write
        self.sort_numeric = sort_numeric

        try:
            print 'loading', self.filename, '...',
            sys.stdout.flush()
            self.map = SpinJSON.load(open(self.filename))
        except:
            self.map = {}
        print 'done'
        self.dirty = False

    def destroy(self):
        try: os.unlink(self.filename)
        except: pass

    # call this BEFORE making any changes to self.map[key]
    def pre_change(self, key): pass

    # call this AFTER making changes to self.map[key]
    def set_dirty(self, key, fsync = True):
        self.dirty = True
        # full flush on every write
        self.flush(fsync = fsync)

    # prune keys we don't care about anymore before flushing
    # note: these deletions are NOT journaled!
    def can_prune(self, key, value): return False
    def do_prune(self):
        to_remove = []
        for key, value in self.map.iteritems():
            # ignore all exceptions, because this is called from
            # flush(), and in an emergency we want to make SURE we do
            # not lose data.
            try:
                if self.can_prune(key, value):
                    to_remove.append(key)
            except:
                print 'exception during do_prune(): '+traceback.format_exc()

        for key in to_remove:
            del self.map[key]

    def flush(self, fsync = True):
        assert self.allow_write
        if self.verbose:
            print 'flushing', self.name, '...',
            start_time = time.time()

        if not self.dirty:
            if self.verbose:
                print 'not dirty'
            return
        else:
            if self.verbose:
                print '(sync=%d)' % fsync,

        # prune map just before write
        self.do_prune()

        self.dirty = False
        atom = AtomicFileWrite.AtomicFileWrite(self.filename, 'w')

        # put keys in sorted order so the output is pretty
        keylist = sorted(self.map.keys(), key = int if self.sort_numeric else None, reverse = True)
        # write dictionary in streaming fashion to save RAM
        atom.fd.write('{\n')
        while len(keylist) > 0:
            key = keylist.pop()
            comma = ',' if len(keylist) > 0 else ''
            atom.fd.write('"'+str(key)+'":'+SpinJSON.dumps(self.map[key], double_precision=5)+comma+'\n')
        atom.fd.write('}\n')

        atom.complete(fsync = fsync)
        if self.verbose:
            end_time = time.time()
            print 'done (%.1f ms)' % (1000.0*(end_time - start_time))

# similar to Map, but writes incremental updates to self.map line by line into a journal file
# so that small updates can be made safely without flushing the entire map to disk.
# the on-disk data (backing file + journal file) is ALWAYS up to date as long as set_dirty(fsync=True)
# is called after each update. You can get more performance (but less safety against crashes)
# by calling set_dirty(fsync=False)

class JournaledMap (Map):
    DELETED = "BALEETED" # special value written to log to indicate deleted keys

    def __init__(self, *args, **kwargs):
        Map.__init__(self, *args, **kwargs)
        self.journal_path = self.filename + '.journal'
        self.journal = None
        self.journal_filename = None
        self.journal_gen = 0

        self.recover()

    def recover(self):
        journal_list = sorted(glob.glob(self.journal_path+'*'))
        assert len(journal_list) < 10
        for filename in journal_list:
            fd = open(filename)
            filesize = os.fstat(fd.fileno()).st_size
            print 'recovering updates from', filename, '(size %d)' % filesize
            if filesize == 0: continue
            self.dirty = True
            for line in fd.xreadlines():
                kvmap = SpinJSON.loads(line)
                for key, value in kvmap.iteritems():
                    if value == JournaledMap.DELETED:
                        if key in self.map:
                            del self.map[key]
                    else:
                        self.map[key] = value

        if self.allow_write and self.dirty:
            self.flush()
            for filename in journal_list:
                os.unlink(filename)

    def destroy(self):
        Map.destroy(self)
        try:
            for filename in glob.glob(self.journal_path+'*'): os.unlink(filename)
        except: pass

    def set_dirty(self, key, fsync = True):
        self.dirty = True
        if not self.journal:
            self.journal_filename = self.journal_path+'.'+str(self.journal_gen)
            self.journal = open(self.journal_filename, 'a', 1)

        contents = self.map.get(key, JournaledMap.DELETED)

        self.journal.write('{"'+str(key)+'":'+SpinJSON.dumps(contents, double_precision=5)+'}\n')
        self.journal.flush()
        if fsync:
            os.fsync(self.journal.fileno())

    def flush(self):
        Map.flush(self, fsync = True)
        self.trim_journal()

    def trim_journal(self):
        if self.journal:
            # try truncating to 0 instead of unlinking, unlink() might a cause of lag spikes
            os.ftruncate(self.journal.fileno(), 0)
            #os.unlink(self.journal_filename)
            self.journal.close()
            self.journal = None
            self.journal_filename = None

class AsyncJournaledMap (JournaledMap):
    def __init__(self, *args, **kwargs):
        # pre-initialize these, because recover() refers to them
        self.async_map = None # snapshotted version of self.map when async flush began
        self.async_keys = None
        self.async_atom = None
        JournaledMap.__init__(self, *args, **kwargs)
    def destroy(self):
        self.async_flush_abort()
        JournaledMap.destroy(self)
    def flush(self):
        # abort async flush in progress, replace with regular flush
        self.async_flush_abort()
        JournaledMap.flush(self)

    # copy-on-write keys into self.async_map so that the snapshot is consistent
    def pre_change(self, key):
        if self.async_map is not None:
            if (key not in self.async_map) and (key in self.map):
                self.async_map[key] = copy.deepcopy(self.map[key])

    def async_flush_begin(self):
        assert self.async_atom is None

        self.do_prune()

        self.async_atom = AtomicFileWrite.AtomicFileWrite(self.filename, 'w')
        self.async_atom.fd.write('{\n')

        # take a virtual copy-on-write snapshot of self.map
        self.async_map = {}

        # sort keys so that the file gets written in nice pretty sorted order
        # if using numeric keys, sort numerically
        # note: reverse the sort so that pop() returns keys in sorted order
        self.async_keys = sorted(self.map.keys(), key = int if self.sort_numeric else None, reverse = True)

        if self.verbose:
            print 'async flush of', self.name, 'start:', len(self.async_keys), 'keys'

    def async_flush_in_progress(self): return self.async_atom is not None
    def async_flush_keys_to_go(self): return len(self.async_keys) if self.async_keys else 0

    def async_flush_end(self):
        assert len(self.async_keys) == 0
        self.async_atom.fd.write('}\n')
        self.async_atom.complete(fsync = True) # should complete quickly
        if self.verbose:
            print 'async flush of', self.name, 'complete: trimming journal'
        self.async_map = None
        self.async_keys = None
        self.async_atom = None
        # swap journal
        self.dirty = False
        self.trim_journal()

    def async_flush_abort(self):
        if self.async_atom:
            if self.verbose:
                print 'aborting in-progress async flush'
            self.async_atom.abort()
            self.async_atom = None
            self.async_keys = None
            self.async_map = None

    def async_flush_step(self, nkeys):
        if not self.dirty: return True

        if self.async_atom is None:
            self.async_flush_begin()

        if self.verbose >= 2:
            print 'async flushing up to', nkeys, 'keys'
        if nkeys < 0:
            nkeys = len(self.async_keys)
        else:
            nkeys = min(nkeys, len(self.async_keys))

        for i in xrange(nkeys):
            key = self.async_keys.pop()
            if key in self.async_map:
                value = self.async_map[key]
            else:
                value = self.map[key]
            comma = ',' if len(self.async_keys) > 0 else ''
            self.async_atom.fd.write('"'+str(key)+'":'+SpinJSON.dumps(value, double_precision=5)+comma+'\n')
            # no need to flush here, it will happen on _end()

        if len(self.async_keys) < 1:
            self.async_flush_end()
            return True

        return False

if __name__ == "__main__":
    TESTFILE = '/tmp/zzz.json'
    if os.path.exists(TESTFILE):
        os.unlink(TESTFILE)

    def dotest(TESTFILE, async):
        klass = AsyncJournaledMap if async else JournaledMap
        table = klass('test', TESTFILE, verbose = True)

        for i in range(2):
            key = chr(ord('A')+i)+str(i)
            table.map[key] = i
            table.set_dirty(key)

        if async:
            table.async_flush_step(1)
        else:
            table.flush()

        newval = {'newval': 5678}
        table.pre_change('newkey')
        table.map['newkey'] = newval
        table.set_dirty('newkey')
        table.pre_change('newkey2')
        table.map['newkey2'] = 'abc'
        table.set_dirty('newkey2')
        table.pre_change('newkey2')
        del table.map['newkey2']
        table.set_dirty('newkey2')

        if async:
            table.async_flush_step(5)

        # forget to flush!
        if table.journal_filename:
            print 'JOURNAL:'
            for line in open(table.journal_filename).xreadlines():
                print line,

        table = klass('test', TESTFILE, verbose = True)
        assert table.map['newkey'] == newval
        if async:
            table.async_flush_begin()
            table.async_flush_step(5)

    dotest(TESTFILE, False)
    dotest(TESTFILE, True)
