#!/usr/bin/env python

# Copyright (c) 2019 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_alliance_help" from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinSQLUtil
import SpinETL
import SpinSingletonProcess
import SpinMySQLdb

time_now = int(time.time())
def alliance_help_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('aliance_id', 'INT4 NOT NULL'),
               ('event_name', 'VARCHAR(128) NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [('total_time', 'VARCHAR(128)'),
               ('kind', 'VARCHAR(128)'),
               ('obj_id', 'VARCHAR(128)'),
               ('start_time', 'INT8'),
               ('obj_spec', 'VARCHAR(32)'),
               ('done_time', 'INT8'),
               ('action_spec', 'VARCHAR(32)'),
               ('action', 'VARCHAR(32)'),
               ('action_level', 'INT4'),
               ('obj_level', 'INT4'),
               ('cur_helpers', 'INT4'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('alliance_help_to_sql-%s' % game_id):

        alliance_help_table = cfg['table_prefix']+game_id+'_alliance_help'

        cur = con.cursor(SpinMySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, alliance_help_table, alliance_help_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 600  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(alliance_help_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        for source_table in ('log_alliance_help',):
            for row in SpinETL.iterate_from_mongodb(game_id, source_table, start_time, end_time):
                if ('sum' not in row) or ('user_id' not in row): continue # ignore bad legacy data

                if row['sum'].get('developer',False): continue # skip events by developers

                if 'reason' in row: # JS code calls this "reason" but it should be "method" for consistency with other analytics
                    row['method'] = row['reason']

                keyvals = [('time',row['time']),
                           ('user_id',row['user_id']),
                           ('alliance_id',row['alliance_id']),
                           ('event_name',row['event_name'])] + \
                           sql_util.parse_brief_summary(row['sum'])
                for FIELD in ('total_time','kind','obj_id','start_time','obj_spec','done_time',
                              'action_spec','action','action_level','obj_level','cur_helpers'):
                    if FIELD in row:
                        keyvals.append((FIELD, row[FIELD]))

                sql_util.do_insert(cur, alliance_help_table, keyvals)

                batch += 1
                total += 1
                affected_days.add(86400*(row['time']//86400))

                if commit_interval > 0 and batch >= commit_interval:
                    batch = 0
                    con.commit()
                    if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(alliance_help_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            event_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            event_range = None

        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', alliance_help_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(alliance_help_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', alliance_help_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(alliance_help_table))
            con.commit()
