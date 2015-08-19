#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool for splitting upcache into "A" and "B" groups for rigorous backtesting

import os
import SpinJSON
import FastGzipFile
import AtomicFileWrite

def outstream_open(filename):
    write_atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
    write_process = FastGzipFile.WriterProcess(write_atom.fd)
    return write_atom, write_process
def outstream_write(data, s):
    write_atom, write_process = data
    write_process.stdin.write(s)
def outstream_close(data):
    write_atom, write_process = data
    write_process.stdin.flush()
    write_process.stdin.close()
    #print 'COMM'
    #stdoutdat, stderrdata = write_process.communicate() # force gzip to finish
    write_atom.complete()

def do_split(game_id, game_name):
    GROUPS = ('all-A', 'all-B', 'payers-A', 'payers-B')

    info_file = '%s-raw/%s-upcache-info.json' % (game_id, game_name)
    info = SpinJSON.load(open(info_file))
    for infile in info['segments']:
        print "PROCESSING", infile
        infile = '%s-raw/' % game_id + os.path.basename(infile)
        outfiles = dict([(name, outstream_open('%s-%s/%s' % (game_id, name, os.path.basename(infile)))) for name in GROUPS])
        instream = FastGzipFile.Reader(infile)
        count = 0
        payer_count = 0
        for line in instream.xreadlines():
            if 'EMPTY' in line:
                count += 1
                continue

            data = SpinJSON.loads(line)
            group = 'A' if (count%2)==0 else 'B'
            outstream_write(outfiles['all-'+group], line)
            if data.get('money_spent',0)>0:
                if 'payers-'+group in outfiles: outstream_write(outfiles['payers-'+group], line)
                payer_count += 1
            count += 1

        for name, stream in outfiles.iteritems():
            print 'CLOSING', name, 'count', count, 'payer_count', payer_count
            outstream_close(stream)

    for group in GROUPS:
        outfo = {'update_time': info['update_time'],
                 'segments': [os.path.basename(infile_name) for infile_name in info['segments']]}
        atom = AtomicFileWrite.AtomicFileWrite('%s-%s/%s-upcache-info.json' % (game_id, group, game_name), 'w')
        SpinJSON.dump(outfo, atom.fd, pretty=True, newline=True)
        atom.complete()

if __name__ == '__main__':
    for game_id, game_name in (('tr','thunderrun'),
                               ('mf','marsfrontier'),
                               ):
        do_split(game_id, game_name)
