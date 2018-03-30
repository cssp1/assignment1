#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "econ_res" table from MongoDB to a SQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import SpinMySQLdb

time_now = int(time.time())

# note: in order to reduce database load, the "raw" econ_res table is actually a per-hour "presummary"
def econ_res_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4')] + \
                      sql_util.summary_in_dimensions() + \
                      [('category', 'VARCHAR(32) NOT NULL'),
                       ('subcategory', 'VARCHAR(32)'),
                       ('spec', 'VARCHAR(32)'),
                       ('level', 'INT2'),
                       ('resource', 'VARCHAR(32) NOT NULL'),
                       ('amount', 'INT4 NOT NULL')], # XXX might need to become INT8
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }

def econ_res_summary_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('category', 'VARCHAR(32) NOT NULL'),
                       ('subcategory', 'VARCHAR(32)'),
                       ('spec', 'VARCHAR(32)'),
                       ('level', 'INT2'),
                       ('resource', 'VARCHAR(32) NOT NULL'),
                       ('amount', 'INT8 NOT NULL')],
            'indices': {'by_day': {'unique':False, 'keys': [('day','ASC')]}},
            }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    do_prune = False
    do_optimize = False
    presummarize = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    with SpinSingletonProcess.SingletonProcess('econ_res_to_sql-%s' % game_id):

        cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
        con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        econ_res_table = cfg['table_prefix']+game_id+'_econ_res'
        econ_res_summary_table = cfg['table_prefix']+game_id+'_econ_res_daily_summary'

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

        cur = con.cursor(SpinMySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, econ_res_table, econ_res_schema(sql_util))
        sql_util.ensure_table(cur, econ_res_summary_table, econ_res_summary_schema(sql_util))
        con.commit()

        # set time range for MongoDB query
        # assume that if we have any events for a given hour, then we have all of them
        start_time = -1
        start_operator = '$gt'
        end_time = 3600*((time_now - 600)//3600)  # skip entries too close to "now" to ensure all events for a given hour have all arrived

        # find most recent already-converted event in SQL
        cur.execute("SELECT time FROM "+sql_util.sym(econ_res_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
            if presummarize and start_time > 0:
                start_time = 3600*(start_time//3600 + 1) # start of next hour that's not already recorded
                start_operator = '$gte'
        con.commit()

        if verbose: print 'start_time', start_operator, start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()

        qs = {'time':{start_operator:start_time, '$lt': end_time}}

        accum = {}

        for row in nosql_client.log_buffer_table('econ_res').find(qs):
            sum_keyvals = sql_util.parse_brief_summary(row)
            if row.get('developer',False): continue # skip events by developers

            if presummarize:
                # create a summary key consisting of [hour, summary dimensions, category, subcategory, spec, level, resource]
                hour = 3600*(row['time']//3600)
                # use literal summary values except for prev_receipts which needs to get encoded to spend_bracket
                dims = [(v if (not k.endswith('prev_receipts')) else sql_util.get_spend_bracket(v)) for k,v in sum_keyvals]
                for resname, amount in row['res'].iteritems():
                    if amount != 0:
                        accum_key = tuple([hour,] + dims + [row['cat'],row.get('sub',None),resname,row.get('spec',None),row.get('level',None)])
                        accum[accum_key] = accum.get(accum_key,0) + amount
            else:
                sql_util.do_insert_batch(cur, econ_res_table,
                                         [[('time',row['time']),
                                           ('user_id',row['user_id'])] + \
                                          sum_keyvals + \
                                          [('category',row['cat']),
                                           ('subcategory',row.get('sub',None)),
                                           ('spec',row.get('spec',None)),
                                           ('level',row.get('level',None)),
                                           ('resource',resname),
                                           ('amount',amount)] for resname, amount in row['res'].iteritems() if amount != 0])
                affected_days.add(86400*(row['time']//86400))

            total += 1
            batch += 1
            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                if presummarize:
                    if verbose: print total, 'summarized'
                else:
                    con.commit()
                    if verbose: print total, 'inserted'

        if presummarize: # dump the accumulators to SQL
            dim_keys = [k for k,v in sql_util.summary_in_dimensions()]
            ndims = len(dim_keys)
            sql_util.do_insert_batch(cur, econ_res_table,
                                     [[('time',key[0]),
                                       ('user_id',None)] + \
                                      [(dim_keys[i], key[i+1]) for i in xrange(ndims)] + \
                                      [('category',key[ndims+1+0]),
                                       ('subcategory',key[ndims+1+1]),
                                       ('resource',key[ndims+1+2]),
                                       ('spec',key[ndims+1+3]),
                                       ('level',key[ndims+1+4]),
                                       ('amount',amount)] for key, amount in accum.iteritems()])
            for key in accum:
                affected_days.add(86400*(key[0]//86400))

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'

        # update summary

        dt = 86400

        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(econ_res_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            econ_res_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            econ_res_range = None

        # check how much summary data we already have
        cur.execute("SELECT MIN(day) AS begin, MAX(day) AS end FROM "+sql_util.sym(econ_res_summary_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['begin'] and rows[0]['end']:
            # we already have summary data - update it incrementally
            if econ_res_range: # fill in any missing trailing summary data
                source_days = sorted(affected_days.union(set(xrange(dt*(rows[0]['end']//dt + 1), dt*(econ_res_range[1]//dt + 1), dt))))
            else:
                source_days = sorted(list(affected_days))
        else:
            # replace entire summary
            if econ_res_range:
                source_days = range(dt*(econ_res_range[0]//dt), dt*(econ_res_range[1]//dt + 1), dt)
            else:
                source_days = None

        if source_days:
            for day_start in source_days:
                if verbose: print 'updating', econ_res_summary_table, 'at', time.strftime('%Y%m%d', time.gmtime(day_start))

                # delete entries for the date range we're about to update
                cur.execute("DELETE FROM "+sql_util.sym(econ_res_summary_table)+" WHERE day >= %s AND day < %s+86400", [day_start,]*2)

                cur.execute("INSERT INTO "+sql_util.sym(econ_res_summary_table) + \
                            "SELECT 86400*FLOOR(econ_res.time/86400.0) AS day," + \
                            "       econ_res.frame_platform AS frame_platform," + \
                            "       econ_res.country_tier AS country_tier," + \
                            "       econ_res.townhall_level AS townhall_level," + \
                            "       "+sql_util.encode_spend_bracket("econ_res.prev_receipts")+" AS spend_bracket," + \
                            "       econ_res.category AS category," + \
                            "       econ_res.subcategory AS subcategory," + \
                            "       econ_res.spec AS spec," + \
                            "       econ_res.level AS level," + \
                            "       econ_res.resource AS resource," + \
                            "       SUM(amount) AS amount " + \
                            "FROM " + sql_util.sym(econ_res_table) + " econ_res " + \
                            "WHERE econ_res.time >= %s AND econ_res.time < %s+86400 " + \
                            "GROUP BY 86400*FLOOR(time/86400.0), frame_platform, country_tier, townhall_level, spend_bracket, category, subcategory, spec, level, resource ORDER BY NULL", [day_start,]*2)

                con.commit()
        else:
            if verbose: print 'no change to', econ_res_summary_table

        if do_prune:
            # drop old data
            KEEP_DAYS = {'fs': 30.0}.get(game_id, 1.0)
            old_limit = time_now - int(KEEP_DAYS * 86400)

            if affected_days: # don't delete any data from days that affected the summary we just made
                old_limit = min(old_limit, min(affected_days))

            if verbose: print 'pruning', econ_res_table, 'limit was', time_now - int(KEEP_DAYS * 86400), 'after affected_days limit', old_limit

            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(econ_res_table)+" WHERE time < %s", [old_limit])
            if do_optimize:
                if verbose: print 'optimizing', econ_res_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(econ_res_table))
            con.commit()
