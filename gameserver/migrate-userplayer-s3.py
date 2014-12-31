#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# migrate on-disk userdb/playerdb files to S3 bucket

import sys, os, urllib2, glob, getopt, time, traceback
import SpinS3
import SpinUserDB
import SpinConfig
import multiprocessing

io_config = SpinConfig.config['gameservers'][SpinConfig.config['gameservers'].keys()[0]].get('io', {})
assert io_config['aistate_use_s3']
con = SpinS3.S3(SpinConfig.aws_key_file())
buckets = { 'userdb': 'spinpunch-prod-userdb',
            'playerdb': 'spinpunch-mfprod-playerdb' }
pre_delete = False
dry_run = False
skip_present = False
quiet = False

def migrate_to_s3(params):
    try:
        do_migrate_to_s3(params)
    except:
        sys.stderr.write('PROBLEM: '+traceback.format_exc()+'\n')
        raise
    return

def do_migrate_to_s3(params):
    kind, part = params
    s3_driver = SpinUserDB.S3Driver()
    local_driver = SpinUserDB.driver

    if kind == 'userdb':
        local_dir = SpinConfig.config.get('userdb_dir', 'userdb')
        local_prefix = local_driver.get_user_dir_for_bucket(part)
        s3_prefix = s3_driver.get_user_prefix_for_bucket(part)
        base_pattern = '*.txt'
    elif kind == 'playerdb':
        local_dir = SpinConfig.config.get('playerdb_dir', 'playerdb')
        local_prefix = local_driver.get_player_dir_for_bucket(part)
        s3_prefix = s3_driver.get_player_prefix_for_bucket(part)
        base_pattern = '*_'+SpinConfig.config['game_id']+'.txt'
    else:
        raise Exception('unknown kind '+kind)

    bucket = buckets[kind]

    glob_pattern = os.path.join(local_dir, local_prefix, base_pattern)
    file_list = sorted(glob.glob(glob_pattern))
    print kind, 'part', part, 'glob', glob_pattern, ': %d files' % len(file_list)

    counter = 0
    for filename in file_list:
        try:
            objname = s3_prefix + '/' + os.path.basename(filename)

            do_print = (not quiet) # or (counter % 10000 == 0)
            counter += 1

            if do_print:
                print '%-35s -> %s/%-40s' % (filename, bucket, objname)

            if pre_delete and (not dry_run):
                con.do_delete(bucket, objname)

            # check if the S3 object already exists and is up to date
            elif skip_present:
                file_mtime = os.path.getmtime(filename)
                mtime = con.exists(bucket, objname)
                if mtime > 0 and mtime >= file_mtime:
                    if do_print:
                        print 'already up to date in S3, skipping (mtime = %d, file = %d, delta = %d)' % (mtime, file_mtime, mtime - file_mtime)
                    continue

            if not dry_run:
                MAX_ATTEMPTS = 10
                attempt = 0
                while True:
                    try:
                        con.put_file(bucket, objname, filename)
                        break
                    except urllib2.HTTPError as e:
                        if e.code == 403:
                            if hasattr(e, 'read'):
                                stuff = repr(e.read())
                                sys.stderr.write('got error 403 (attempt %d): %s\n' % (attempt,stuff))
                            stuff = repr(e.info().headers)
                            sys.stderr.write('got error 403 (attempt %d): %s\n' % (attempt,stuff))
                        else:
                            raise Exception('unknown HTTPError: %d' % e.code)

                    attempt += 1
                    if attempt > MAX_ATTEMPTS:
                        raise Exception('too many HTTP failures, giving up')
                    sys.stderr.write('recovering...\n')
                    time.sleep(1.0)

            #print 'uploaded'
        except KeyboardInterrupt:
            raise
        except:
            sys.stderr.write('PROBLEM WITH '+filename+'\n'+traceback.format_exc()+'\n')
            break

    return None

def migrate_from_s3(params):
    kind, part = params
    s3_driver = SpinUserDB.S3Driver()
    local_driver = SpinUserDB.driver

    if kind == 'userdb':
        local_dir = SpinConfig.config.get('userdb_dir', 'userdb')
        s3_prefix = s3_driver.get_user_prefix_for_bucket(part)
        local_prefix = local_driver.get_user_dir_for_bucket(part)
    elif kind == 'playerdb':
        local_dir = SpinConfig.config.get('playerdb_dir', 'playerdb')
        s3_prefix = s3_driver.get_player_prefix_for_bucket(part)
        local_prefix = local_driver.get_player_dir_for_bucket(part)
    else:
        raise Exception('unknown kind '+kind)

    bucket = buckets[kind]

    print 'listing %s/%s...' % (bucket, s3_prefix)

    counter = 0
    for data in con.list_bucket(bucket, prefix = s3_prefix+'/'):
        objname = data['name']
        filename = os.path.join(local_dir, local_prefix, objname.split['/'][-1])
        do_print = (not quiet) or (counter % 100 == 0)
        counter += 1
        if do_print:
            print '%s/%-60s -> %-35s' % (bucket, objname, filename)
        if not dry_run:
            fd = con.get_open(bucket, objname)
            open(filename, 'w').write(fd.read())
            os.utime(filename, (-1, data['mtime']))


if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['parallel=','to-s3','from-s3','dry-run','skip-present',
                                                      'pre-delete','quiet'])

    migrate_func = None
    parallel = 1
    for key, val in opts:
        if key == '--parallel':
            parallel = int(val)
        elif key == '--to-s3':
            migrate_func = migrate_to_s3
        elif key == '--from-s3':
            migrate_func = migrate_from_s3
        elif key == '--dry-run':
            dry_run = True
        elif key == '--skip-present':
            skip_present = True
        elif key == '--pre-delete':
            pre_delete = True
        elif key == '--quiet':
            quiet = True

    if not migrate_func:
        sys.stderr.write('need either --to-s3 or --from-s3\n')
        sys.exit(1)

    s3_driver = SpinUserDB.S3Driver()
    task_list = []
    for part in xrange(s3_driver.nbuckets):
        task_list.append(['userdb', part])
        task_list.append(['playerdb', part])

    print 'migrating', len(task_list), 'tasks...'

    if parallel == 1:
        for task in task_list:
            migrate_func(task)
    else:
        pool = multiprocessing.Pool(parallel)
        chunksize = 1
        pool.map(migrate_func, task_list, chunksize)
        pool.close()
        pool.join()

    print 'DONE'

