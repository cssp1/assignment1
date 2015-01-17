#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# backup all game server state, including local databases and S3 userdb/playerdb/aistate,
# to another S3 bucket

import sys, os, getopt, time, tempfile, shutil
import SpinS3
import SpinUserDB
import SpinConfig
import SpinParallel
import SpinSingletonProcess
import subprocess

time_now = int(time.time())
date_str = time.strftime('%Y%m%d', time.gmtime(time_now))

# autoconfigure based on config.json
game_id = SpinConfig.config['game_id']
backup_bucket = 'spinpunch-backups'
backup_obj_prefix = '%s-player-data-%s/' % (SpinConfig.game_id_long(), date_str)
s3_key_file_for_db = SpinConfig.aws_key_file()
s3_key_file_for_backups = SpinConfig.aws_key_file()
s3_driver = None
userdb_bucket = SpinConfig.config['userdb_s3_bucket']
playerdb_bucket = SpinConfig.config['playerdb_s3_bucket']
aistate_bucket = SpinConfig.config['aistate_s3_bucket']

class NullFD(object):
    def write(self, stuff): pass

def do_local_backup(verbose):
    msg_fd = sys.stderr if verbose else NullFD()
    backup_con = SpinS3.S3(s3_key_file_for_backups)

    # back up config.json and all local database files
    objname = backup_obj_prefix + 'config.json'
    print >> msg_fd, 'local: uploading config.json', '->', objname, '...'
    backup_con.put_file(backup_bucket, objname, 'config.json')

    if ('sqlserver' in SpinConfig.config) and SpinConfig.config['sqlserver'].get('enable', True) and False:
        # OBSOLETE - we don't use MySQL anymore, and if we re-introduce it we'd do the backups on the MySQL server itself
        sqlfile = tempfile.NamedTemporaryFile(prefix='prodbackup-local', suffix='.sql.gz')
        sqlfilename = sqlfile.name
        cfg = SpinConfig.config['sqlserver']
        print >> msg_fd, 'local: dumping SQL data...'
        subprocess.check_call('mysqldump -u%s -p%s %s | gzip -c > %s' % (cfg['username'], cfg['password'], cfg['database'], sqlfilename), shell = True)
        objname = backup_obj_prefix + 'mysql.gz'
        print >> msg_fd, 'local: uploading', os.path.basename(sqlfilename), '->', objname, '...'
        backup_con.put_file(backup_bucket, objname, sqlfilename)

    if ('mongodb_servers' in SpinConfig.config) and False:
        # OBSOLETE - we now have the MongoDB servers take care of their own backups
        for key, cfg in SpinConfig.config['mongodb_servers'].iteritems():
            if not cfg.get('backup',False): continue
            #if cfg['host'] != 'localhost': continue

            config = SpinConfig.get_mongodb_config(key)
            mydir = tempfile.mkdtemp(prefix='prodbackup-local-'+key, suffix='-mongodb')
            try:
                print >> msg_fd, 'local: dumping NoSQL data for %s...' % key
                subprocess.check_call('/usr/local/mongodb/bin/mongodump --host %s --port %d -u %s -p %s -d %s -o %s > /dev/null' % (config['host'], config['port'], config['username'], config['password'], config['dbname'], mydir), shell = True)
                myarch = os.path.join(mydir, 'mongodb-%s.cpio.gz' % config['dbname'])
                print >> msg_fd, 'local: compressing %s...' % os.path.basename(myarch)
                subprocess.check_call('(cd %s && find %s | cpio -oL --quiet | gzip -c > %s)' % (mydir, config['dbname'], myarch), shell = True)
                objname = backup_obj_prefix + 'mongodb-%s.cpio.gz' % config['dbname']
                print >> msg_fd, 'local: uploading', os.path.basename(myarch), '->', objname, '...'
                backup_con.put_file(backup_bucket, objname, myarch)
            finally:
                subprocess.check_call('rm -rf %s' % mydir, shell = True)

    print >> msg_fd, 'local: done'


def backup_s3_dir(title, bucket_name, prefix = '', ignore_errors = False, verbose = False):
    # back up from S3 (either an entire bucket or one subdirectory) to one cpio.gz archive
    msg_fd = sys.stderr if verbose else NullFD()

    db_con = SpinS3.S3(s3_key_file_for_db)
    backup_con = SpinS3.S3(s3_key_file_for_backups)

    print >> msg_fd, title, ':'
    td = tempfile.mkdtemp(prefix='prodbackup-'+title)
    try:
        counter = 0
        print >> msg_fd, title, ': listing bucket...'
        if prefix:
            os.mkdir(os.path.join(td, prefix))
        for data in db_con.list_bucket(bucket_name, prefix = (prefix+'/' if prefix else '')):
            objname = data['name']
            filename = os.path.join(td, objname)
            if verbose: # counter % 1 == 0:
                print >> msg_fd, title, ': getting %s/%s -> %s (%d)...' % (bucket_name, objname, filename, counter)

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

            counter += 1

            #if counter >= 50: break

        print >> msg_fd, title, ': downloaded %d files' % counter
        print >> msg_fd, title, ': collecting archive...'
        tf = tempfile.NamedTemporaryFile(prefix='prodbackup-'+title, suffix='.cpio.gz')
        subprocess.check_call('(cd %s && find . | cpio -oL --quiet | gzip -c > %s)' % (td, tf.name), shell = True)
        objname = backup_obj_prefix + title + '.cpio.gz'
        print >> msg_fd, title, ': uploading', tf.name, '->', objname, '...'
        backup_con.put_file(backup_bucket, objname, tf.name)
        print >> msg_fd, title, ': done'
    finally:
        print >> msg_fd, title, ': CLEANUP', td
        shutil.rmtree(td, True)

def get_s3_driver():
    return SpinUserDB.S3Driver(game_id = game_id,
                               key_file = s3_key_file_for_db,
                               userdb_bucket = userdb_bucket,
                               playerdb_bucket = playerdb_bucket)

def do_user_backup(part, verbose):
    s3_driver = get_s3_driver()
    backup_s3_dir('userdb-part%02dof%02d' % (part, s3_driver.nbuckets-1),
                  userdb_bucket,
                  prefix = s3_driver.get_user_prefix_for_bucket(part),
                  verbose = verbose)
def do_player_backup(part, verbose):
    s3_driver = get_s3_driver()
    backup_s3_dir('playerdb-part%02dof%02d' % (part, s3_driver.nbuckets-1),
                  playerdb_bucket,
                  prefix = s3_driver.get_player_prefix_for_bucket(part),
                  verbose = verbose)


def my_slave(input):
    if input['kind'] == 'local':
        do_local_backup(input['verbose'])
    elif input['kind'] == 'player':
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

    if do_local:
        task_list.append({'kind':'local', 'verbose':verbose})

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

