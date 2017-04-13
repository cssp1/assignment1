#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# create a snapshot of the regional maps from MongoDB to a MySQL database for analytics

import sys,time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
import SpinSingletonProcess
import SpinSQLUtil
import MySQLdb

gamedata = None
time_now = int(time.time())

def map_summary_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('region_id', 'VARCHAR(16) NOT NULL'),
               ('base_type', 'VARCHAR(8) NOT NULL'),
               ('base_template', 'VARCHAR(32)'),
               ('townhall_level', 'INT'),
               ('count', 'INT')],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }

def map_upgrades_schema(sql_util): return {
    'fields': [('time', 'INT8 NOT NULL'),
               ('region_id', 'VARCHAR(16) NOT NULL'),
#               ('base_type', 'VARCHAR(8) NOT NULL'),
#               ('base_template', 'VARCHAR(32)'),
               ('spec', 'VARCHAR(255) NOT NULL'),
               ('level', 'INT NOT NULL'),
               ('count', 'INT NOT NULL')],
    'indices': {'by_time': {'keys': [('time','ASC')]}}
    }

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    do_prune = False
    do_optimize = False
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True
        elif key == '--dry-run': dry_run = True
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    with SpinSingletonProcess.SingletonProcess('map_to_sql-%s' % game_id):

        cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
        con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
        nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

        map_summary_table = cfg['table_prefix']+game_id+'_map_summary'
        map_upgrades_table = cfg['table_prefix']+game_id+'_map_upgrades'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        if not dry_run:
            sql_util.ensure_table(cur, map_summary_table, map_summary_schema(sql_util))
            sql_util.ensure_table(cur, map_upgrades_table, map_upgrades_schema(sql_util))
            con.commit()

        for name, data in gamedata['regions'].iteritems():
            if data.get('developer_only', False): continue
            if not data.get('enable_map', True): continue

            # count hives and quarries by template
            for KIND in ('hive', 'quarry', 'raid'):
                count_by_template = nosql_client.region_table(name, 'map').aggregate([{'$match':{'base_type':KIND}},
                                                                                      {'$project':{'base_template':1}},
                                                                                      {'$group':{'_id': '$base_template',
                                                                                                 'count': {'$sum':1}}}])
                if not dry_run:
                    sql_util.do_insert_batch(cur, map_summary_table,
                                             [[('time',time_now),
                                               ('region_id',name),
                                               ('base_type',KIND),
                                               ('base_template',row['_id']),
                                               ('count',row['count'])] for row in count_by_template])

            # count player bases by townhall level
            count_by_townhall = nosql_client.region_table(name, 'map').aggregate([{'$match':{'base_type':'home'}},
                                                                                  {'$project':{gamedata['townhall']+'_level':1}},
                                                                                  {'$group':{'_id': '$'+gamedata['townhall']+'_level',
                                                                                             'count': {'$sum':1}}}])
            if not dry_run:
                sql_util.do_insert_batch(cur, map_summary_table,
                                         [[('time',time_now),
                                           ('region_id',name),
                                           ('base_type','home'),
                                           ('townhall_level',row['_id']),
                                           ('count',row['count'])] for row in count_by_townhall])


            # check what's been leveled up
            upgradable_specnames = [x['name'] for x in gamedata['buildings'].itervalues() if x.get('quarry_upgradable',False)]
            if upgradable_specnames:
                counts = nosql_client.region_table(name, 'fixed').aggregate([{'$match':{'spec':{'$in':upgradable_specnames}}},
                                                                             {'$project':{'spec':1, 'level':1}},
                                                                             {'$group':{'_id': {'spec': '$spec',
                                                                                                'level': '$level'},
                                                                                        'count': {'$sum':1}}}])
                if not dry_run:
                    sql_util.do_insert_batch(cur, map_upgrades_table,
                                             [[('time',time_now),
                                               ('region_id',name),
                                               ('spec',row['_id']['spec']),
                                               ('level',row['_id'].get('level',1)),
                                               ('count',row['count'])] for row in counts])

                # get enhancements too
                counts = nosql_client.region_table(name, 'fixed').aggregate([{'$match':{'spec':{'$in':upgradable_specnames},
                                                                                        'enhancements':{'$exists':True}}},
                                                                             {'$project':{'spec':1, 'enhancements':1}},
                                                                             {'$group':{'_id': {'spec': '$spec',
                                                                                                'enhancements': '$enhancements'},
                                                                                        'count': {'$sum':1}}}])
                if not dry_run:
                    # group by spec:enh_name, enh_level
                    regroup = {}
                    for row in counts:
                        for enh_name, enh_level, in row['_id']['enhancements'].iteritems():
                            key = (row['_id']['spec']+':'+enh_name,enh_level)
                            regroup[key] = regroup.get(key,0) + row['count']

                    sql_util.do_insert_batch(cur, map_upgrades_table,
                                             [[('time',time_now),
                                               ('region_id',name),
                                               ('spec',k[0]),
                                               ('level',k[1]),
                                               ('count',val)] for k, val in regroup.iteritems()])

            con.commit()

        if (not dry_run) and do_prune:
            # drop old data
            KEEP_DAYS = 360
            old_limit = time_now - KEEP_DAYS * 86400

            for table in (map_summary_table, map_upgrades_table):
                if verbose: print 'pruning', table
                cur.execute("DELETE FROM "+sql_util.sym(table)+" WHERE time < %s", [old_limit])
                con.commit()
                if do_optimize:
                    if verbose: print 'optimizing', table
                    cur.execute("OPTIMIZE TABLE "+sql_util.sym(table))
