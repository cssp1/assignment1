#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool to clean out bad aistate files

import SpinS3
import SpinConfig
import time

time_now = int(time.time())

if __name__ == '__main__':
    con = SpinS3.S3(SpinConfig.aws_key_file())
    for data in con.list_bucket(SpinConfig.config['aistate_s3_bucket']):
        # get rid of old Fugitive bases
        if data['name'].endswith('_tr_10.txt'):
            if data['mtime'] < time_now - 3600:
                print "DEL", data['name']
                con.do_delete(SpinConfig.config['aistate_s3_bucket'], data['name'])
