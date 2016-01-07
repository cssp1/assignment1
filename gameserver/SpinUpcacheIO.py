#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# I/O library for working with upcache both locally and in S3

import SpinJSON
import FastGzipFile
import os, subprocess, time

# WRITER is in dump_userdb.py

class Reader(object):
    def num_segments(self):
        return len(self.segments)
    def update_time(self):
        return self.info['update_time']

class LocalReader(Reader):
    def __init__(self, path, verbose = False, info = None, skip_empty = True, skip_developer = True):
        self.path = path
        self.verbose = verbose
        self.skip_empty = skip_empty
        self.skip_developer = skip_developer
        if info:
            self.info = info
        else:
            self.info = SpinJSON.load(open(path+'-info.json'))
        if 'segments' in self.info:
            self.segments = self.info['segments']
        else:
            self.segments = [path+'.sjson.gz']
    def iter_all(self):
        for segment in self.segments:
            s = FastGzipFile.Reader(segment)
            for line in s.xreadlines():
                ret = SpinJSON.loads(line)
                if self.skip_empty and ('EMPTY' in ret): continue
                if self.skip_developer and ret.get('developer',False): continue
                yield ret
    def iter_segment(self, segnum):
        s = FastGzipFile.Reader(self.segments[segnum])
        for line in s.xreadlines():
            ret = SpinJSON.loads(line)
            if self.skip_empty and ('EMPTY' in ret): continue
            if self.skip_developer and ret.get('developer',False): continue
            yield ret

class S3Reader(Reader):
    def __init__(self, s3, bucket, prefix, verbose = False, info = None, skip_empty = True, skip_developer = True):
        self.s3 = s3
        self.bucket = bucket
        self.prefix = prefix
        self.verbose = verbose
        self.skip_empty = skip_empty
        self.skip_developer = skip_developer

        if info:
            self.info = info
        else:
            self.info = SpinJSON.loads(self.s3.get_slurp(self.bucket, os.path.basename(self.prefix+'-info.json')))
        if 'segments' in self.info:
            self.segments = self.info['segments']
        else:
            self.segments = [self.prefix+'.sjson.gz']
        if self.verbose:
            print 'INFO', self.info
            print 'SEGMENTS', self.segments
    def segment_filename(self, segment):
        return os.path.basename(segment)
    def iter_all(self):
        for segnum in xrange(len(self.segments)):
            for item in self.iter_segment(segnum):
                yield item

    def iter_segment(self, segnum):
        filename = self.segment_filename(self.segments[segnum])

        skip = 0
        fail_count = 0

        start_time = time.time()
        busy_time = 0.0

        while True:
            # BEGIN open S3 connection
            fd = self.s3.get_open(self.bucket, filename, allow_keepalive = False)
            unzipper = subprocess.Popen(['gunzip', '-c', '-'],
                                        stdin=fd.fileno(),
                                        stdout=subprocess.PIPE)

            entry = 0
            restart = False

            try:
                line = ''
                for line in unzipper.stdout.xreadlines():
                    if entry < skip:
                        entry += 1; continue

                    ret = SpinJSON.loads(line)

                    entry += 1
                    skip += 1

                    # output
                    if self.skip_empty and ('EMPTY' in ret): continue
                    if self.skip_developer and ret.get('developer',False): continue

                    busy_start = time.time()
                    yield ret
                    busy_end = time.time()
                    busy_time += (busy_end - busy_start)

                if unzipper.returncode != 0:
                    raise Exception('unclean exit from unzipper')

            except GeneratorExit:
                raise
            except Exception as e:
                # received bad data
                unzipper.terminate()
                unzipper = None
                fd = None
                fail_count += 1
                if fail_count >= SpinS3.MAX_RETRIES:
                    debug = open('/tmp/upcacheIO-fail2-%s-%d-%d.json' % (filename,skip,os.getpid()), 'w')
                    debug.write(line)
                    debug.close()
                    raise
                else:
                    restart = True

            if restart:
                time.sleep(SpinS3.RETRY_DELAY)
                continue # try again from BEGIN

            # success!
            break

        end_time = time.time()
        if 1:
            s = '%d %-50s: count %d total %.2fs busy %.2fs (%.0f%%)' % (end_time, filename, skip, end_time-start_time, busy_time, 100.0*(busy_time / (end_time-start_time)))
            if fail_count > 0:
                s += ' (%d fails)' % fail_count
            s += '\n'
            debug = open('/tmp/upcacheIO-time.json', 'a')
            debug.write(s)
            debug.close()

if __name__ == "__main__":
    reader = LocalReader('logs/upcache')
