#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump battles (summaries) from MongoDB to PostgreSQL for warehousing

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinJSON
import SpinSingletonProcess
import psycopg2
import SpinSQLUtil

time_now = int(time.time())

sql_util = SpinSQLUtil.PostgreSQLUtil()

# generate a unique ID for a battle summary
def make_log_id(s):
    if s['base_type'] == 'home':
        return '%10d-%d-vs-%d' % (s['time'], s['attacker_id'], s['defender_id'])
    else:
        return '%10d-%d-vs-%d-at-%s' % (s['time'], s['attacker_id'], s['defender_id'], s['base_id'])

def battles_schema(sql_util):
    return { 'fields': [('battle_id', 'VARCHAR(64) NOT NULL'),
                        ('time', 'INT8 NOT NULL'),
                        ('involved_player0', 'INT4'),
                        ('involved_player1', 'INT4'),
                        ('involved_alliance0', 'INT4'),
                        ('involved_alliance1', 'INT4'),
                        ('is_ai', 'boolean NOT NULL'),
                        ('summary', 'jsonb NOT NULL'),
                        ],
             'indices': { 'by_time': {'keys': [('time','ASC')]},
                          'by_battle_id': {'keys': [('battle_id','ASC')], 'unique': True},
                          'by_player0_time': {'keys': [('involved_player0','ASC'),('time','ASC')], 'where': 'involved_player0 IS NOT NULL'},
                          'by_player1_time': {'keys': [('involved_player1','ASC'),('time','ASC')], 'where': 'involved_player1 IS NOT NULL'},
                          'by_alliance0_time': {'keys': [('involved_alliance0','ASC'),('time','ASC')], 'where': 'involved_alliance0 IS NOT NULL'},
                          'by_alliance1_time': {'keys': [('involved_alliance1','ASC'),('time','ASC')], 'where': 'involved_alliance1 IS NOT NULL'},
                          }
             }


if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 100
    verbose = True
    optimize = False
    force = False
    do_reset = False
    dry_run = 0
    throttle = 0

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['reset','optimize','dry-run','force','throttle='])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--optimize': optimize = True
        elif key == '--mongo-drop': do_mongo_drop = True
        elif key == '--reset': do_reset = True
        elif key == '--dry-run': dry_run = 1
        elif key == '--force': force = True
        elif key == '--throttle': throttle = float(val)

    if not verbose: sql_util.disable_warnings()

    if SpinConfig.config['game_id']+'_battles' not in SpinConfig.config.get('pgsql_servers',{}):
        if verbose:
            print SpinConfig.config['game_id']+'_battles', 'not present in config.json'
        sys.exit(0)

    cfg = SpinConfig.get_pgsql_config(SpinConfig.config['game_id']+'_battles')

    if (not force) and \
       (SpinConfig.in_maintenance_window(cfg, time_now = time_now) or SpinConfig.in_maintenance_window(cfg, time_now = time_now + 1800)): # allow for 30min to operate
        if verbose: print 'in database maintenance window, aborting'
        sys.exit(0)

    with SpinSingletonProcess.SingletonProcess('battles-to-psql-%s' % (game_id)):

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

        con = psycopg2.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        cur = con.cursor()

        tbl = cfg['table_prefix']+'battles'

        if verbose: print 'setting up tables and indices for', tbl
        if do_reset and dry_run < 2:
            cur.execute("DROP TABLE "+sql_util.sym(tbl))
        if dry_run < 2: sql_util.ensure_table(cur, tbl, battles_schema(sql_util))
        con.commit()

        end_time = time_now - 60 # don't get too close to "now"

        start_time = -1
        if dry_run < 2:
            if verbose: print 'MAX(time) query...'
            cur.execute("SELECT MAX(time) FROM "+sql_util.sym(tbl))
            row = cur.fetchone()
            if row and row[0]:
                start_time = row[0]

        if verbose: print 'SQL last time', start_time

        n_updated = 0
        summaries = nosql_client.battles_get(-1, -1, -1, -1, time_range = [start_time+1, end_time], oldest_first = True, streaming = True)

        if verbose: print 'found some battles...'

        batch = []
        total = 0

        for row in summaries:
            assert len(row['involved_players']) >= 1 and len(row['involved_players']) <= 2

            player0 = player1 = None
            if len(row['involved_players']) >= 1:
                player0 = row['involved_players'][0]
            if len(row['involved_players']) >= 2:
                player1 = row['involved_players'][1]

            alliance0 = alliance1 = None
            if 'involved_alliances' in row:
                if len(row['involved_alliances']) >= 1:
                    alliance0 = row['involved_alliances'][0]
                if len(row['involved_alliances']) >= 2:
                    alliance1 = row['involved_alliances'][1]

            assert ('_id' not in row) # don't rely on MongoDB object IDs
            keyvals = [('battle_id', row['battle_id']), # make_log_id(row)
                       ('time', row['time']),
                       ('involved_player0', player0),
                       ('involved_player1', player1),
                       ('involved_alliance0', alliance0),
                       ('involved_alliance1', alliance1),
                       ('is_ai', (row.get('attacker_type') == 'ai' or row.get('defender_type') == 'ai') and (not row.get('ladder_state'))),
                       ('summary', SpinJSON.dumps(row))]

            batch.append(keyvals)

            if (not dry_run) and len(batch) >= commit_interval:
                sql_util.do_insert_batch(cur, tbl, batch)
                con.commit()

                if verbose:
                    print 'inserted', len(batch), 'battles'

                total += len(batch)
                batch = []

                if throttle > 0: time.sleep(throttle)

        if (not dry_run) and batch:
            sql_util.do_insert_batch(cur, tbl, batch)
            con.commit()
            total += len(batch)
            batch = []

        if verbose:
            print 'total', total, 'battles'

        if not dry_run and optimize:
            old = con.isolation_level
            con.set_isolation_level(0)
            try:
                if verbose: print 'VACUUMing', tbl, '...'
                cur.execute("VACUUM " + sql_util.sym(tbl))
                con.commit()
            finally:
                con.set_isolation_level(old)

