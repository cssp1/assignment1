#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_lottery" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinETL
import SpinNoSQL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def lottery_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('event_name', 'VARCHAR(128) NOT NULL'),
                       ('slot', 'VARCHAR(32)'),
                       # properties of the reward item
                       ('spec', 'VARCHAR(255)'),
                       ('level', 'INT1'),
                       ('stack', 'INT4'),
                       # denormalized stats on the player's warehouse, since we'll want to watch this carefully
                       ('inventory_slots_total', 'INT4'),
                       ('inventory_slots_filled', 'INT4'),
                       ],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }

# (not used)
def lottery_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                       sql_util.summary_out_dimensions() + \
                      [('event_name', 'VARCHAR(128) NOT NULL'),
                       ('n_events', 'INT4'),
                       ('unique_players', 'INT4')
                       ],
            'indices': {'by_'+interval: {'keys': [(interval,'ASC')]}}
            }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    lottery_table = cfg['table_prefix']+game_id+'_lottery'
    lottery_daily_summary_table = cfg['table_prefix']+game_id+'_lottery_daily_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sql_util.ensure_table(cur, lottery_table, lottery_schema(sql_util))
    #sql_util.ensure_table(cur, lottery_daily_summary_table, lottery_summary_schema(sql_util, 'day'))
    con.commit()

    # find most recent already-converted action
    start_time = -1
    end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

    cur.execute("SELECT time FROM "+sql_util.sym(lottery_table)+" ORDER BY time DESC LIMIT 1")
    rows = cur.fetchall()
    if rows:
        start_time = max(start_time, rows[0]['time'])
    con.commit()

    if verbose:  print 'start_time', start_time, 'end_time', end_time

    batch = 0
    total = 0
    affected_days = set()

    qs = {'time':{'$gt':start_time, '$lt':end_time}}

    for row in nosql_client.log_buffer_table('log_lottery').find(qs):
        if ('sum' in row) and row['sum'].get('developer',False): continue # skip events by developers
        if 'user_id' not in row: continue # skip bogus log entries with missing user_id

        keyvals = [('time',row['time']),
                   ('user_id',row['user_id']),
                   ('event_name', row['event_name']),
                   ('slot', row.get('slot',None))]
        if 'sum' in row:
            keyvals += sql_util.parse_brief_summary(row['sum'])

        if 'inv_slots' in row:
            keyvals += [('inventory_slots_total', row['inv_slots']['total']),
                        ('inventory_slots_filled', row['inv_slots']['full'])]
        if 'loot' in row:
            assert len(row['loot']) == 1
            item = row['loot'][0]
            keyvals += [('spec', item['spec']),
                        ('level', item.get('level',None)),
                        ('stack', item.get('stack',1))]
        elif 'spec' in row:
            keyvals += [('spec', row['spec']),
                        ('level', row.get('level', None)),
                        ('stack', row.get('stack', 1))]

        if not dry_run:
            sql_util.do_insert(cur, lottery_table, keyvals)
        else:
            print keyvals

        batch += 1
        total += 1
        affected_days.add(86400*(row['time']//86400))

        if commit_interval > 0 and batch >= commit_interval:
            batch = 0
            con.commit()
            if verbose: print total, 'inserted'

    con.commit()
    if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

    # update summary
    if 0:
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(lottery_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            lottery_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            lottery_range = None

        def update_lottery_summary(cur, table, interval, day_start, dt):
            cur.execute("INSERT INTO "+sql_util.sym(lottery_daily_summary_table) + \
                        "SELECT %s AS "+interval+"," + \
                        "       frame_platform AS frame_platform," + \
                        "       country_tier AS country_tier," + \
                        "       townhall_level AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("prev_receipts")+" AS spend_bracket," + \
                        "       event_name AS event_name," + \
                        "       quest AS quest," + \
                        "       COUNT(1) AS n_events," + \
                        "       COUNT(DISTINCT(user_id)) AS unique_players " + \
                        "FROM " + sql_util.sym(lottery_table) + " dp " + \
                        "WHERE time >= %s AND time < %s " + \
                        "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, event_name, quest ORDER BY NULL",
                        [day_start, day_start, day_start+dt])

        SpinETL.update_summary(sql_util, con, cur, lottery_daily_summary_table, affected_days, lottery_range, 'day', 86400,
                               verbose = verbose, resummarize_tail = 86400, execute_func = update_lottery_summary)

    if (not dry_run) and do_prune:
        # drop old data
        KEEP_DAYS = 90
        old_limit = time_now - KEEP_DAYS * 86400

        for TABLE in (lottery_table,):
            if verbose: print 'pruning', TABLE
            cur.execute("DELETE FROM "+sql_util.sym(TABLE)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', TABLE
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(TABLE))
            con.commit()
