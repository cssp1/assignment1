#!/usr/bin/python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a raw standalone script that does not depend on a game SVN checkout

# RESTORE INSTRUCTIONS

# 1. get Tim Kay's aws script (from game/aws/aws)
# 2. put an IAM key with spinpunch-backups read access in ~/.awssecret and chmod 0700
# 3. download the files, (PUT THEM ON FAST SSD DRIVE!) e.g.:
#      for F in `~/aws ls -1 spinpunch-backups/battlefrontmars-player-data-20140926/`; do if [ `echo $F | grep mongo` ]; then ~/aws get --progress spinpunch-backups/$F $F; fi; done
# 4. untar
#      for F in *.tar.gz; do tar zxvf $F; done
# 5. start MongoDB with auth=false and with bind_ip=127.0.0.1
# 6. restore admin database
#      mongorestore --drop admin
# 7. restore game databases
#      for F in mfprod*; do mongorestore --authenticationDatabase admin -u root -p [password] --drop $F; done
# 8. restart MongoDB with auth=true and bind_ip off
# 9. if moving to new ephemeral storage, check that the SCRATCH_DIR exists!

# script to "catch up" new facebook_id_map entries to avoid losing accounts:
# grep created_new_account longs/20140528-metrics.json > /tmp/z
# out = open('/tmp/cmds', 'w')
# for line in open('/tmp/z'):
#    data = json.loads(line)
#    print >> out, 'var user_id = %d, fb_id = "%s"; db.mf_facebook_id_map.save({_id:fb_id, user_id:NumberInt(user_id)});' % (data['user_id'], data['social_id'][2:] if data['social_id'].startswith('fb') else data['social_id'])
#  to check for data loss:
#    print >> out, 'var user_id = %d, fb_id = "%s"; printjson(db.mf_facebook_id_map.findOne({_id:fb_id}));' % (data['user_id'], data['social_id'][2:])


import sys, os, time, socket, getopt, subprocess
import boto.s3.connection
import boto.s3.key

### HOST-SPECIFIC PARAMETERS
SCRATCH_DIR = '/media/ephemeral0/temp'
mongo_root_password_filename = 'mfprod-mongo-root-password'
backup_bucket = 'spinpunch-backups'
backup_obj_prefix = 'marsfrontier-player-data-$DATE/'
backup_databases = None # or None for all
###

time_now = int(time.time())
date_str = time.strftime('%Y%m%d', time.gmtime(time_now))
backup_obj_prefix = backup_obj_prefix.replace('$DATE', date_str)
host = socket.gethostname().split('.')[0]
aws_key_file = os.path.join(os.getenv('HOME'), '.ssh', host+'-awssecret')
mongo_root_password = open(os.path.join(os.getenv('HOME'), '.ssh', mongo_root_password_filename)).read().strip()
mongo_bin = None
for p in ['/usr/local/mongodb/bin/mongo', '/usr/bin/mongo']:
    if os.path.exists(p):
        mongo_bin = p
        break
assert mongo_bin
mongo_cmd = [mongo_bin, '--host', 'localhost', '--port', '27017', '-u', 'root', '-p', mongo_root_password]

with open(aws_key_file) as key_fd:
    aws_key, aws_secret = key_fd.readline().strip(), key_fd.readline().strip()

def percent_cb(complete, total):
    sys.stdout.write('#')
    sys.stdout.flush()

def s3_put_file(bucket, object, filename, verbose = False):
    conn = boto.s3.connection.S3Connection(aws_key, aws_secret)
    buck = conn.get_bucket(bucket, validate = False)
    k = boto.s3.key.Key(buck)
    k.key = object
    k.set_contents_from_filename(filename, cb = percent_cb if verbose else None, num_cb = 20)
    if verbose: print 'ok'

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['dry-run'])
    dry_run = False
    verbose = False
    clear_log = True
    for key, val in opts:
        if key == '--dry-run': dry_run = True
        elif key == '-v': verbose = True

    # get list of databases
    databases = filter(lambda x: bool(x), subprocess.Popen(mongo_cmd + ['admin', '--quiet', '--eval', "db.adminCommand('listDatabases')['databases'].forEach(function(x) { print(x['name']); });"], stdout=subprocess.PIPE).stdout.read().split('\n'))

    if verbose: print 'host databases:', databases

    if backup_databases is not None: databases = filter(lambda x: x in backup_databases, databases)
    else: databases = filter(lambda x: x not in ('local','config','test'), databases)

    if verbose: print 'will back up databases:', databases

    for database in databases:
        save_cwd = os.getcwd()
        mydir = os.path.join(SCRATCH_DIR, 'mongo-backup-'+database)

        try:
            if not dry_run:
                os.mkdir(mydir)
                os.chdir(mydir)
            if verbose: print 'dumping', database, 'to', mydir, '...'
            if not dry_run:
                subprocess.check_call([mongo_cmd[0]+'dump']+mongo_cmd[1:]+['--authenticationDatabase','admin',
                                                                           '-d', database,
                                                                           '-o', '.'], stdout=open('/dev/null','w'))

            if 0: # CPIO cannot handle files >8GB :P
                zip_file = 'mongodb-%s.cpio.gz' % database
                zip_cmd = 'find %s | cpio -oL --quiet | gzip -c > %s' % (database, zip_file)
            else:
                zip_file = 'mongodb-%s.tar.gz' % database
                zip_cmd = 'tar zcf %s %s' % (zip_file, database)

            if verbose: print 'compressing', zip_file, '...'
            if not dry_run:
                subprocess.check_call(zip_cmd, shell = True)

            backup_obj = backup_obj_prefix + zip_file
            if verbose: print 'uploading', zip_file, '->', backup_bucket, backup_obj, '...',
            if not dry_run:
                s3_put_file(backup_bucket, backup_obj, zip_file, verbose = verbose)
        finally:
            os.chdir(save_cwd)
            if verbose: print 'cleaning up', mydir, '...'
            if not dry_run:
                subprocess.check_call(['/bin/rm','-rf', mydir])

    if clear_log:
        if verbose: print 'rotating logs...'
        cmd = "var opts = db.runCommand({getCmdLineOpts:1})['parsed']; print(('systemLog' in opts ? opts['systemLog']['path'] : opts['logpath']));"
        if not dry_run:
            cmd = "db.runCommand({logRotate:1}); "+cmd
        logpath = subprocess.Popen(mongo_cmd + ['admin', '--quiet', '--eval', cmd], stdout=subprocess.PIPE).stdout.read().strip()
        assert logpath
        if verbose: print 'cleaning up log files:', logpath+'.*'
        if not dry_run:
            subprocess.check_call('/bin/rm -f %s' % (logpath+'.*'), shell=True)
