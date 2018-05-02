#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_privacy" from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import SpinMySQLdb

time_now = int(time.time())
def privacy_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4 NOT NULL'),
               ('social_id', 'VARCHAR(128)'),
               ('event_name', 'VARCHAR(128) NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [('method', 'VARCHAR(128)'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }

def iterate_from_mongodb(game_id, table_name, start_time, end_time):
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))
    qs = {'time': {'$gt': start_time, '$lt': end_time}}

    for row in nosql_client.log_buffer_table(table_name).find(qs):
        row['_id'] = nosql_client.decode_object_id(row['_id'])
        yield row

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

    with SpinSingletonProcess.SingletonProcess('privacy_to_sql-%s' % game_id):

        privacy_table = cfg['table_prefix']+game_id+'_privacy'

        cur = con.cursor(SpinMySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, privacy_table, privacy_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(privacy_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        for source_table in ('log_privacy',):
            for row in iterate_from_mongodb(game_id, source_table, start_time, end_time):

                if row.get('developer', False): continue # skip events by developers

                keyvals = [('time',row['time']),
                           ('user_id',row['user_id']),
                           ('social_id',row.get('social_id')),
                           ('event_name',row['event_name']),
                           ('frame_platform',row.get('frame_platform')),
                           ('country_tier',SpinConfig.country_tier_map.get(row.get('country'))),
                           ('townhall_level',None), # not logged
                           ('prev_receipts',None), # not logged
                           ('method', row.get('method'))]

                sql_util.do_insert(cur, privacy_table, keyvals)

                batch += 1
                total += 1
                affected_days.add(86400*(row['time']//86400))

                if commit_interval > 0 and batch >= commit_interval:
                    batch = 0
                    con.commit()
                    if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', privacy_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(privacy_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', privacy_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(privacy_table))
            con.commit()
