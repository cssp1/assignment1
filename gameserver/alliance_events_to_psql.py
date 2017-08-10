#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump log_alliance_members events from MongoDB to PostgreSQL for warehousing

import sys, time, getopt, calendar
import SpinConfig
import SpinNoSQL
import SpinETL
import SpinSingletonProcess
import psycopg2
import SpinSQLUtil

time_now = int(time.time())

sql_util = SpinSQLUtil.PostgreSQLUtil()

def log_alliance_members_schema(sql_util):
    return { 'fields': [('_id', 'VARCHAR(64) NOT NULL'),
                        ('time', 'INT8 NOT NULL'),
                        ('event_name', 'TEXT NOT NULL'),
                        ('user_id', 'INT4'),
                        ('target_id', 'INT4'),
                        ('alliance_id', 'INT4'),
                        ('role', 'INT4'),
                        ('alliance_ui_name', 'TEXT'),
                        ('alliance_chat_tag', 'TEXT'),
                        ],
             'indices': { 'by_id': {'keys': [('_id','ASC')], 'unique': True },
                          'by_time': {'keys': [('time','ASC')] },
                          'by_user_id_time': {'keys': [('user_id','ASC'),('time','ASC')],
                                              'where': 'user_id IS NOT NULL'},
                          'by_target_id_time': {'keys': [('target_id','ASC'),('time','ASC')],
                                                'where': 'target_id IS NOT NULL'},
                          }
             }


if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 100
    verbose = True
    optimize = False
    force = False
    source = 'mongodb'
    do_reset = False
    dry_run = 0
    throttle = 0

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['reset','optimize','dry-run','force','throttle=','s3='])

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
        elif key == '--s3':
            # specify starting date for backfill, like "--s3 2015-04-01" (first recording starts here)
            source = 's3'
            source_ymd = map(int, val.split('-'))
            assert len(source_ymd) == 3

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

    with SpinSingletonProcess.SingletonProcess('alliance-events-to-psql-%s' % (game_id)):

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

        con = psycopg2.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        cur = con.cursor()

        tbl = cfg['table_prefix']+'log_alliance_members'

        if verbose: print 'setting up tables and indices for', tbl
        if do_reset and dry_run < 2:
            cur.execute("DROP TABLE "+sql_util.sym(tbl))
        if dry_run < 2: sql_util.ensure_table(cur, tbl, log_alliance_members_schema(sql_util))
        con.commit()

        end_time = time_now - 60 # don't get too close to "now"

        start_time = -1
        if dry_run < 2:
            if verbose: print 'MAX(time) query...'
            cur.execute("SELECT MAX(time) FROM "+sql_util.sym(tbl))
            row = cur.fetchone()
            if row and row[0]:
                start_time = row[0]
            con.commit()

        if verbose: print 'SQL last time', start_time

        alliance_info_cache = {}

        batch = []
        total = 0

        if source == 's3':
            start_time = calendar.timegm(source_ymd + [0,0,0])
            if verbose: print 'Source = S3, starting at', start_time
            row_iter = SpinETL.iterate_from_s3(SpinConfig.game(), 'spinpunch-logs',
                                               'alliance_member_events',
                                               start_time, end_time, verbose = verbose)
        else:
            row_iter = SpinETL.iterate_from_mongodb(SpinConfig.config['game_id'],
                                                    'log_alliance_members',
                                                    start_time, end_time)

        for row in row_iter:

            keyvals = [('_id', row['_id']),
                       ('time', row['time']),
                       ('event_name', row['event_name']),
                       ('user_id', row['user_id']),
                       ('role', row.get('role')),
                       ('target_id', row.get('target_id')),
                       ('alliance_id', row['alliance_id']),
                       ]

            # events that affect user_id
            if row['event_name'] in ('4610_alliance_member_joined',
                                     '4620_alliance_member_left'):
                pass
            # events that affect target_id
            elif row['event_name'] in ('4625_alliance_member_kicked',
                                       '4626_alliance_member_promoted',
                                       '4650_alliance_member_join_request_accepted'):
                pass
            else:
                continue # unlogged event

            alliance_ui_name = None
            alliance_chat_tag = None

            if 'alliance_ui_name' in row:
                alliance_ui_name = row['alliance_ui_name']
                alliance_chat_tag = row['alliance_chat_tag']

            else:
                # query current ui_name/tag
                if row['alliance_id'] not in alliance_info_cache:
                    alliance_info_cache[row['alliance_id']] = nosql_client.get_alliance_info(row['alliance_id'])

                info = alliance_info_cache.get(row['alliance_id'])
                if info:
                    alliance_ui_name = info.get('ui_name')
                    alliance_chat_tag = info.get('chat_tag')

            keyvals.append(('alliance_ui_name', alliance_ui_name))
            keyvals.append(('alliance_chat_tag', alliance_chat_tag))

            batch.append(keyvals)

            if (not dry_run) and len(batch) >= commit_interval:
                sql_util.do_insert_batch(cur, tbl, batch)
                con.commit()

                if verbose:
                    print 'inserted', len(batch)

                total += len(batch)
                del batch[:]

                if throttle > 0: time.sleep(throttle)

        if (not dry_run) and batch:
            sql_util.do_insert_batch(cur, tbl, batch)
            con.commit()
            total += len(batch)
            del batch[:]

        if verbose:
            print 'total', total

        if not dry_run and optimize and 0: # disable vacuum since there will be no garbage unless we starting pruning
            old = con.isolation_level
            con.set_isolation_level(0)
            try:
                if verbose: print 'VACUUMing', tbl, '...'
                cur.execute("VACUUM " + sql_util.sym(tbl))
                con.commit()
            finally:
                con.set_isolation_level(old)

