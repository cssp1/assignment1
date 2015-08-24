#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# create a snapshot of the regional maps from MongoDB to a MySQL database for analytics

import sys,time, getopt
import SpinConfig
import SpinJSON
import SpinNoSQL
# SingletonProcess not needed
import MySQLdb
from warnings import filterwarnings

gamedata = None
time_now = int(time.time())

map_summary_fields = {
    'time': 'INT NOT NULL',
    'region_id':'VARCHAR(16) NOT NULL',
    'base_type': 'VARCHAR(8) NOT NULL',
    'base_template': 'VARCHAR(32)',
    'townhall_level': 'INT',
    'count': 'INT',
    }

def field_column(key, val):
    return "`%s` %s" % (key, val)

def do_insert(cur, table_name, keyvals):
    cur.execute("INSERT INTO " + table_name + \
                "("+', '.join(['`'+x[0]+'`' for x in keyvals])+")"+ \
                " VALUES ("+', '.join(['%s'] * len(keyvals)) +")",
                [x[1] for x in keyvals])

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', [])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False

    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))

    if not verbose: filterwarnings('ignore', category = MySQLdb.Warning)

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    map_summary_table = cfg['table_prefix']+game_id+'_map_summary'

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cur = con.cursor()
    for table, fields in [(map_summary_table, map_summary_fields)]:
        cur.execute("CREATE TABLE IF NOT EXISTS %s (" % table + \
                    ", ".join([field_column(key, fields[key]) for key in fields]) + \
                    ") CHARACTER SET utf8")
    con.commit()

    for name, data in gamedata['regions'].iteritems():
        if data.get('developer_only', False): continue
        if not data.get('enable_map', True): continue

        # count hives and quarries by template
        for KIND in ('hive', 'quarry'):
            count_by_template = nosql_client.region_table(name, 'map').aggregate([{'$match':{'base_type':KIND}},
                                                                                  {'$project':{'base_template':1}},
                                                                                  {'$group':{'_id': '$base_template',
                                                                                             'count': {'$sum':1}}}])
            cur = con.cursor()
            for row in count_by_template:
                keyvals = [('time',time_now),
                           ('region_id',name),
                           ('base_type',KIND),
                           ('base_template',row['_id']),
                           ('count',row['count'])]
                do_insert(cur, map_summary_table, keyvals)

        # count player bases by townhall level
        count_by_townhall = nosql_client.region_table(name, 'map').aggregate([{'$match':{'base_type':'home'}},
                                                                              {'$project':{gamedata['townhall']+'_level':1}},
                                                                              {'$group':{'_id': '$'+gamedata['townhall']+'_level',
                                                                                         'count': {'$sum':1}}}])
        for row in count_by_townhall:
            keyvals = [('time',time_now),
                       ('region_id',name),
                       ('base_type','home'),
                       ('townhall_level',row['_id']),
                       ('count',row['count'])]
            do_insert(cur, map_summary_table, keyvals)

        con.commit()

