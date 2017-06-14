#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_gamebucks" table from MongoDB to a MySQL database for analytics

import sys, time, getopt
import SpinConfig
import SpinUpcache
import SpinJSON
import SpinETL
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())

# schema migration to add summary dimensions:

# ALTER TABLE tr_store DROP PRIMARY KEY, DROP _id, CHANGE time time INT8 NOT NULL, ADD COLUMN frame_platform CHAR(2), ADD COLUMN country_tier CHAR(1), ADD COLUMN townhall_level INT4, ADD COLUMN prev_receipts FLOAT4;
# ALTER TABLE tr_store_daily_summary DROP INDEX tr_store_daily_summary_master, ADD COLUMN frame_platform CHAR(2) AFTER day, ADD COLUMN country_tier CHAR(1) AFTER frame_platform, ADD COLUMN spend_bracket INT4 AFTER country_tier, MODIFY COLUMN townhall_level INT4 AFTER country_tier, MODIFY COLUMN currency VARCHAR(16) AFTER spend_bracket, ADD UNIQUE INDEX tr_store_daily_summary_master (day ASC, frame_platform ASC, country_tier ASC, townhall_level ASC, spend_bracket ASC, currency ASC, category ASC, subcategory ASC, level ASC, item ASC);

# ALTER TABLE tr_unit_cost DROP INDEX tr_unit_cost_by_id, DROP COLUMN store_id, ADD COLUMN frame_platform CHAR(2) AFTER user_id, ADD COLUMN country_tier CHAR(1) AFTER frame_platform, ADD COLUMN townhall_level INT4 AFTER country_tier, ADD COLUMN prev_receipts FLOAT4 AFTER townhall_level;

# ALTER TABLE tr_unit_cost_daily_summary DROP INDEX tr_unit_cost_daily_summary_master, ADD COLUMN frame_platform CHAR(2) AFTER day, ADD COLUMN country_tier CHAR(1) AFTER frame_platform, ADD COLUMN spend_bracket INT4 AFTER country_tier, MODIFY COLUMN townhall_level INT4 AFTER country_tier, ADD UNIQUE INDEX tr_unit_cost_daily_summary_master (day ASC, frame_platform ASC, country_tier ASC, townhall_level ASC, spend_bracket ASC, specname ASC, location ASC);

# backfill summary dimensions
#UPDATE tr_store store LEFT JOIN tr_upcache upcache ON upcache.user_id = store.user_id SET
#store.frame_platform=IFNULL(store.frame_platform,IFNULL(upcache.frame_platform,'fb')),
#store.country_tier=IFNULL(store.country_tier, upcache.country_tier),
#store.townhall_level=IFNULL(store.townhall_level, IFNULL((SELECT MAX(th.townhall_level) FROM tr_townhall_at_time th WHERE th.user_id = store.user_id AND th.time < store.time),1)),
#store.prev_receipts=(SELECT SUM(0.01*c2.usd_receipts_cents) FROM tr_credits c2 WHERE c2.user_id = store.user_id AND c2.time < store.time) -- ensure (user_id, time) index on credits!
#;

#UPDATE tr_unit_cost unit_cost LEFT JOIN tr_upcache upcache ON upcache.user_id = unit_cost.user_id SET
#unit_cost.frame_platform=IFNULL(unit_cost.frame_platform,IFNULL(upcache.frame_platform,'fb')),
#unit_cost.country_tier=IFNULL(unit_cost.country_tier, upcache.country_tier),
#unit_cost.townhall_level=IF(unit_cost.townhall_level IS NULL or unit_cost.townhall_level < 1, IFNULL((SELECT MAX(th.townhall_level) FROM tr_townhall_at_time th WHERE th.user_id = unit_cost.user_id AND th.time < unit_cost.time),1), unit_cost.townhall_level),
#unit_cost.prev_receipts=(SELECT SUM(0.01*c2.usd_receipts_cents) FROM tr_credits c2 WHERE c2.user_id = unit_cost.user_id AND c2.time < unit_cost.time) -- ensure (user_id, time) index on credits!
#;

def store_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('price', 'INT4'),
                       ('currency', 'VARCHAR(16)'),
                       ('stack', 'INT4'),
                       ('ui_index', 'INT4'),
                       ('item', 'VARCHAR(128)'),
                       ('description', 'VARCHAR(255)'),
                       ('category', 'VARCHAR(64)'),
                       ('subcategory', 'VARCHAR(64)'),
                       ('level', 'INT4')],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }

def store_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('currency', 'VARCHAR(16)'),
                       ('category', 'VARCHAR(64)'),
                       ('subcategory', 'VARCHAR(64)'),
                       ('level', 'INT4'),
                       ('item', 'VARCHAR(128)'),
                       # ---
                       ('count', 'INT8'),
                       ('total_price', 'INT8'),
                       ('total_stack', 'INT8')],
            'indices': {'master': {'keys': [(interval,'ASC')] # + \
                                   # [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions()] + \
                                   # [('currency','ASC'),('category','ASC'),('subcategory','ASC'),('level','ASC'),('item','ASC')]
                                   }},
            }

# track user_ids of players with top spend in each summary segment
def store_top_spenders_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
            sql_util.summary_out_dimensions() + \
            [('currency', 'VARCHAR(16)'),
             # OUTPUTS
             ('user_id', 'INT4 NOT NULL'),
             ('num_purchases', 'INT4 NOT NULL'),
             ('total_price', 'INT8 NOT NULL'),
             ],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }

# temp table used for building top_spenders - this is the total spend of ALL users, by user, within a time window
def store_by_user_temp_schema(sql_util):
    return {'fields': sql_util.summary_out_dimensions() + \
            [('currency', 'VARCHAR(16)'),
             ('user_id', 'INT4 NOT NULL'),
             ('num_purchases', 'INT4 NOT NULL'),
             ('total_price', 'INT8 NOT NULL'),
             ],
            'indices': {'by_interval': {'unique':False, 'keys': [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions() + [('currency','ASC'),('total_price','DESC')]]}}
            }

def unit_cost_schema(sql_util):
    # a bunch of intentional redundancy here to isolate it from the store table
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('user_id', 'INT4 NOT NULL')] + \
                      sql_util.summary_in_dimensions() + \
                      [('specname', 'VARCHAR(128) NOT NULL'),
                       ('gamebucks', 'FLOAT4 NOT NULL'),
                       ('location', 'VARCHAR(16) NOT NULL')],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }

def unit_cost_summary_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL')] + \
                      sql_util.summary_out_dimensions() + \
                      [('specname', 'VARCHAR(128) NOT NULL'),
                       ('location', 'VARCHAR(16) NOT NULL'),
                       # ---
                       ('count', 'INT8'),
                       ('gamebucks', 'FLOAT4 NOT NULL'),
                       ],
            'indices': {'master': {'unique':True, 'keys': [('day','ASC')] + [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions()] + [('specname','ASC'),('location','ASC')]}},
            }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False
    do_prune = False
    do_optimize = False
    do_unit_cost = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','dry-run','unit-cost'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True
        elif key == '--unit-cost': do_unit_cost = True

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    store_table = cfg['table_prefix']+game_id+'_store'
    store_daily_summary_table = cfg['table_prefix']+game_id+'_store_daily_summary'
    store_hourly_summary_table = cfg['table_prefix']+game_id+'_store_hourly_summary'
    store_top_spenders_28d_table = cfg['table_prefix']+game_id+'_store_top_spenders_28d'
    unit_cost_table = cfg['table_prefix']+game_id+'_unit_cost'
    unit_cost_daily_summary_table = cfg['table_prefix']+game_id+'_unit_cost_daily_summary'

    with SpinSingletonProcess.SingletonProcess('gamebucks_to_mysql-%s' % game_id):

        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config((game_id+'test') if SpinConfig.config['game_id'].endswith('test') else game_id))

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, store_table, store_schema(sql_util))
        sql_util.ensure_table(cur, store_daily_summary_table, store_summary_schema(sql_util, 'day'))
        sql_util.ensure_table(cur, store_hourly_summary_table, store_summary_schema(sql_util, 'hour'))
        sql_util.ensure_table(cur, store_top_spenders_28d_table, store_top_spenders_schema(sql_util, 'day'))
        if do_unit_cost:
            sql_util.ensure_table(cur, unit_cost_table, unit_cost_schema(sql_util))
            sql_util.ensure_table(cur, unit_cost_daily_summary_table, unit_cost_summary_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(store_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_days = set()
        affected_hours = set()

        qs = {'time':{'$gt':start_time, '$lt':end_time}}

        for row in nosql_client.log_buffer_table('log_gamebucks').find(qs):
            keyvals = [('time',row['time']),
                       ('user_id',row['user_id'])]

            if 'summary' in row:
                if row['summary'].get('developer',False): continue # skip events by developers
                summary = sql_util.parse_brief_summary(row['summary'])
            else:
                summary = []

            keyvals += summary

            if row['event_name'] in ('1400_gamebucks_spent', '1401_fungible_spent', '1402_score_spent'):
                if row['event_name'] == '1400_gamebucks_spent':
                    keyvals.append(('price',row['gamebucks_price']))
                    keyvals.append(('currency','gamebucks'))
                elif row['event_name'] in ('1401_fungible_spent', '1402_score_spent'):
                    keyvals.append(('price',row['price']))
                    keyvals.append(('currency',row['price_currency']))

                descr = row['Billing Description']
                keyvals.append(('description',descr))
                if descr.startswith("BUY_ITEM,"):
                    spellarg_str = descr[len("BUY_ITEM,"):]
                    if ("':" in spellarg_str): # old Python repr()
                        spellarg = eval(spellarg_str)
                    else:
                        spellarg = SpinJSON.loads(spellarg_str)
                    skudata = spellarg['skudata']
                    if 'loot_table' in skudata:
                        keyvals.append(('item', skudata['loot_table'])) # abuse "item" to include loot tables as well
                    elif 'item' in skudata:
                        keyvals.append(('item', skudata['item']))
                    keyvals.append(('stack', skudata.get('stack',1)))
                    if spellarg.get('ui_index',-1) >= 0:
                        keyvals.append(('ui_index', spellarg['ui_index']))
                elif (descr.startswith("BUY_RANDOM") or descr.startswith("FREE_RANDOM")) and descr.find(',') > 0:
                    items = SpinJSON.loads(descr[descr.find(',')+1:])['items']
                    assert len(items) == 1
                    keyvals.append(('item', items[0]['spec']))
                    keyvals.append(('stack', items[0].get('stack',1)))
                else:
                    pass # just go by the description for other spells

                cat, subcat, level = SpinUpcache.classify_purchase(gamedata, descr)
                keyvals.append(('category', cat))
                keyvals.append(('subcategory', subcat))
                keyvals.append(('level', level))

                if do_unit_cost and ('unit_cost' in row):
                    kvlist = []
                    for location, r in row['unit_cost'].iteritems():
                        for specname, cost in r.iteritems():
                            kvlist.append([('time',row['time']),
                                           ('user_id',row['user_id']),
                                           ('specname',specname),
                                           ('gamebucks',cost),
                                           ('location',location)] + summary)
                    if not dry_run:
                        sql_util.do_insert_batch(cur, unit_cost_table, kvlist)

            elif row['event_name'] == '5120_buy_item':
                keyvals.append(('price',row['price']))
                keyvals.append(('currency',row['price_currency']))
                assert len(row['items']) == 1
                item = row['items'][0]
                keyvals.append(('item',item['spec']))
                keyvals.append(('stack',item.get('stack',1)))
                if row.get('ui_index',-1) >= 0:
                    keyvals.append(('ui_index',row['ui_index']))
            else:
                if verbose: print 'unrecognized event', row
                continue

            if not dry_run:
                sql_util.do_insert(cur, store_table, keyvals)
            else:
                print keyvals

            batch += 1
            total += 1
            affected_days.add(86400*(row['time']//86400))
            affected_hours.add(3600*(row['time']//3600))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)', len(affected_hours), 'hour(s)'


        # update summary
        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(store_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            store_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            store_range = None

        def update_store_summary(cur, table, interval, day_start, dt):
            cur.execute("INSERT INTO "+sql_util.sym(table) + \
                        "SELECT %s*FLOOR(store.time/%s) AS "+interval+"," + \
                        "       store.frame_platform AS frame_platform," + \
                        "       store.country_tier AS country_tier," + \
                        "       store.townhall_level AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("store.prev_receipts")+" AS spend_bracket," + \
                        "       store.currency AS currency," + \
                        "       store.category AS category," + \
                        "       store.subcategory AS subcategory," + \
                        "       store.level AS level," + \
                        "       store.item AS item," + \
                        "       SUM(1) AS count, " + \
                        "       SUM(price) AS total_price, " + \
                        "       SUM(stack) AS total_stack " + \
                        "FROM " + sql_util.sym(store_table) + " store " + \
                        "WHERE store.time >= %s AND store.time < %s+%s AND (store.category IS NOT NULL OR store.item IS NOT NULL)" + \
                        "GROUP BY "+interval+", frame_platform, country_tier, townhall_level, spend_bracket, currency, category, subcategory, level, item ORDER BY NULL", [dt,dt,day_start,day_start,dt])

        def update_unit_cost_summary(cur, table, interval, day_start, dt):
            cur.execute("INSERT INTO "+sql_util.sym(unit_cost_daily_summary_table) + \
                        "SELECT 86400*FLOOR(cost.time/86400.0) AS day," + \
                        "       cost.frame_platform AS frame_platform," + \
                        "       cost.country_tier AS country_tier," + \
                        "       cost.townhall_level AS townhall_level," + \
                        "       "+sql_util.encode_spend_bracket("cost.prev_receipts")+" AS spend_bracket," + \
                        "       cost.specname AS specname," + \
                        "       cost.location AS location," + \
                        "       SUM(1) AS count, " + \
                        "       SUM(cost.gamebucks) AS gamebucks " + \
                        "FROM " + sql_util.sym(unit_cost_table) + " cost " + \
                        "WHERE cost.time >= %s AND cost.time < %s+86400 " + \
                        "GROUP BY 86400*FLOOR(cost.time/86400.0), frame_platform, country_tier, townhall_level, spend_bracket, specname, location ORDER BY NULL", [day_start,]*2)

        for table, interval, dt, affected in ((store_hourly_summary_table, 'hour', 3600, affected_hours),
                                              (store_daily_summary_table, 'day', 86400, affected_days)):
            SpinETL.update_summary(sql_util, con, cur, table, affected, store_range, interval, dt,
                                   verbose = verbose, resummarize_tail = dt, execute_func = update_store_summary)

        if do_unit_cost:
            SpinETL.update_summary(sql_util, con, cur, unit_cost_daily_summary_table, affected_days, store_range, 'day', 86400,
                                   verbose = verbose, resummarize_tail = 86400, execute_func = update_unit_cost_summary)


        # update the "top spenders within trailing 28 days" summary table
        def update_top_spenders(cur, table, interval, day_start, dt):
            temp_table = cfg['table_prefix']+game_id+'_store_by_user_temp'
            axes_table = cfg['table_prefix']+game_id+'_store_by_user_temp_axes'
            for t in (temp_table, axes_table): cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(t))
            try:
                # note: this can't actually be a TEMPORARY table because we need to refer to it more than once in the following queries
                sql_util.ensure_table(cur, temp_table, store_by_user_temp_schema(sql_util), temporary = False)

                # add up all spend by each user within the trailing time window
                if verbose: print "gathering spend by user,currency in trailing window..."
                cur.execute("INSERT INTO "+sql_util.sym(temp_table) + " " + \
                            "SELECT store.frame_platform AS frame_platform," + \
                            "       store.country_tier AS country_tier," + \
                            "       MAX(store.townhall_level) AS townhall_level," + \
                            "       MAX("+sql_util.encode_spend_bracket("store.prev_receipts")+") AS spend_bracket," + \
                            "       store.currency AS currency," + \
                            "       store.user_id AS user_id," + \
                            "       SUM(IF(store.price>0,1,0)) AS num_purchases," + \
                            "       SUM(store.price) AS total_price " + \
                            "FROM " + sql_util.sym(store_table) + " store " + \
                            "WHERE store.time >= %s AND store.time < %s AND store.price IS NOT NULL AND store.price > 0 " + \
                            "GROUP BY store.user_id, store.currency ORDER BY NULL",
                            [day_start - 28*86400, day_start])
                con.commit()

                # create another temp table with just the present permutations of all the summary dimensions
                # in theory, this should not be necessary, we should just be able to do a SELECT MAX(total_price) and then GROUP BY summary dimensions
                # however, MySQL's query optimizer blows up on this. So we manually create the handful of permutations here
                # and use it to drive the following query of the max spender for each one, since that is indexed and fast.
                cur.execute("CREATE TABLE "+sql_util.sym(axes_table) + " AS " + \
                            "SELECT frame_platform, country_tier, townhall_level, spend_bracket, currency " + \
                            "FROM " + sql_util.sym(temp_table) + " " + \
                            "GROUP BY frame_platform, country_tier, townhall_level, spend_bracket, currency ORDER BY NULL")
                con.commit()

                # only insert the max spender for each permutation of the summary dimensions
                if verbose: print "selecting top spenders..."
                cur.execute("INSERT INTO "+sql_util.sym(table) + " " + \
                            "SELECT %s AS "+sql_util.sym(interval)+"," + \
                            "       ax.frame_platform AS frame_platform," + \
                            "       ax.country_tier AS country_tier," + \
                            "       ax.townhall_level AS townhall_level," + \
                            "       ax.spend_bracket AS spend_bracket," + \
                            "       ax.currency AS currency," + \
                            "       by_user.user_id AS user_id," + \
                            "       by_user.num_purchases AS num_purchases," + \
                            "       by_user.total_price AS total_price " + \
                            "FROM "+sql_util.sym(axes_table)+ " ax, " +sql_util.sym(temp_table)+ " by_user " + \
                            "WHERE by_user.total_price = (SELECT MAX(b2.total_price) FROM "+sql_util.sym(temp_table)+" b2 WHERE " + \
                            "b2.frame_platform = ax.frame_platform AND b2.country_tier = ax.country_tier AND b2.townhall_level = ax.townhall_level AND b2.spend_bracket = ax.spend_bracket AND b2.currency = ax.currency) AND " + \
                            "by_user.frame_platform = ax.frame_platform AND by_user.country_tier = ax.country_tier AND by_user.townhall_level = ax.townhall_level AND by_user.spend_bracket = ax.spend_bracket AND by_user.currency = ax.currency",
                            [day_start,])
            finally:
                for t in (temp_table, axes_table): cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(t))

        SpinETL.update_summary(sql_util, con, cur, store_top_spenders_28d_table,
                               # every change to the store table affects top_spenders_28d up to 28 days in the future
                               set(sum([range(x, min(x+(28+1)*86400, 86400*(end_time//86400 + 1)), 86400) for x in affected_days],[])),
                               # input data only starts mattering 28 days after the event
                               [min(store_range[0]+28*86400,end_time), min(store_range[1]+28*86400,end_time)] if store_range else None,
                               'day', 86400, verbose=verbose, dry_run=dry_run, execute_func = update_top_spenders, resummarize_tail = 86400)


        if (not dry_run) and do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            for TABLE in store_table, unit_cost_table:
                if verbose: print 'pruning', TABLE
                cur.execute("DELETE FROM "+sql_util.sym(TABLE)+" WHERE time < %s", [old_limit])
                if do_optimize:
                    if verbose: print 'optimizing', TABLE
                    cur.execute("OPTIMIZE TABLE "+sql_util.sym(TABLE))
                con.commit()
