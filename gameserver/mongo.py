#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool to quickly invoke mongo on a database using credentials from config.json

import SpinConfig
import os, sys, getopt, subprocess

if __name__=='__main__':
    whichdb_list = [SpinConfig.config['game_id'],]
    mode = 'connect'

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['sizes'])

    for key, val in opts:
        if key == '--sizes': mode = 'size'

    if len(args)>0:
        whichdb_list = [args[0],]
    elif mode == 'size':
        whichdb_list = SpinConfig.get_mongodb_config_list()

    for whichdb in whichdb_list:
        conf = SpinConfig.get_mongodb_config(whichdb)
        cmd_args = ['mongo', '-u', conf['username'], '-p', conf['password'], '--host', conf['host'], '--port', '%d' % conf['port'], conf['dbname']]

        if mode == 'size':
            cmd_args += ['--quiet','--eval','''db.getCollectionNames().forEach(function (x) { var stats = db.getCollection(x).stats(); if(!stats['ns'] || stats['size'] < 1) { return; }; print((stats['size']/(1024*1024)).toFixed(1) + ' MB, '+(stats['storageSize']/(1024*1024)).toFixed(1)+' MB on disk: '+stats['ns']); })''']

        if len(whichdb_list) > 1:
            subprocess.check_call(cmd_args)
        else:
            os.execvp(cmd_args[0], cmd_args)
