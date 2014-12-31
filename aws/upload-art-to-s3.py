#!/usr/bin/python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Script to upload each file in the game art packet to the
# spinpunch-art S3 bucket, which is the source for our CDN.
# Must be run from within the "aws" directory of the game instance.

import sys, os, time, string
import getopt, glob, subprocess
import multiprocessing

SCRIPT_DIR = os.path.dirname(sys.argv[0])
ART_DIR = SCRIPT_DIR+'/../gameclient/art'

aws_bucket = 'spinpunch-art/mf1art'

aws_script = SCRIPT_DIR + '/aws'
aws_script_args = '--secrets-file="'+os.getenv('HOME')+'/.ssh/artmaster-awssecret"'

# set up HTTP cache control headers

def format_http_time(stamp):
    return time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(stamp))

# we will set files to expire one year from the current time
const_one_year = 60*60*24*365
const_one_year_from_now_str = format_http_time(time.time()+const_one_year)

cache_control_arg = '"Cache-Control: max-age=%d"' % const_one_year
expires_arg = '"Expires: %s"' % const_one_year_from_now_str

# manually set Content-Type to avoid any system dependencies
CONTENT_TYPE_MAP = { 'png': 'image/png',
                     'jpg': 'image/jpeg',
                     'ogg': 'audio/ogg',
                     'mp3': 'audio/mpeg',
                     'wav': 'audio/x-wav',
                     }

if __name__ == "__main__":
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['write', 'dry-run', 'parallel=', 'all'])
    args = sys.argv[1:]
    if len(args) < 0:
        print 'usage: %s' % sys.argv[0]
        sys.exit(1)

    #userdb_dir = args[0]

    dry_run = False
    proc_count = 20
    master_only = True

    for key, val in opts:
    if key == '--dry-run':
        dry_run = True
        if key == '--write':
            dry_run = False
        if key == '--parallel':
            proc_count = int(val)
        if key == '--all':
            master_only = Fase

    if master_only:
        # only upload the master art.tar.gz file
        aws_bucket = 'spinpunch-artmaster'
        src_file = ART_DIR+'/../art.tar.gz'
        last_mod = format_http_time(os.path.getmtime(src_file))
        aws_command = string.join([aws_script, aws_script_args, '--progress', 'put',
                                   '"Content-Type: application/x-tar-gz"',
                                   #'"Last-Modified: %s"' % last_mod,
                                   aws_bucket+'/art.tar.gz', src_file], ' ')
        print aws_command
        sys.exit(subprocess.check_call(aws_command , shell=True))
        #sys.exit(0)

    file_list = []
    for dirname, dirnames, filenames in os.walk(ART_DIR):
        for filename in filenames:
            if filename == '.DS_Store':
                continue
            path = os.path.relpath(os.path.join(dirname, filename), ART_DIR)
            file_list.append(path)
    file_list.sort()

    completion = multiprocessing.Array('i', [0])

    def do_work(i):
        file = file_list[i]

        if proc_count > 1:
            done_so_far = completion[0]
            completion[0] += 1
        else:
            done_so_far = i

        print 'uploading file %d of %d (%.2f%%): %s' % (done_so_far+1, len(file_list),
                                                        100.0*float(done_so_far+1)/len(file_list), file)


        dest_arg = aws_bucket+'/'+file
        src_arg = os.path.join(ART_DIR, file)
        content_type = CONTENT_TYPE_MAP[file.split('.')[-1]]
        content_type_arg = '"Content-Type: %s"' % content_type
        aws_command = string.join([aws_script, aws_script_args, 'put', content_type_arg, cache_control_arg, expires_arg,
                                   dest_arg, src_arg], ' ')
        if dry_run:
            print aws_command
            return 0
        else:
            return subprocess.check_call(aws_command, shell=True)

    if proc_count > 1:
        pool = multiprocessing.Pool(processes = proc_count)
        pool.map(do_work, range(len(file_list)))
    else:
        for i in range(len(file_list)):
            do_work(i)
