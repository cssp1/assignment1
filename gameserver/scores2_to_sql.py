#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump player_scores2 from MongoDB to SQL for warehousing

import sys, time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSingletonProcess
import psycopg2
import SpinSQLUtil
import Scores2

gamedata = None
time_now = int(time.time())

sql_util = SpinSQLUtil.PostgreSQLUtil()

def scores2_schema(id_field):
    return { 'fields': [(id_field, 'INT4 NOT NULL'),
                        ('stat', 'VARCHAR(32) NOT NULL'),
                        ('time_scope', 'VARCHAR(8) NOT NULL'),
                        ('time_loc', 'INT4 NOT NULL'),
                        ('space_scope', 'VARCHAR(10) NOT NULL'),
                        ('space_loc', 'VARCHAR(16) NOT NULL'),
                        ('extra_scope', 'VARCHAR(8)'),
                        ('extra_loc', 'VARCHAR(16)'),
                        ('val', 'FLOAT8 NOT NULL'),
                        ('mtime', 'INT8 NOT NULL')
                        ],
             # note: index stat AFTER time so that we can do time range queries quickly
             'indices': { 'by_id_unique': {'unique':True,
                                    'keys':[(id_field,'ASC'), ('time_scope','ASC'), ('time_loc','ASC'), ('stat','ASC'), ('space_scope','ASC'), ('space_loc','ASC'),
                                            # extra_scope and extra_loc must be non-null in the index for the ON CONFLICT upsert to work
                                            ("COALESCE(extra_scope, '')",'ASC'), ("COALESCE(extra_loc, '')",'ASC')] },
                          'by_stat': {'keys': [('time_scope','ASC'), ('time_loc','ASC'), ('stat','ASC'), ('space_scope','ASC'), ('space_loc','ASC'),
                                               ('extra_scope','ASC'), ('extra_loc','ASC'), ('val','DESC')]},
                          'by_mtime': {'keys': [('time_scope','ASC'), ('time_loc','ASC'), ('mtime','ASC')]},
                          }
             }


if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    optimize = False
    force = False
    do_reset = False
    do_mongo_drop = False
    dry_run = 0

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['reset','mongo-drop','optimize','dry-run','force'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--optimize': optimize = True
        elif key == '--mongo-drop': do_mongo_drop = True
        elif key == '--reset': do_reset = True
        elif key == '--dry-run': dry_run = 1
        elif key == '--force': force = True

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_pgsql_config(SpinConfig.config['game_id']+'_scores2')

    if (not force) and \
       (SpinConfig.in_maintenance_window(cfg, time_now = time_now) or SpinConfig.in_maintenance_window(cfg, time_now = time_now + 1800)): # allow for 30min to operate
        if verbose: print 'in database maintenance window, aborting'
        sys.exit(0)

    with SpinSingletonProcess.SingletonProcess('scores2-to-sql-%s' % (game_id)):

        con = psycopg2.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        tbl = { 'player': cfg['table_prefix']+'player_scores2',
                'alliance': cfg['table_prefix']+'alliance_scores2' }

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
        mongo_scores = Scores2.MongoScores2(nosql_client)

        cur = con.cursor()

        for kind in tbl:
            if verbose: print 'setting up tables, indices, and functions for', tbl[kind]
            if do_reset and dry_run < 2:
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl[kind]))
            if dry_run < 2: sql_util.ensure_table(cur, tbl[kind], scores2_schema(Scores2.ID_FIELD[kind]))

        con.commit()

        now_time_coords = Scores2.make_time_coords(time_now,
                                                   SpinConfig.get_pvp_season(gamedata['matchmaking']['season_starts'], time_now),
                                                   SpinConfig.get_pvp_week(gamedata['matchmaking']['week_origin'], time_now),
                                                   SpinConfig.get_pvp_day(gamedata['matchmaking']['week_origin'], time_now),
                                                   use_day = True)

        for kind in tbl:
            # for each time scope
            for freq in Scores2.FREQ_VALUES:

                # find earliest time loc recorded for this scope in MongoDB
                live_time_range = mongo_scores._scores2_get_time_range(kind, freq)
                if verbose:
                    print kind, freq, 'live time range', live_time_range

                if live_time_range[0] < 0: continue # no data

                for loc in xrange(live_time_range[0], live_time_range[1]+1):
                    # find latest time loc recorded for this scope in SQL
                    sql_last_mtime = -1

                    if dry_run < 2:
                        if verbose: print kind, freq, loc, 'MAX(mtime) query...'
                        cur.execute("SELECT MAX(mtime) FROM "+sql_util.sym(tbl[kind])+" WHERE time_scope = %s AND time_loc = %s", [freq, loc])
                        row = cur.fetchone()
                        if row and row[0]:
                            sql_last_mtime = row[0]

                    if verbose: print kind, freq, loc, 'SQL latest mtime', sql_last_mtime

                    # update all new stats for this time loc
                    n_updated = 0
                    mongo_stats = mongo_scores._scores2_get_stats_for_time(kind, freq, loc, mtime_gte = sql_last_mtime)
                    mongo_count = mongo_stats.count()

                    if verbose: print kind, freq, loc, 'inserting', mongo_count, 'scores...'

                    batch = []

                    for row in mongo_stats:
                        assert row['axes']['time'][0] == freq and row['axes']['time'][1] == loc # sanity check
                        keyvals = [(Scores2.ID_FIELD[kind], int(row[Scores2.ID_FIELD[kind]])),
                                   ('stat', row['stat']),
                                   ('time_scope', freq), ('time_loc', int(loc)),
                                   ('space_scope', row['axes']['space'][0]), ('space_loc', row['axes']['space'][1])]

                        has_extra = False
                        skip_this_row = False
                        for name, scope_loc in row['axes'].iteritems():
                            if name not in ('time','space'):
                                # arbitrary extra axes
                                assert not has_extra # only one
                                if name != 'challenge':
                                    print 'invalid extra axis name', name
                                    skip_this_row = True
                                    break
                                keyvals += [('extra_scope', scope_loc[0]), ('extra_loc', scope_loc[1])]
                                has_extra = True
                        if skip_this_row:
                            continue

                        if not has_extra:
                            # ensure every keyvals[] list has extra_scope and extra_loc, even if they are null
                            keyvals += [('extra_scope',None), ('extra_loc',None)]

                        keyvals += [('val', float(row['val'])), ('mtime', int(row.get('mtime',-1)))]
                        batch.append(keyvals)
                        n_updated += 1

                    if (not dry_run) and batch:
                        # note: keyvals2[-2] and [-1] are second copies of (val, mtime) for the DO UPDATE SET clause
                        cur.executemany("""
INSERT INTO """ + tbl[kind] + """ (""" + Scores2.ID_FIELD[kind] + """,stat,time_scope,time_loc,space_scope,space_loc,extra_scope,extra_loc,val,mtime)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (""" + Scores2.ID_FIELD[kind] + """,stat,time_scope,time_loc,space_scope,space_loc, COALESCE(extra_scope, ''), COALESCE(extra_loc, ''))
DO UPDATE SET val = %s, mtime = %s
""", [([v for k,v in keyvals2] + [keyvals2[-2][1], keyvals2[-1][1]]) for keyvals2 in batch])
                        con.commit() # new scores become permanent in SQL

                    if verbose:
                        if n_updated > 0:
                            print kind, freq, loc, 'updated', n_updated, 'rows', 'mongo_count', mongo_count

                    if do_mongo_drop:
                        # remove historical data (earlier than this time period minus keep_history) from Mongo
                        keep_history = {Scores2.FREQ_ALL: 0,
                                        Scores2.FREQ_SEASON: 1, # keep last season
                                        Scores2.FREQ_WEEK: 2 # keep last TWO weeks
                                        }[freq]
                        if loc < now_time_coords[freq] - keep_history:

                            # THIS DOES NOT FIX THE RACE CONDITION, but it's close enough that I wouldn't worry about it.
                            if mongo_scores._scores2_get_stats_for_time(kind, freq, loc, mtime_gte = sql_last_mtime).count() != mongo_count:
                                if verbose: print kind, freq, loc, 'NOT dropping this MongoDB collection, modifications were made since scan started'
                                pass
                            else:
                                if verbose: print kind, freq, loc, 'dropping from MongoDB'
                                if not dry_run: mongo_scores._scores2_drop_stats_for_time(kind, freq, loc)
            if not dry_run and optimize:
                old = con.isolation_level
                con.set_isolation_level(0)
                try:
                    if verbose: print 'VACUUMing', tbl[kind], '...'
                    cur.execute("VACUUM " + sql_util.sym(tbl[kind]))
                    con.commit()
                finally:
                    con.set_isolation_level(old)

