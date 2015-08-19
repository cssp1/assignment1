#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool to quickly invoke mysql on a database using credentials from config.json

import SpinConfig
import os, sys, getopt, subprocess

if __name__=='__main__':
    whichdb = SpinConfig.config['game_id']+'_upcache'
    execute = None
    mode = 'connect'
    dump_to = None

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['sizes','dump='])

    for key, val in opts:
        if key == '--sizes': mode = 'size'
        elif key == '--dump':
            mode = 'dump'
            dump_to = val

    if len(args)>0:
        whichdb = args[0]
        if len(args) > 1:
            execute = args[1]

    conf = SpinConfig.get_mysql_config(whichdb)
    cmd_args=['-u', conf['username'], "-p"+conf['password'], '-h', conf['host'], '--port', '%d' % conf['port'], '--protocol=tcp']

    if mode == 'dump': # perform dump
        cmd_args += ['--routines',conf['dbname']]
        try:
            subprocess.check_call('mysqldump '+' '.join(cmd_args)+' | gzip -c - > '+dump_to, shell = True)
        except:
            # clean up partial file
            try:
                os.unlink(dump_to)
            except OSError:
                pass
            raise

    else:
        cmd_args += [conf['dbname'],]
        if mode == 'size': # print table sizes
            execute = \
'''SELECT table_name,
          round(((data_length + index_length) / 1024 / 1024), 0) as `total (MB)`,
          round(((data_length) / 1024 / 1024), 0) as `data (MB)`,
          round(((index_length) / 1024 / 1024), 0) as `indexes (MB)`
   FROM information_schema.TABLES
   WHERE table_schema = '%s' and (data_length+index_length) > 10*1024*1024 order by (data_length+index_length) DESC;''' % conf['dbname']

        if execute: # execute literal command
            cmd_args += ['-e', execute]

        os.execvp('mysql', ['mysql',]+cmd_args)
