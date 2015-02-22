#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump "log_credits" table from MongoDB to a MySQL database for analytics

import sys, time, getopt, re, functools
import SpinConfig
import SpinETL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

time_now = int(time.time())
gamebucks_re = re.compile('BUY_GAMEBUCKS_([0-9]+)')
spellname_re = re.compile('spellname=(.+)&')

# code to backfill old events with summary data
#CREATE TABLE zzz SELECT * FROM mf2_credits;
#ALTER TABLE zzz ADD INDEX user_tim (user_id, time);
#UPDATE zzz credits, mf2_upcache upcache SET
#credits.frame_platform=IFNULL(upcache.frame_platform,'fb'),
#credits.country_tier=upcache.country_tier,
#credits.townhall_level=IFNULL((SELECT MAX(th.townhall_level) FROM mf2_townhall_at_time th WHERE th.user_id = credits.user_id AND th.time < credits.time),1),
#credits.prev_receipts=(SELECT SUM(0.01*c2.usd_receipts_cents) FROM mf2_credits c2 WHERE c2.user_id = credits.user_id AND c2.time < credits.time)
#WHERE upcache.user_id = credits.user_id AND credits.time < 1389398506;
#RENAME TABLE zzz TO mf2_credits;

def credits_schema(sql_util):
    return {'fields': [('_id', 'CHAR(24) NOT NULL PRIMARY KEY'),
                       #    'fb_payment_id':'CHAR(16)',
                       ('time', 'INT NOT NULL'),
                       ('user_id', 'INT NOT NULL')] + \
            sql_util.summary_in_dimensions() + \
            [('is_gift_order', 'TINYINT(1) NOT NULL'),
             ('currency', 'VARCHAR(16) NOT NULL'),
             ('currency_amount', 'FLOAT NOT NULL'),
             ('tax_amount', 'FLOAT'),
             ('tax_country', 'CHAR(2)'),
             ('payout_foreign_exchange_rate', 'FLOAT'),
             ('usd_receipts_cents', 'INT NOT NULL'),
             ('description', 'VARCHAR(255) NOT NULL'),
             ('gamebucks', 'INT'), # derived from description, may be NULL
             ('quantity', 'INT')],
            'indices': {'by_time': {'keys': [('time','ASC')]}}
            }
def credits_summary_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
            sql_util.summary_out_dimensions() + \
            [('currency', 'VARCHAR(16) NOT NULL'),
             # OUTPUTS
             ('currency_amount', 'FLOAT8 NOT NULL'),
             ('usd_receipts_cents', 'INT8 NOT NULL'),
             ('gamebucks', 'INT8 NOT NULL')],
            'indices': {'master': {'unique':True, 'keys': [(interval,'ASC')] + [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions()] + [('currency','ASC')]}}
            }

# track user_ids of players with top spend in each summary segment
def credits_top_spenders_schema(sql_util, interval):
    return {'fields': [(interval, 'INT8 NOT NULL')] + \
            sql_util.summary_out_dimensions() + \
            [
             # OUTPUTS
             ('user_id', 'INT4 NOT NULL'),
             ('num_purchases', 'INT4 NOT NULL'),
             ('total_usd_receipts_cents', 'INT8 NOT NULL'),
             ],
            'indices': {'by_interval': {'unique':False, 'keys': [(interval,'ASC')]}}
            }

# temp table used for building top_spenders - this is the total spend of ALL users, by user, within a time window
def credits_by_user_temp_schema(sql_util):
    return {'fields': sql_util.summary_out_dimensions() + \
            [
             ('user_id', 'INT4 NOT NULL'),
             ('num_purchases', 'INT4 NOT NULL'),
             ('total_usd_receipts_cents', 'INT8 NOT NULL'),
             ],
            'indices': {'by_interval': {'unique':False, 'keys': [(dim,'ASC') for dim, kind in sql_util.summary_out_dimensions() + [('total_usd_receipts_cents','DESC')]]}}
            }


if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', [])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    credits_table = cfg['table_prefix']+game_id+'_credits'
    credits_hourly_summary_table = cfg['table_prefix']+game_id+'_credits_hourly_summary'
    credits_daily_summary_table = cfg['table_prefix']+game_id+'_credits_daily_summary'
    credits_top_spenders_28d_table = cfg['table_prefix']+game_id+'_credits_top_spenders_28d'
    credits_top_spenders_alltime_table = cfg['table_prefix']+game_id+'_credits_top_spenders_alltime'

    with SpinSingletonProcess.SingletonProcess('credits_to_mysql-%s' % game_id):

        con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        cur = con.cursor(MySQLdb.cursors.DictCursor)
        for table, schema in ((credits_table, credits_schema(sql_util)),
                              (credits_hourly_summary_table, credits_summary_schema(sql_util,'hour')),
                              (credits_daily_summary_table, credits_summary_schema(sql_util,'day')),
                              (credits_top_spenders_28d_table, credits_top_spenders_schema(sql_util,'day')),
                              (credits_top_spenders_alltime_table, credits_top_spenders_schema(sql_util,'day')),
                              ):
            sql_util.ensure_table(cur, table, schema)
        con.commit()

        # find most recent already-converted action
        start_time = -1
        refund_start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(credits_table)+" ORDER BY time DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            start_time = row['time']
        cur.execute("SELECT time FROM "+sql_util.sym(credits_table)+" WHERE currency_amount < 0 ORDER BY time DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            refund_start_time = row['time']
        con.commit()

        if verbose:  print 'start_time', start_time, 'refund_start_time', refund_start_time, 'end_time', end_time

        batch = 0
        total = 0
        affected_hours = set()
        affected_days = set()

        qs = {'$or':[{'event_name':'1000_billed',
                      'time': {'$gt':start_time, '$lt': end_time}},
                     {'event_name':'1310_order_refunded',
                      'time': {'$gt':refund_start_time, '$lt': end_time}}]}

    #    for row in SpinETL.iterate_from_s3(game_id, 'spinpunch-logs', 'credits', 1388096233, 1389398506, verbose = verbose):
        for row in SpinETL.iterate_from_mongodb(game_id, 'log_credits', min(start_time, refund_start_time), end_time, query = qs):
            keyvals = [('_id',row['_id']),
                       ('time',row['time']),
                       ('user_id',row['user_id'])]

            if 'summary' in row:
                if row['summary'].get('developer',False): continue # skip events by developers
                keyvals += sql_util.parse_brief_summary(row['summary'])

            if row['event_name'] in ('1000_billed', '1310_order_refunded'):
                sign = -1 if row['event_name'] == '1310_order_refunded' else 1
                keyvals.append(('is_gift_order', 1 if row.get('gift_order',False) else 0))
                keyvals.append(('currency',row.get('currency','USD')))

                if 'currency' not in row: # very old FB Payments data
                    row['currency'] = 'USD'
                    row['currency_amount'] = row['Billing Amount']/0.7

                if ('currency_amount' not in row) and (row['currency'] == 'kgcredits'): # bad legacy data
                    keyvals.append(('currency_amount', sign * int(row['Billing Amount']/0.07 + 0.5)))
                else:
                    keyvals.append(('currency_amount', sign * row['currency_amount']))

                keyvals.append(('usd_receipts_cents',sign * int(100*row['Billing Amount']+0.5)))

                if 'Billing Description' in row:
                    descr = row['Billing Description']
                    keyvals.append(('description',descr))

                    if descr.startswith("BUY_GAMEBUCKS_"):
                        keyvals.append(('gamebucks', sign * int(descr.split('_')[2])))
                    elif descr.startswith("FB_GAMEBUCKS_PAYMENT,") or descr.startswith("FB_TRIALPAY_GAMEBUCKS,"):
                        keyvals.append(('gamebucks', sign * int(descr.split(',')[1])))
                    else:
                        pass # just go by the description for other spells

                elif 'product' in row:
                    found = spellname_re.search(row['product'])
                    if found:
                        keyvals.append(('description', found.groups()[0]))
                    found = gamebucks_re.search(row['product'])
                    if found:
                        keyvals.append(('gamebucks', sign * int(found.groups()[0])))

                for FIELD in ('quantity', 'payout_foreign_exchange_rate', 'tax_amount', 'tax_country'):
                    if FIELD in row:
                        keyvals.append((FIELD,row[FIELD]))

            else:
                if verbose: print 'unrecognized event', row
                continue

            sql_util.do_insert(cur, credits_table, keyvals)

            batch += 1
            total += 1
            affected_hours.add(3600*(row['time']//3600))
            affected_days.add(86400*(row['time']//86400))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_hours), 'hour(s)', len(affected_days), 'day(s)'

        # update summary

        cur.execute("SELECT MIN(time) AS min_time, MAX(time) AS max_time FROM "+sql_util.sym(credits_table))
        rows = cur.fetchall()
        if rows and rows[0] and rows[0]['min_time'] and rows[0]['max_time']:
            credits_range = (rows[0]['min_time'], rows[0]['max_time'])
        else:
            credits_range = None

        for table, affected, interval, dt in ((credits_hourly_summary_table, affected_hours, 'hour', 3600),
                                              (credits_daily_summary_table, affected_days, 'day', 86400)):
            SpinETL.update_summary(sql_util, con, cur, table, affected, credits_range, interval, dt, verbose=verbose, dry_run=dry_run,
                                   resummarize_tail = dt,
                                   execute_func = lambda cur, table, interval, day_start, dt:
                        cur.execute("INSERT INTO "+sql_util.sym(table) + \
                                    "SELECT %s*FLOOR(credits.time/%s) AS "+sql_util.sym(interval)+"," + \
                                    "       credits.frame_platform AS frame_platform," + \
                                    "       credits.country_tier AS country_tier," + \
                                    "       credits.townhall_level AS townhall_level," + \
                                    "       "+sql_util.encode_spend_bracket("credits.prev_receipts")+" AS spend_bracket," + \
                                    "       credits.currency AS currency," + \
                                    "       SUM(credits.currency_amount) AS currency_amount," + \
                                    "       SUM(usd_receipts_cents) AS usd_receipts_cents," + \
                                    "       SUM(gamebucks) AS gamebucks " + \
                                    "FROM " + sql_util.sym(credits_table) + " credits " + \
                                    "WHERE credits.time >= %s AND credits.time < %s+%s " + \
                                    "GROUP BY "+sql_util.sym(interval)+", credits.frame_platform, credits.country_tier, credits.townhall_level, "+sql_util.encode_spend_bracket("credits.prev_receipts")+", credits.currency ORDER BY NULL", [dt,dt,day_start,day_start,dt])
                           )

        # update the "top spenders within trailing 28 days" summary table
        def update_top_spenders(day_window, cur, table, interval, day_start, dt):
            temp_table = cfg['table_prefix']+game_id+'_credits_by_user_temp'
            cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(temp_table))
            try:
                # note: this can't actually be a TEMPORARY table because we need to refer to it more than once in the following queries
                sql_util.ensure_table(cur, temp_table, credits_by_user_temp_schema(sql_util), temporary = False)

                # add up all spend by each user within the trailing time window
                cur.execute("INSERT INTO "+sql_util.sym(temp_table) + \
                            "SELECT credits.frame_platform AS frame_platform," + \
                            "       credits.country_tier AS country_tier," + \
                            "       MAX(credits.townhall_level) AS townhall_level," + \
                            "       MAX("+sql_util.encode_spend_bracket("credits.prev_receipts")+") AS spend_bracket," + \
                            "       credits.user_id AS user_id," + \
                            "       SUM(IF(credits.usd_receipts_cents>0,1,0)) AS num_purchases," + \
                            "       SUM(credits.usd_receipts_cents) AS total_usd_receipts_cents " + \
                            "FROM " + sql_util.sym(credits_table) + " credits " + \
                            "WHERE credits.time >= %s AND credits.time < %s " + \
                            "GROUP BY credits.user_id",
                            [(day_start - day_window*86400) if day_window > 0 else 0, day_start])

                # only insert the max spender for each permutation of the summary dimensions
                cur.execute("INSERT INTO "+sql_util.sym(table) + \
                            "SELECT %s AS "+sql_util.sym(interval)+"," + \
                            "       by_user.frame_platform AS frame_platform," + \
                            "       by_user.country_tier AS country_tier," + \
                            "       by_user.townhall_level AS townhall_level," + \
                            "       by_user.spend_bracket AS spend_bracket," + \
                            "       by_user.user_id AS user_id," + \
                            "       by_user.num_purchases AS num_purchases," + \
                            "       by_user.total_usd_receipts_cents AS total_usd_receipts_cents " + \
                            "FROM "+sql_util.sym(temp_table)+ " by_user " + \
                            "WHERE by_user.total_usd_receipts_cents = (SELECT MAX(b2.total_usd_receipts_cents) FROM "+sql_util.sym(temp_table)+" b2 WHERE b2.frame_platform = by_user.frame_platform AND b2.country_tier = by_user.country_tier AND b2.townhall_level = by_user.townhall_level AND b2.spend_bracket = by_user.spend_bracket)",
                            [day_start,])
            finally:
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(temp_table))

        for table, day_window in ((credits_top_spenders_28d_table, 28),
                                  (credits_top_spenders_alltime_table, -1),):
            if day_window > 0:
                # every change to the credits table affects top_spenders_28d up to 28 days in the future
                affect_set = set(sum([range(x, min(x+(day_window+1)*86400, 86400*(end_time//86400 + 1)), 86400) for x in affected_days],[]))
                # input data only starts mattering 28 days after the event
                input_set = [min(credits_range[0]+28*86400,end_time), min(credits_range[1]+28*86400,end_time)] if credits_range else None
            else:
                # every change to the credits table affects ALL following days
                affect_set = set(sum([range(x, 86400*(end_time//86400 + 1), 86400) for x in affected_days],[]))
                input_set = credits_range

            SpinETL.update_summary(sql_util, con, cur, table, affect_set, input_set,
                                   'day', 86400, verbose=verbose, dry_run=dry_run,
                                   execute_func = functools.partial(update_top_spenders, day_window),
                                   resummarize_tail = 86400)

