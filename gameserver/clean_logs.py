#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# clean out extra unnecessary log files to save disk space

import SpinConfig
import SpinS3
import os, sys, glob, time, subprocess, getopt

SAVE_RECENT = 7*24*60*60 #  save most files less than a week old
SAVE_EXCEPTIONS = 60*24*60*60 #  save server exception logs two months
ARCHIVE_BATTLES = 30*24*60*60 # archive battles older than one month
SAVE_BATTLES = False

time_now = int(time.time())
s3 = SpinS3.S3(SpinConfig.aws_key_file())

def upload_battle_archive(filename, bucketname):
    # assumes filename begins with YYYYMMDD
    dest_date = filename[0:6]
    assert dest_date.isdigit()
    dest = filename[0:6] + '/' + filename
    s3.put_file(bucketname, dest, filename, timeout=300)


def handle(filename, dry_run = True, battle_archive_s3_bucket = None):
    if filename.endswith('-chat.json') or \
       filename.endswith('-pcheck.json') or \
       filename.endswith('-gamebucks.json') or \
       filename.endswith('-metrics.json') or \
       filename.endswith('-credits.json') or \
       filename.endswith('-fbrtapi.txt') or \
       filename.endswith('-xsapi.txt') or \
       filename.endswith('-fb_conversion_pixels.json') or \
       filename.endswith('-fb_app_events.json') or \
       filename.endswith('-adotomi.json') or \
       filename.endswith('-adparlor.json') or \
       filename.endswith('-dauup2.json') or \
       filename.endswith('-dauup.json') or \
       filename.endswith('-liniad.json'):
            print 'keeping vital', filename

    elif filename.endswith('-exceptions.txt'):
        if os.path.getmtime(filename) >= (time_now - SAVE_EXCEPTIONS):
            print 'keeping recent', filename

    elif filename.endswith('-dbserver.txt') or \
         filename.endswith('-proxyserver.txt') or \
         filename.endswith('-traces.txt') or \
         filename.endswith('-armorgames.txt') or \
         filename.endswith('-facebook.txt') or \
         filename.endswith('-kongregate.txt') or \
         filename.endswith('-xsolla.txt') or \
         filename.endswith('-hives.txt') or \
         filename.endswith('-region-maint.txt') or \
         filename.endswith('-maint.txt') or \
         ('-raw-' in filename and filename.endswith('.txt')):
            if os.path.getmtime(filename) >= (time_now - SAVE_RECENT):
                print 'keeping recent', filename
            else:
                print 'DELETING', filename
                if not dry_run:
                    os.unlink(filename)

    elif filename.endswith('-battles'):
        if os.path.getmtime(filename) >= (time_now - ARCHIVE_BATTLES):
            print 'keeping recent', filename
        else:
            if SAVE_BATTLES:
                print 'ARCHIVING', filename
                archive = filename+".tar.gz"
                cmd = ["tar", "zcf", archive, filename]
                if not dry_run:
                    subprocess.check_call(cmd)
                    # everything is OK, we can delete the directory
                    subprocess.check_call(["rm", "-r", filename])
                    if battle_archive_s3_bucket:
                        upload_battle_archive(archive, battle_archive_s3_bucket)
            else:
                print 'DELETING', filename
                if not dry_run:
                    subprocess.check_call(["rm", "-r", filename])

    elif filename.endswith('-battles.tar.gz'):
        if SAVE_BATTLES and battle_archive_s3_bucket:
            print 'UPLOADING', filename
            if not dry_run:
                upload_battle_archive(filename, battle_archive_s3_bucket)
        print 'DELETING', filename
        if not dry_run:
            os.unlink(filename)

    elif filename.endswith('-sessions.json') or \
         filename.endswith('-machine.json'):
        print 'DELETING', filename
        if not dry_run:
            os.unlink(filename)
    else:
        print 'do not know how to handle', filename

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['go', 'battle-archive-s3-bucket='])

    dry_run = True
    battle_archive_s3_bucket = None

    for key, val in opts:
        if key == '--go':
            dry_run = False
        elif key == '--battle-archive-s3-bucket':
            battle_archive_s3_bucket = val

    log_dir = SpinConfig.config.get('log_dir','logs')
    os.chdir(log_dir)
    file_list = glob.glob('*.*')
    file_list += glob.glob('*-battles')
    file_list.sort()
    for filename in file_list:
        handle(filename, dry_run = dry_run, battle_archive_s3_bucket = battle_archive_s3_bucket)
