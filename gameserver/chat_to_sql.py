#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "chat_buffer" table from MongoDB to a SQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSQLUtil
import SpinETL
import MySQLdb

time_now = int(time.time())

def chat_schema(sql_util): return {
    'fields': [('_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'),
               ('user_id', 'INT4 NOT NULL')] + \
              sql_util.summary_in_dimensions() + \
              [('channel', 'VARCHAR(32) NOT NULL'),
               ('type', 'VARCHAR(64) NOT NULL'),
               ('text', 'VARCHAR(1024)'),
               ],
    'indices': {'by_time': {'keys': [('time','ASC')]},
                }
    }
def chat_summary_schema(sql_util): return {
    'fields': [('day', 'INT8 NOT NULL')] + \
              sql_util.summary_out_dimensions() + \
              [('channel_kind', 'VARCHAR(32) NOT NULL'),
               # this is a simplified version of "channel" that maps
               # all alliance channels to "ALLIANCE"
               # and all region channels to "REGION"
               ('count', 'INT4'),
               ('unique_players', 'INT4')],
    'indices': {'by_day': {'keys': [('day','ASC')]}}
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
    chat_table = cfg['table_prefix']+game_id+'_chat'
    chat_summary_table = cfg['table_prefix']+game_id+'_chat_daily_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor()
    sql_util.ensure_table(cur, chat_table, chat_schema(sql_util))
    sql_util.ensure_table(cur, chat_summary_table, chat_summary_schema(sql_util))
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    cur.execute("SELECT time FROM "+sql_util.sym(chat_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_days = set()

    qs = {'time':{'$gt':start_time, '$lt': end_time}}

    for row in nosql_client.chat_buffer_table().find(qs):
        _id = nosql_client.decode_object_id(row['_id'])

        if not row['channel']: continue # bad data
        message_type = row['sender'].get('type', 'default')

        # check chat template to see whether it is a player-originated
        # chat message (which will have a %body for body text
        # replacement) or a system-generated message (e.g. unit
        # donation traffic). For system messages, do not bother
        # storing the text.

        template = gamedata['strings']['chat_templates'].get(message_type, '%body')
        if '%body' in template:
            text = row['text']
        else:
            text = None

        keyvals = [('_id',_id),
                   ('time',row['time']),
                   ('user_id',row['sender']['user_id']),
                   ('channel',row['channel']),
                   ('type',message_type),
                   ('text',text)]

        if '_sum' in row['sender']:
            # do NOT skip developer-originated chat messages for now
            # if row['_sum'].get('developer',False): continue
            keyvals += sql_util.parse_brief_summary(row['sender']['_sum'])

        sql_util.do_insert(cur, chat_table, keyvals)

        batch += 1
        total += 1
        affected_days.add(86400*(row['time']//86400))
        if commit_interval > 0 and batch >= commit_interval:
            batch = 0
            con.commit()
            if verbose: print total, 'inserted'

    con.commit()
    if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

    # update summary table

    cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(chat_table))
    rows = cur.fetchall()
    if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
        event_range = (rows[0]['min_time'], rows[0]['max_time'])
    else:
        event_range = None

    for table, affected, interval, dt in ((chat_summary_table, affected_days, 'day', 86400),):
        SpinETL.update_summary(sql_util, con, cur, table, affected, event_range, interval, dt, verbose=verbose, dry_run=dry_run,
                               resummarize_tail = dt,
                               execute_func = lambda cur, table, interval, day_start, dt:
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT %s AS day ," + \
                        "       frame_platform AS frame_platform, " + \
                        "       country_tier AS country_tier ," + \
                        "       townhall_level AS townhall_level, " + \
                        "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket, " + \
                        "       IF(SUBSTRING(channel FROM 1 FOR 2)='a:','ALLIANCE', " + \
                        "         IF(SUBSTRING(channel FROM 1 FOR 2)='r:','REGION', "+ \
                        "         channel)) AS channel_kind, " + \
                        "       COUNT(1) AS count, " + \
                        "       COUNT(DISTINCT(user_id)) AS unique_players " + \
                        "FROM " + sql_util.sym(chat_table) + " " + \
                        "WHERE time >= %s AND time < %s " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, channel_kind ORDER BY NULL",
                        [day_start, day_start, day_start+dt]))

    if do_prune:
        # drop old data
        KEEP_DAYS = 60
        old_limit = time_now - KEEP_DAYS * 86400

        if verbose: print 'pruning', chat_table
        cur = con.cursor()
        cur.execute("DELETE FROM "+sql_util.sym(chat_table)+" WHERE time < %s", old_limit)
        if do_optimize:
            if verbose: print 'optimizing', chat_table
            cur.execute("OPTIMIZE TABLE "+sql_util.sym(chat_table))
        con.commit()
