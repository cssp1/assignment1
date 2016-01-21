#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump current alliances and memberships to SQL for analytics use

import sys, getopt
import SpinConfig
import SpinNoSQL
import SpinSQLUtil
import SpinSingletonProcess
import MySQLdb

alliances_schema = {
    'fields': [('alliance_id', 'INT4 NOT NULL'),
               ('chat_tag', 'VARCHAR(3)'),
               ('ui_name', 'VARCHAR(64)'),
               ('num_members_cache', 'INT4'),
               ('leader_id', 'INT4'),
               ('founder_id', 'INT4'),
               ('creation_time', 'INT8'),
               ('ui_description', 'VARCHAR(256)'),
               ('logo', 'VARCHAR(32)'),
               ('continent', 'VARCHAR(32)'),
               ('join_type', 'VARCHAR(16)'),
               ('chat_motd', 'VARCHAR(256)')],
    'indices': {'by_alliance_id': {'keys': [('alliance_id','ASC')]}}
    }
alliance_members_schema = {
    'fields': [('user_id', 'INT4 NOT NULL'),
               ('alliance_id', 'INT4 NOT NULL'),
               ('role', 'INT4'),
               ('join_time', 'INT8')],
    'indices': {'by_alliance_id': {'keys': [('alliance_id','ASC')]},
                'by_user_id': {'keys': [('user_id','ASC')]}}
    }

# commit block of inserts to a table
def flush_keyvals(sql_util, cur, tbl, keyvals):
    if not dry_run:
        try:
            sql_util.do_insert_batch(cur, tbl, keyvals)
        except MySQLdb.Warning as e:
            raise Exception('while inserting into %s:\n' % tbl+'\n'.join(map(repr, keyvals))+'\n'+repr(e))
        con.commit()
    del keyvals[:]

if __name__ == '__main__':
    game_id = SpinConfig.game()
    commit_interval = 1000
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if verbose or True:
        from warnings import filterwarnings
        filterwarnings('error', category = MySQLdb.Warning)
    else:
        sql_util.disable_warnings()

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('alliance_state_to_sql-%s' % game_id):

        alliances_table = cfg['table_prefix']+game_id+'_alliances'
        alliance_members_table = cfg['table_prefix']+game_id+'_alliance_members'

        cur = con.cursor(MySQLdb.cursors.DictCursor)
        if not dry_run:
            filterwarnings('ignore', category = MySQLdb.Warning)
            for tbl, schema in ((alliances_table, alliances_schema),
                                (alliance_members_table, alliance_members_schema)):
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl+'_temp'))
                sql_util.ensure_table(cur, tbl, schema)
                sql_util.ensure_table(cur, tbl+'_temp', schema)

            filterwarnings('error', category = MySQLdb.Warning)
            con.commit()

            for sql_table, nosql_table, schema, keyname_map in \
                ((alliances_table, 'alliances', alliances_schema, {'alliance_id': '_id'}),
                 (alliance_members_table, 'alliance_members', alliance_members_schema, {'user_id': '_id'})):
                total = 0
                batch = 0
                keyvals = []

                for row in nosql_client.alliance_table(nosql_table).find():
                    keyvals.append([(keyname, row.get(keyname_map.get(keyname,keyname),None))
                                    for keyname, keytype in schema['fields']])
                    total += 1
                    if commit_interval > 0 and len(keyvals) >= commit_interval:
                        flush_keyvals(sql_util, cur, sql_table+'_temp', keyvals)
                        if verbose: print total, nosql_table, 'inserted'

                if keyvals: flush_keyvals(sql_util, cur, sql_table+'_temp', keyvals)
                con.commit()
                if verbose: print 'total', total, nosql_table, 'inserted'

        if not dry_run:
            filterwarnings('ignore', category = MySQLdb.Warning)
            for tbl in (alliances_table, alliance_members_table):
                cur.execute("RENAME TABLE "+\
                            sql_util.sym(tbl)+" TO "+sql_util.sym(tbl+'_old')+","+\
                            sql_util.sym(tbl+'_temp')+" TO "+sql_util.sym(tbl))
                cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(tbl+'_old'))

            con.commit()
