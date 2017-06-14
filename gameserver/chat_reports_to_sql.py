#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "chat_reports" table from MongoDB to a SQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())

def chat_reports_schema(sql_util): return {
    'fields': [('_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'), # time the thing was said
               ('report_time', 'INT8 NOT NULL'), # time the report was made
               ('resolution_time', 'INT8'),
               ('resolution', 'VARCHAR(32)'),
               ('target_id', 'INT4 NOT NULL'),
               ('reporter_id', 'INT4 NOT NULL'),
               ('channel', 'VARCHAR(32) NOT NULL'),
               ('message_id', 'CHAR(24)'), # joinable to "chat" table on _id
               ('context', 'VARCHAR(1024)'),
               ],
    'indices': {'by_report_time': {'keys': [('report_time','ASC')]},
                }
    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    do_prune = False
    do_optimize = False
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('chat_reports_to_sql-%s' % game_id):

        chat_reports_table = cfg['table_prefix']+game_id+'_chat_reports'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

        cur = con.cursor()
        sql_util.ensure_table(cur, chat_reports_table, chat_reports_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 12*3600  # skip entries too close to "now" to ensure all reports have been made and resolved

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        cur.execute("SELECT report_time FROM "+sql_util.sym(chat_reports_table)+" ORDER BY report_time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['report_time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0

        qs = {'time':{'$gt':start_time, '$lt': end_time}}

        for row in nosql_client.chat_reports_get(start_time, end_time):

            if 'message_id' not in row: continue # bad data
            if not row.get('resolved'): continue # still unresolved

            keyvals = [('_id',row['id']),
                       ('time',row['time']),
                       ('report_time',row['report_time']),
                       ('resolution_time',row.get('resolution_time')),
                       ('resolution',row.get('resolution')),
                       ('target_id',row['target_id']),
                       ('reporter_id',row['reporter_id']),
                       ('channel',row['channel']),
                       ('message_id',row['message_id']),
                       ('context',row.get('context'))]

            sql_util.do_insert(cur, chat_reports_table, keyvals)

            batch += 1
            total += 1
            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted'

        if do_prune:
            # drop old data
            KEEP_DAYS = 60
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', chat_reports_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(chat_reports_table)+" WHERE report_time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', chat_reports_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(chat_reports_table))
            con.commit()
