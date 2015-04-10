#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# dump current alliances and memberships to SQL for analytics use

import sys, getopt, time
import SpinConfig
import SpinNoSQL
import SpinETL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def alliance_events_schema(sql_util):
    return { 'fields': [('time', 'INT8 NOT NULL'),
                        ('user_id', 'INT4 NOT NULL'),
                        ('alliance_id', 'INT4 NOT NULL')] + \
                        sql_util.summary_in_dimensions() + \
                       [('event_name', 'VARCHAR(128) NOT NULL'),
                        ('chat_tag', 'VARCHAR(3)'),
                        ('ui_name', 'VARCHAR(64)'),
                        ('num_members_cache', 'INT4'),
                        ('ui_description', 'VARCHAR(256)'),
                        ('logo', 'VARCHAR(32)'),
                        ('continent', 'VARCHAR(32)'),
                        ('join_type', 'VARCHAR(16)'),
                        ('chat_motd', 'VARCHAR(256)')],
             'indices': {'by_time': {'keys': [('time','ASC')]},
                         'by_alliance_id': {'keys': [('alliance_id','ASC'),('time','ASC')]}},
    }

def alliance_member_events_schema(sql_util):
    return { 'fields': [('time', 'INT8 NOT NULL'),
                        ('user_id', 'INT4 NOT NULL'),
                        ('alliance_id', 'INT4 NOT NULL')] + \
                        sql_util.summary_in_dimensions() + \
                       [('event_name', 'VARCHAR(128) NOT NULL'),
                        ('target_id', 'INT4'),
                        ('role', 'INT4')],
             'indices': {'by_time': {'keys': [('time','ASC')]},
                         'by_alliance_id': {'keys': [('alliance_id','ASC'),('time','ASC')]},
                         'by_user_id': {'keys': [('user_id','ASC'),('time','ASC')]},
                         'by_target_id': {'keys': [('target_id','ASC'),('time','ASC')]},
                         }
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
    do_prune = False
    do_optimize = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:c:q', ['prune','optimize','dry-run'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '-c': commit_interval = int(val)
        elif key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--prune': do_prune = True
        elif key == '--optimize': do_optimize = True


    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(game_id))

    cfg = SpinConfig.get_mysql_config(game_id+'_upcache')
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    alliance_events_table = cfg['table_prefix']+game_id+'_alliance_events'
    alliance_member_events_table = cfg['table_prefix']+game_id+'_alliance_member_events'

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    for tbl, schema in ((alliance_events_table, alliance_events_schema(sql_util)),
                        (alliance_member_events_table, alliance_member_events_schema(sql_util))):
        sql_util.ensure_table(cur, tbl, schema)
    con.commit()

    for sql_table, nosql_table, schema, keyname_map in \
        ((alliance_events_table, 'log_alliances', alliance_events_schema(sql_util), {}),
         (alliance_member_events_table, 'log_alliance_members', alliance_member_events_schema(sql_util), {})):

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 60  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT time FROM "+sql_util.sym(sql_table)+" ORDER BY time DESC LIMIT 1")
        rows = cur.fetchall()
        if rows:
            start_time = max(start_time, rows[0]['time'])
        con.commit()

        total = 0
        batch = 0
        keyvals = []

        for row in SpinETL.iterate_from_mongodb(game_id, nosql_table, start_time, end_time):
            # note: DO include events by developers

            # follow the keys in the schema, assuming that the summary dimensions start at position 3
            assert schema['fields'][3][0] == sql_util.summary_in_dimensions()[0][0]

            keyvals.append([(keyname, row.get(keyname_map.get(keyname,keyname),None))
                            for keyname, keytype in schema['fields'][0:3]])

            if 'sum' in row:
                keyvals += sql_util.parse_brief_summary(row['sum'])
            else:
                keyvals += [(keyname,None) for keyname, keytype in sql_util.summary_in_dimensions()]

            keyvals.append([(keyname, row.get(keyname_map.get(keyname,keyname),None))
                            for keyname, keytype in schema['fields'][3+len(sql_util.summary_in_dimensions()):]])
            total += 1
            if commit_interval > 0 and len(keyvals) >= commit_interval:
                flush_keyvals(sql_util, cur, sql_table+'_temp', keyvals)
                if verbose: print total, nosql_table, 'inserted'

        if keyvals: flush_keyvals(sql_util, cur, sql_table+'_temp', keyvals)
        con.commit()
        if verbose: print 'total', total, nosql_table, 'inserted'

        if do_prune:
            # drop old data
            KEEP_DAYS = 90
            old_limit = time_now - KEEP_DAYS * 86400

            if verbose: print 'pruning', sql_table
            cur = con.cursor()
            cur.execute("DELETE FROM "+sql_util.sym(sql_table)+" WHERE time < %s", old_limit)
            if do_optimize:
                if verbose: print 'optimizing', sql_table
                cur.execute("OPTIMIZE TABLE "+sql_util.sym(sql_table))
            con.commit()
