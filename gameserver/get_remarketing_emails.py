#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# query SQL (both skynet and game upcache) for email addresses to use to set up remarketing lists

import sys, time, getopt, csv
import SpinConfig
import SpinSQLUtil, SpinMySQLdb
import SpinGeoIP

time_now = int(time.time())
geoip_client = SpinGeoIP.SpinGeoIP()

def upcache_table(sql_util, game_id):
    # note: assumes table_prefix equals '$GAMEID_upcache'
    return sql_util.sym(game_id + '_upcache') + '.' + sql_util.sym(game_id + ('_upcache_lite' if game_id == 'mf' else '_upcache'))

if __name__ == '__main__':

    # APPLIES TO BH.COM AND FB GAMES:
    # only look for players in these country tiers
    accept_country_tiers = (1,2,)

    # APPLIES TO FB GAMES ONLY:
    # require player to be active within this many days
    active_within_days = 120
    or_min_spend = 100.0 # also include players outside accept_country_tiers if their spend is above this

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['active-within='])
    for key, val in opts:
        if key == '--active-within': active_within_days = int(val)

    cfg = SpinConfig.get_mysql_config(SpinConfig.game()+'_upcache') # note: use "native" connection, not game_id
    sql_util = SpinSQLUtil.MySQLUtil()
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    cur = con.cursor(SpinMySQLdb.cursors.DictCursor)

    candidates_by_email = dict()

    if 1:
        # grab all BH users in Tier 1/2
        # (note: this table doesn't have country or country tier, so we have to geolocate the IP)
        print >> sys.stderr, 'querying for BH users in Tier 1/2...'
        cur.execute('SELECT user_id, LOWER(ui_email) AS email, ui_name AS name, last_login_ip AS ip ' + \
                    'FROM '+ sql_util.sym('skynet') + '.' + sql_util.sym('bh_users') + ' ' + \
                    'WHERE ui_email IS NOT NULL AND ' + \
                    ' email_verified IS TRUE')
        candidate_list = cur.fetchall()
        for c in candidate_list:
            # geolocate and drop by country tier
            country = geoip_client.get_country(c['ip'])
            country_tier = SpinConfig.country_tier_map.get(country, 4)
            if country_tier not in accept_country_tiers: continue
            candidates_by_email[c['email']] = c
        del candidate_list
        con.commit()
        print >> sys.stderr, 'got', len(candidates_by_email), 'candidates'

    for game_id in ('tr','dv',):
        print >> sys.stderr, 'querying for candidate', game_id, 'players...'
        cur.execute('SELECT user_id, LOWER(email) AS email, facebook_name AS name, country ' + \
                    'FROM ' + upcache_table(sql_util, game_id) + ' ' + \
                    'WHERE email IS NOT NULL AND ' + \
                    ' toc_level >= 3 AND gamebucks_balance >= 0 AND ' + \
                    ' (country_tier IN %s OR money_spent > %s) AND ' + \
                    ' last_login_time >= %s',
                    [map(str, accept_country_tiers), or_min_spend, time_now - active_within_days * 86400])
        candidate_list = cur.fetchall()
        for c in candidate_list:
            candidates_by_email[c['email']] = c
        con.commit()
        print >> sys.stderr, 'got', len(candidate_list), 'candidates'
        del candidate_list

    # output to CSV
    CSV_FIELDS = ['email', 'name']
    writer = csv.DictWriter(sys.stdout, CSV_FIELDS, dialect='excel')
    writer.writerow(dict((fn,fn) for fn in CSV_FIELDS))
    for _, candidate in sorted(candidates_by_email.items()):
        csv_obj = dict((k, candidate[k].encode('utf-8')) for k in CSV_FIELDS)
        writer.writerow(csv_obj)
