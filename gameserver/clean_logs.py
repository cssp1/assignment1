#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# clean out extra unnecessary log files to save disk space

import SpinConfig
import SpinS3
import os, sys, glob, time, subprocess, getopt

SAVE_RECENT = 7*24*60*60 #  save most files less than a week old
SAVE_EXCEPTIONS = 60*24*60*60 #  save server exception logs two months
SAVE_REPLAYS = 2*24*60*60 # archive replays older than 2 days
SAVE_BATTLES = 7*24*60*60 # archive battles older than 7 days
ARCHIVE_BATTLES = False

time_now = int(time.time())
s3 = SpinS3.S3(SpinConfig.aws_key_file())

def upload_battle_archive(filename, bucketname):
    # assumes filename begins with YYYYMMDD
    dest_date = filename[0:6]
    assert dest_date.isdigit()
    dest = filename[0:6] + '/' + filename
    s3.put_file(bucketname, dest, filename, timeout=300)


def handle(filename, dry_run = True, is_sandbox = False, battle_archive_s3_bucket = None):
    # "precious" files that should be kept as long as possible
    # (financial / auditing related things)
    if filename.endswith('-pcheck.json') or \
       filename.endswith('-credits.json') or \
       filename.endswith('-fbrtapi.txt') or \
       filename.endswith('-xsapi.txt') or \
       filename.endswith('-policy_bot.json') or \
       filename.endswith('-fb_conversion_pixels.json') or \
       filename.endswith('-fb_app_events.json') or \
       filename.endswith('-adotomi.json') or \
       filename.endswith('-adparlor.json') or \
       filename.endswith('-dauup2.json') or \
       filename.endswith('-dauup.json') or \
       filename.endswith('-kg_conversion_pixels.json') or \
       filename.endswith('-liniad.json'):
        if is_sandbox and \
           os.path.getmtime(filename) < (time_now - SAVE_RECENT):
            print 'DELETING', filename
            if not dry_run:
                os.unlink(filename)
        else:
            print 'keeping vital', filename

    # special case for exceptions log
    elif filename.endswith('-exceptions.txt'):
        if ((not is_sandbox) and (os.path.getmtime(filename) >= (time_now - SAVE_EXCEPTIONS))) or \
           (is_sandbox and (os.path.getmtime(filename) >= (time_now - SAVE_RECENT))):
            print 'keeping recent', filename
        else:
            print 'DELETING', filename
            if not dry_run:
                os.unlink(filename)

    # normal log files that should be kept temporarily only
    elif filename.endswith('-chat.json') or \
         filename.endswith('-gamebucks.json') or \
         filename.endswith('-metrics.json') or \
         filename.endswith('-dbserver.txt') or \
         filename.endswith('-proxyserver.txt') or \
         filename.endswith('-purchase_ui.json') or \
         filename.endswith('-traces.txt') or \
         filename.endswith('-armorgames.txt') or \
         filename.endswith('-battlehouse.txt') or \
         filename.endswith('-mattermost.txt') or \
         filename.endswith('-facebook.txt') or \
         filename.endswith('-mailchimp.json') or \
         filename.endswith('-player-io.txt') or \
         filename.endswith('-controlapi.txt') or \
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

    # special cases for battle logs
    elif filename.endswith('-battles'):
        if os.path.getmtime(filename) >= (time_now - SAVE_BATTLES):
            print 'keeping recent', filename
        else:
            if ARCHIVE_BATTLES and battle_archive_s3_bucket:
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
        if ARCHIVE_BATTLES and battle_archive_s3_bucket:
            print 'UPLOADING', filename
            if not dry_run:
                upload_battle_archive(filename, battle_archive_s3_bucket)
        print 'DELETING', filename
        if not dry_run:
            os.unlink(filename)

    # special cases for battle replays
    elif filename.endswith('-replays'):
        if os.path.getmtime(filename) >= (time_now - SAVE_REPLAYS):
            print 'keeping recent', filename
        else:
            print 'DELETING', filename
            if not dry_run:
                subprocess.check_call(["rm", "-r", filename])

    # obsolete log files that should be deleted immediately
    elif filename.endswith('-sessions.json') or \
         filename.endswith('-machine.json'):
        print 'DELETING', filename
        if not dry_run:
            os.unlink(filename)
    else:
        print 'do not know how to handle', filename

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['go', 'dry-run', 'battle-archive-s3-bucket='])

    dry_run = True
    battle_archive_s3_bucket = None

    for key, val in opts:
        if key == '--go':
            dry_run = False
        elif key == '--dry-run':
            dry_run = True
        elif key == '--battle-archive-s3-bucket':
            battle_archive_s3_bucket = val

    log_dir = SpinConfig.config.get('log_dir','logs')
    os.chdir(log_dir)
    file_list = glob.glob('*.*')
    file_list += glob.glob('*-battles')
    file_list += glob.glob('*-replays')
    file_list.sort()
    for filename in file_list:
        handle(filename, dry_run = dry_run,
               is_sandbox = SpinConfig.config['game_id'].endswith('test'),
               battle_archive_s3_bucket = battle_archive_s3_bucket)
