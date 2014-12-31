#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool to quickly invoke mongo on a database using credentials from config.json

import SpinConfig
import os, sys, getopt

if __name__=='__main__':
    whichdb = SpinConfig.config['game_id']
    mode = 'connect'

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['sizes'])

    for key, val in opts:
        if key == '--sizes': mode = 'size'

    if len(args)>0:
        whichdb = args[0]

    conf = SpinConfig.get_mongodb_config(whichdb)
    cmd_args = ['mongo', '-u', conf['username'], '-p', conf['password'], '--host', conf['host'], '--port', '%d' % conf['port'], conf['dbname']]

    if mode == 'size':
        cmd_args += ['--eval','''db.getCollectionNames().forEach(function (x) { var stats = db.getCollection(x).stats(); if(!stats['ns']) { return; }; print(stats['ns']+': '+(stats['size']/(1024*1024)).toFixed(1) + ' MB, '+(stats['storageSize']/(1024*1024)).toFixed(1)+' MB on disk'); })''']

    os.execvp(cmd_args[0], cmd_args)
