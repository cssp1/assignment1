#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_purchase_ui" table from MongoDB to a SQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

purchase_ui_schema = {
    'fields': [('_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'),
               ('client_time', 'INT8'), # may be omitted for server-side events
               ('user_id', 'INT4 NOT NULL'),
               ('code', 'INT4 NOT NULL'),
               ('event_name', 'VARCHAR(255) NOT NULL'),

               ('gui_version', 'INT4'),
               ('sku', 'VARCHAR(255)'),
               ('method', 'VARCHAR(255)'),
               ('gamebucks', 'INT4'),
               ('currency_price', 'FLOAT4'),
               ('currency', 'VARCHAR(64)'),
               ('usd_receipts_cents', 'INT4'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]},
                'by_user_id_time': {'keys': [('user_id','ASC'),('time','ASC')]},
                }
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
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    purchase_ui_table = cfg['table_prefix']+game_id+'_purchase_ui'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, purchase_ui_table, purchase_ui_schema)
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur.execute("SELECT time FROM "+sql_util.sym(purchase_ui_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0

    qs = {'time':{'$gt':start_time, '$lt': end_time}}

    for row in nosql_client.log_buffer_table('log_purchase_ui').find(qs):
        _id = nosql_client.decode_object_id(row['_id'])

        keyvals = [('_id',_id),
                   ('time',row['time']),
                   ('user_id',row['user_id']),
                   ('code',row['code']),
                   ('event_name',row['event_name'])]

        if 'gui_version' in row:
            if type(row['gui_version']) is list:
                # bad data - cond chain
                gui_version = 1
            else:
                gui_version = row['gui_version']
            keyvals.append(('gui_version', gui_version))

        for FIELD in ('client_time', 'sku', 'method', 'gamebucks', 'currency_price', 'currency'):
            if FIELD in row:
                keyvals.append((FIELD, row[FIELD]))

        if 'usd_equivalent' in row:
            if row['usd_equivalent'] is not None:
                keyvals.append(('usd_receipts_cents', int(100*row['usd_equivalent'])))
            elif row['event_name'] == '4450_buy_gamebucks_payment_complete' and row['currency'] == 'kgcredits': # bad legacy data
                keyvals.append(('usd_receipts_cents', int(0.07*row['currency_price'])))

        sql_util.do_insert(cur, purchase_ui_table, keyvals)

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
        KEEP_DAYS = 180
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', purchase_ui_table
        cur.execute("DELETE FROM "+sql_util.sym(purchase_ui_table)+" WHERE time < %s", old_limit)
        if do_optimize:
            if verbose: print 'optimizing', purchase_ui_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(purchase_ui_table))
        con.commit()
