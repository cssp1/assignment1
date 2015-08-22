#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump Skynet adstats from MongoDB to a MySQL database for analytics
# this runs once for ALL game titles, from the sandbox that is managing skynet

import sys, time, getopt, traceback
import SpinConfig
import SkynetLib
import pymongo # 3.0+ OK
import MySQLdb
import SpinSQLUtil
import requests
import SpinJSON
import SpinFacebook

time_now = int(time.time())

adstats_schema = {
    'fields': [('_id', 'VARCHAR(255) NOT NULL PRIMARY KEY'),
               ('time', 'INT8 NOT NULL'),
               ('campaign_id', 'VARCHAR(255)'),
               ('adgroup_id', 'VARCHAR(255) NOT NULL'),
               ('stgt', 'VARCHAR(255) NOT NULL'),
               ('bid', 'INT4 NOT NULL'),
               ('spent', 'INT4 NOT NULL'),
               ('clicks', 'INT4 NOT NULL'),
               ('impressions', 'INT4 NOT NULL'),
               ] + SkynetLib.get_tgt_fields_for_sql(),
    'indices': {'by_time': {'unique':False, 'keys': [('time','ASC')]}}
    }

name_cache = {}
requests_session = None

def get_adgroup_name(id):
    global requests_session

    if id in name_cache: return name_cache[id]
    if requests_session is None: requests_session = requests.Session()

    data = SpinJSON.loads(requests_session.request('GET', SpinFacebook.versioned_graph_endpoint('adgroup', id),
                                                   {'access_token':SpinConfig.config['facebook_ads_api_access_token'],'fields':'name'}).content)
    print id, '->', data # XXX
    if data and 'name' in data:
        ret = data['name']
    else:
        ret = None
    name_cache[id] = ret
    return ret

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False
    fix_missing_data = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['dry-run','fix-missing-data'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--fix-missing-data': fix_missing_data = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet' if fix_missing_data else 'skynet_readonly')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    adstats_table = cfg['table_prefix']+'adstats_hourly'

    nosql_config = SpinConfig.get_mongodb_config('skynet')
    nosql_client = pymongo.MongoClient(*nosql_config['connect_args'], **nosql_config['connect_kwargs'])
    nosql_db = nosql_client[nosql_config['dbname']]
    nosql_tbl = nosql_db['fb_adstats_hourly']

    cur = con.cursor()
    if not dry_run:
        sql_util.ensure_table(cur, adstats_table, adstats_schema)
    con.commit()

    # find most recent entry
    start_time = -1
    end_time = time_now - 4*3600 # skip entries too close to "now" to ensure that all entries are present
    cur = con.cursor(MySQLdb.cursors.DictCursor)
    if dry_run:
        row = None
    else:
        cur.execute("SELECT time FROM "+sql_util.sym(adstats_table)+" ORDER BY time DESC LIMIT 1")
        row = cur.fetchone()
    if row:
        start_time = row['time']
    qs = {'start_time': {'$gt': start_time, '$lt': end_time}}

    # for fixing bad data
    #qs = {'$or': [{'dtgt': {'$exists':False}},
    #              {'dtgt.a': {'$exists':False}},
    #              {'adgroup_name': {'$exists':False}}]}

    batch = 0
    total = 0
    fail_time_range = [-1,-1]
    n_failed = 0
    n_name_fixed = 0
    n_dtgt_fixed = 0

    query = nosql_tbl.find(qs).sort([('start_time',1)])
    query_size = query.count()
    cur = con.cursor()
    for row in query:
        try:
            keyvals = [('_id', row['_id']),
                       ('time', row['start_time']),
                       ('adgroup_id', str(row['adgroup_id'])),
                       ('bid', row['bid']),
                       ('spent', row['spent']),
                       ('clicks', row['clicks']),
                       ('impressions', row['impressions'])]

            if 'campaign_id' in row:
                keyvals.append(('campaign_id', str(row['campaign_id'])))

            if fix_missing_data and ('dtgt' not in row) and ('adgroup_name' not in row):
                new_name = get_adgroup_name(str(row['adgroup_id']))
                if new_name:
                    if SkynetLib.adgroup_name_is_bad(new_name):
                        nosql_tbl.delete_one({'_id':row['_id']})
                        continue

                    row['adgroup_name'] = new_name
                    stgt, tgt = SkynetLib.decode_adgroup_name(SkynetLib.standin_spin_params, row['adgroup_name'])
                    if stgt:
                        dtgt = SkynetLib.stgt_to_dtgt(stgt)
                        assert dtgt
                        if 'a' not in dtgt: dtgt['a'] = 'tr' # fill in missing game on legacy ads
                        row['dtgt'] = dtgt
                        nosql_tbl.update_one({'_id':row['_id']}, {'$set':{'adgroup_name':row['adgroup_name'], 'dtgt': dtgt}})
                        n_name_fixed += 1
                    else:
                        print 'bad name?', new_name

            if 'dtgt' in row:
                assert 'a' in row['dtgt'] # make sure the game is identified
                for k, v in row['dtgt'].iteritems():
                    full_name, full_val = SkynetLib.decode_one_param(SkynetLib.standin_spin_params, k+v)
                    short_val = SkynetLib.encode_one_param(SkynetLib.standin_spin_params, full_name, full_val)[1:]
                    keyvals.append(('tgt_%s' % full_name, short_val))
                stgt = '_'.join(sorted(filter(lambda x: x is not None, (k+v for k,v in row['dtgt'].iteritems()))))
                assert stgt
                keyvals.append(('stgt', stgt))

            elif 'adgroup_name' in row:
                if SkynetLib.adgroup_name_is_bad(row['adgroup_name']):
                    if fix_missing_data:
                        nosql_tbl.delete_one({'_id':row['_id']})
                    continue
                stgt, tgt = SkynetLib.decode_adgroup_name(SkynetLib.standin_spin_params, row['adgroup_name'])
                assert stgt and tgt
                keyvals.append(('stgt', stgt))
                if 'game' not in tgt:
                    tgt['game'] = 'tr' # fill in missing game on legacy ads
                    stgt += '_atr'

                for k, v in tgt.iteritems():
                    code = SkynetLib.encode_one_param(SkynetLib.standin_spin_params, k, v)[1:]
                    keyvals.append(('tgt_%s' % k, code))

                if fix_missing_data: # add the dtgt field
                    # note: if we added the game here, the dtgt wil disagree with the adgroup_name
                    dtgt = SkynetLib.stgt_to_dtgt(stgt)
                    assert 'a' in dtgt
                    nosql_tbl.update_one({'_id':row['_id']}, {'$set':{'dtgt': dtgt}})
                    n_dtgt_fixed += 1

            else:
                print 'FAIL', row
                fail_time_range[0] = min(fail_time_range[0], row['start_time']) if fail_time_range[0] > 0 else row['start_time']
                fail_time_range[1] = max(fail_time_range[1], row['start_time']) if fail_time_range[1] > 0 else row['start_time']
                n_failed += 1
                continue

            #print keyvals

        except KeyboardInterrupt:
            break

        except:
            print traceback.format_exc()
            print 'problem row:', row
            continue

        if not dry_run:
            cur.execute("DELETE FROM "+sql_util.sym(adstats_table)+" WHERE _id = %s", row['_id'])
            sql_util.do_insert(cur, adstats_table, keyvals)
        total += 1
        batch += 1
        if commit_interval > 0 and batch >= commit_interval:
            con.commit()
            if verbose: print 'inserted', total, 'of', query_size, 'stats', '(%.2f%%)' % (100*float(total)/query_size)
            cur = con.cursor()
            batch = 0

    con.commit()
    if verbose: print 'inserted total', total, 'stats'
    if n_name_fixed > 0:
        print 'fixed', n_name_fixed, 'missing adgroup_names+dtgts'
    if n_dtgt_fixed > 0:
        print 'fixed', n_dtgt_fixed, 'missing dtgts'
    if n_failed > 0:
        print 'failed', n_failed, 'stats at time range', fail_time_range
