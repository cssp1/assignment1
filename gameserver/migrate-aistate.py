#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# migrate on-disk aistate/ files to S3 bucket

import sys, os, hashlib, glob, getopt
import SpinS3
import SpinConfig
import multiprocessing

io_config = SpinConfig.config['gameservers'][SpinConfig.config['gameservers'].keys()[0]].get('io', {})
assert io_config['aistate_use_s3']
con = SpinS3.S3(SpinConfig.aws_key_file())
bucket = SpinConfig.config['aistate_s3_bucket']

def make_s3_aistate_objname(filename):
    name = os.path.basename(filename)
    return hashlib.md5(name).hexdigest() + '-' + name

def migrate_to_s3(filename):
    objname = make_s3_aistate_objname(filename)
    print '%-35s -> %-60s' % (filename, objname),

    # check if the file exists
    mtime = con.exists(bucket, objname)
    if mtime > 0:
        file_mtime = 0 # os.path.getmtime(filename)
        print 'already in S3, skipping (mtime = %d, file = %d, delta = %d)' % (mtime, file_mtime, mtime - file_mtime)
        return

    try:
        con.put_file(bucket, objname, filename)
    except IOError:
        print 'race condition, file was deleted'
        return
    print 'uploaded'

    #wrote_data = con.do_delete(bucket, objname)
    #print 'DELETE OK', wrote_data

def migrate_from_s3(data):
    storage_dir = SpinConfig.config.get('aistate_dir', 'aistate')
    objname = data['name']
    hash, basename = objname.split('-')
    filename = os.path.join(storage_dir, basename)
    print '%-60s -> %-35s' % (objname, filename),

    fd = con.get_open(bucket, objname)
    open(filename, 'w').write(fd.read())
    os.utime(filename, (-1, data['mtime']))
    print 'written'
    #os.unlink(filename)

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['parallel=','to-s3','from-s3'])

    migrate_func = None
    parallel = 1
    for key, val in opts:
        if key == '--parallel':
            parallel = int(val)
        elif key == '--to-s3':
            migrate_func = migrate_to_s3
        elif key == '--from-s3':
            migrate_func = migrate_from_s3

    if not migrate_func:
        sys.stderr.write('need either --to-s3 or --from-s3\n')
        sys.exit(1)

    if migrate_func is migrate_to_s3:
        storage_dir = SpinConfig.config.get('aistate_dir', 'aistate')
        task_list = glob.glob(os.path.join(storage_dir, '*.txt'))
    elif migrate_func is migrate_from_s3:
        task_list = []
        for data in con.list_bucket(bucket):
            if len(task_list) % 1000 == 0:
                print '\rlisting bucket (%d)...' % len(task_list)
            task_list.append(data)

    print 'migrating', len(task_list), 'files...'

    if parallel == 1:
        for filename in task_list:
            migrate_func(filename)
    else:
        pool = multiprocessing.Pool(parallel)
        chunksize = 50
        pool.map(migrate_func, task_list, chunksize)
        pool.close()
        pool.join()

    print 'DONE'

