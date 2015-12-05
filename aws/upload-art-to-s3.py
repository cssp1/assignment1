#!/usr/bin/python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Script to upload each file in the game art packet to the
# spinpunch-art S3 bucket, which is the source for our CDN.
# Must be run from within the "aws" directory of the game instance.

import sys, os, getopt, subprocess

SCRIPT_DIR = os.path.dirname(sys.argv[0])
ART_DIR = SCRIPT_DIR+'/../gameclient/art'

if __name__ == "__main__":
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])

    for key, val in opts:
        pass

    # only upload the master art.tar.gz file
    src_file = os.path.join(ART_DIR, '..', 'art.tar.gz')
    aws_bucket = 'spinpunch-artmaster'
    aws_command = ['aws', 's3', 'cp', src_file, 's3://%s/art.tar.gz' % aws_bucket, '--acl', 'public-read']
    print ' '.join(aws_command)
    subprocess.check_call(aws_command)

