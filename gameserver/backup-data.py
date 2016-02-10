#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# backup S3 userdb/playerdb to compressed files in another S3 bucket

# note: requires a large amount of space (1GB+) for gathering temporary files
# set TMPDIR environment variable to a suitable location

import sys, os, getopt, time, tempfile, shutil
import SpinS3
import SpinUserDB
import SpinConfig
import SpinParallel
import SpinSingletonProcess
import subprocess

date_str = time.strftime('%Y%m%d', time.gmtime())

# autoconfigure based on config.json
game_id = SpinConfig.config['game_id']
backup_bucket = 'spinpunch-backups'
backup_obj_prefix = '%s-player-data-%s/' % (SpinConfig.game_id_long(), date_str)
s3_key_file_for_db = SpinConfig.aws_key_file()
s3_key_file_for_backups = SpinConfig.aws_key_file()

class NullFD(object):
    def write(self, stuff): pass

SUBPART_PATTERN = '.%05d' # appended to the part00of99 archive name for subparts

# since we have to back up an entire S3 directory at once, we might want to break the archive into
# multiple subparts, to avoid the size of any one subpart growing without bound. This is the
# max size of uncompressed input data to put in a subpart. Note, playerdb files typically compress about 10x with gzip.
SIZE_BREAK = 50*1024*1024 # needs ~50MB of scratch space per parallel process

def ship_subpart(msg_fd, backup_con, backup_bucket, td, prefix, backup_obj_prefix, title, subpart_num):
    print >> msg_fd, title, ': archiving subpart %d...' % subpart_num
    # name of the compressed archive to create
    tf = tempfile.NamedTemporaryFile(prefix='prodbackup-'+title+(SUBPART_PATTERN % subpart_num), suffix='.cpio.gz')
    # cpio/gzip it
    subprocess.check_call('(cd %s && find . | cpio -oL --quiet | gzip -c > %s)' % (td, tf.name), shell = True)
    objname = backup_obj_prefix + title + (SUBPART_PATTERN % subpart_num) + '.cpio.gz'
    # upload it to S3
    print >> msg_fd, title, ': uploading', tf.name, '->', objname, '...'
    backup_con.put_file(backup_bucket, objname, tf.name)

    # now clean out td (but leave the parent td directory, to be reused for next subpart)
    print >> msg_fd, title, ': subpart %d done, clearing temp directory...' % subpart_num
    subprocess.check_call('rm -r %s/*' % (td,), shell = True)
    if prefix: # recreate the subdirectory mirroring the prefix in S3
        os.mkdir(os.path.join(td, prefix))

def backup_s3_dir(title, bucket_name, prefix = '', ignore_errors = False, verbose = False):
    # back up from S3 (either an entire bucket or one subdirectory) to one (or multiple) cpio.gz archive(s)
    msg_fd = sys.stderr if verbose else NullFD()

    db_con = SpinS3.S3(s3_key_file_for_db)
    backup_con = SpinS3.S3(s3_key_file_for_backups)

    print >> msg_fd, title, ':'
    td = tempfile.mkdtemp(prefix=game_id+'-prodbackup-'+title)
    try:
        s3_object_count = 0
        s3_total_size = 0
        s3_subpart_size = 0
        s3_subpart_count = 0

        print >> msg_fd, title, ': listing bucket...'
        if prefix: # create a subdirectory mirroring the prefix in S3
            os.mkdir(os.path.join(td, prefix))
        for data in db_con.list_bucket(bucket_name, prefix = (prefix+'/' if prefix else '')):
            objname = data['name']
            filename = os.path.join(td, objname)
            if verbose: # s3_object_count % 1 == 0:
                print >> msg_fd, title, ': getting %s/%s -> %s (%d subpart %d)...' % (bucket_name, objname, filename, s3_object_count, s3_subpart_count)

            attempt = 0
            MAX_ATTEMPTS = 3
            while attempt < MAX_ATTEMPTS:
                attempt += 1
                success = False
                try:
                    db_con.get_file(bucket_name, objname, filename)
                    success = True
                except SpinS3.S3Exception:
                    # retry failed downloads (S3)
                    pass
                except IOError:
                    # retry failed downloads (disk)
                    pass
                except:
                    raise

                if success:
                    break

            s3_object_count += 1
            s3_total_size += data['size']
            s3_subpart_size += data['size']

            if s3_subpart_size >= SIZE_BREAK:
                # ship this subpart
                ship_subpart(msg_fd, backup_con, backup_bucket, td, prefix, backup_obj_prefix, title, s3_subpart_count)
                s3_subpart_count += 1
                s3_subpart_size = 0

        # ship final subpart
        if s3_subpart_size > 0:
            ship_subpart(msg_fd, backup_con, backup_bucket, td, prefix, backup_obj_prefix, title, s3_subpart_count)

        print >> msg_fd, title, ': done: %d files %d bytes in %d subparts' % (s3_object_count, s3_total_size, s3_subpart_count)
    finally:
        print >> msg_fd, title, ': CLEANUP', td
        shutil.rmtree(td, True)

def get_s3_driver():
    return SpinUserDB.S3Driver()

def do_user_backup(part, verbose):
    s3_driver = get_s3_driver()
    backup_s3_dir('userdb-part%02dof%02d' % (part, s3_driver.nbuckets-1),
                  s3_driver.userdb_bucket,
                  prefix = s3_driver.get_user_prefix_for_bucket(part),
                  verbose = verbose)
def do_player_backup(part, verbose):
    s3_driver = get_s3_driver()
    backup_s3_dir('playerdb-part%02dof%02d' % (part, s3_driver.nbuckets-1),
                  s3_driver.playerdb_bucket,
                  prefix = s3_driver.get_player_prefix_for_bucket(part),
                  verbose = verbose)

def my_slave(input):
    if input['kind'] == 'player':
        do_player_backup(input['part'], input['verbose'])
    elif input['kind'] == 'user':
        do_user_backup(input['part'], input['verbose'])

if __name__ == '__main__':
    if '--slave' in sys.argv:
        SpinParallel.slave(my_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['parallel=', 'quiet', 'local=', 's3='])

    verbose = True
    do_s3 = False
    do_local = False
    parallel = 1

    for key, val in opts:
        if key == '--parallel':
            parallel = int(val)
        elif key == '--quiet':
            verbose = False
        elif key == '--s3':
            do_s3 = bool(int(val))
        elif key == '--local':
            do_local = bool(int(val))

    task_list = []

    if do_s3:
        s3_driver = get_s3_driver()
        for part in xrange(s3_driver.nbuckets):
            task_list.append({'kind': 'player', 'part': part, 'verbose': verbose})
        for part in xrange(s3_driver.nbuckets):
            task_list.append({'kind': 'user', 'part': part, 'verbose': verbose})

    with SpinSingletonProcess.SingletonProcess('backup-data-%s' % game_id):
        if parallel <= 1:
            for task in task_list:
                my_slave(task)
        else:
            SpinParallel.go(task_list, [sys.argv[0], '--slave'], on_error = 'continue', nprocs=parallel, verbose = False)

    print 'DONE'

