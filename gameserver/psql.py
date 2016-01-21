#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# tool to quickly invoke psql on a database using credentials from config.json

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

    conf = SpinConfig.get_pgsql_config(whichdb)
    cmd_args=['psql', '--host', conf['host'], '--port', '%d' % conf['port'], '--username', conf['username'], conf['dbname']]
    env = os.environ.copy()
    env['PGPASSWORD'] = conf['password']

    if mode == 'size':
        cmd_args += ['-c',
'''SELECT full_table_name AS table_name,
          round(total_size/(1024*1024)) AS "total (MB)",
          round(table_size/(1024*1024), 0) AS "data (MB)",
          round(indexes_size/(1024*1024), 0) AS "indexes (MB)"
          FROM (SELECT full_table_name,
                       pg_table_size(full_table_name) AS table_size,
                       pg_indexes_size(full_table_name) AS indexes_size,
                       pg_total_relation_size(full_table_name) AS total_size
                       FROM (SELECT ('"' || table_schema || '"."' || table_name || '"') AS full_table_name
                             FROM information_schema.tables WHERE pg_total_relation_size(('"' || table_schema || '"."' || table_name || '"')) >= 10*1024*1024)
                       AS all_tables
                ORDER BY total_size DESC)
          AS pretty_sizes;''']

    os.execvpe(cmd_args[0], cmd_args, env)
