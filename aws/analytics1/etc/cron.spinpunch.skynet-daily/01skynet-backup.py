#!/usr/bin/python

# this is a raw standalone script that does not depend on a game SVN checkout

import sys, os, time, socket, getopt, subprocess
import boto.s3.connection
import boto.s3.key

### HOST-SPECIFIC PARAMETERS
SCRATCH_DIR = '/media/backup-scratch'
mongo_root_password_filename = 'analytics1-mongo-root-password'
backup_bucket = 'spinpunch-backups'
backup_obj_prefix = 'skynet/$DATE-'
backup_databases = ['skynet'] # or None for all
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
                subprocess.check_call([mongo_cmd[0]+'dump']+mongo_cmd[1:]+['--authenticationDatabase','admin','--quiet',
                                                                           '-d', database,
                                                                           '-o', '.'], stdout=open('/dev/null','w'))

            if 0: # CPIO cannot handle files >4GB :P
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
        if verbose: print 'cleaning up log files:', logpath+'.*'
        if not dry_run:
            subprocess.check_call('/bin/rm -f %s' % (logpath+'.*'), shell=True)
