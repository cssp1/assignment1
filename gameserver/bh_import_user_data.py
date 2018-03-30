#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# import static user data from BHLogin's database (via HTTP API) into the skynet SQL tables

import sys, time, getopt
import SpinConfig
import SpinSQLUtil
import SpinJSON
import SpinSingletonProcess
import SpinMySQLdb
import requests

time_now = int(time.time())

def bh_users_schema(sql_util):
    return {'fields': [('user_id', 'VARCHAR(255) NOT NULL'),
                       ('ui_name', 'VARCHAR(255)'),
                       ('ui_email', 'VARCHAR(255)'),
                       ('real_name', 'VARCHAR(255)'),
                       ('name_source', 'VARCHAR(64)'),
                       ('email_source', 'VARCHAR(64)'),
                       ('email_verified', 'INT1'),
                       ('trust_level', 'INT4'),
                       ('creation_time', 'INT8'),
                       ('creation_provider', 'VARCHAR(64)'),
                       ('last_login_time', 'INT8'),
                       ('last_login_ip', 'VARCHAR(64)'),
                       ('creation_ip', 'VARCHAR(64)'),
                       ('facebook_id', 'VARCHAR(64)'), # might be null: facebook ID for the battlehouse.com login app
                       ('country', 'VARCHAR(2)'),
                       ('country_tier', 'CHAR(1)'),
                       ('locale', 'VARCHAR(16)'),
                       ('timezone', 'INT4'),
                       ],
            'indices': {'by_creation_time': {'unique':False, 'keys': [('creation_time','ASC')]}}
            }

if __name__ == '__main__':
    verbose = True
    dry_run = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['dry-run'])

    for key, val in opts:
          if key == '-q': verbose = False
          elif key == '--dry-run': dry_run = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet')
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('bh_import_user_data'):

        bh_users_table = cfg['table_prefix']+'bh_users'

        cur = con.cursor(SpinMySQLdb.cursors.DictCursor)

        response = requests.get('https://www.battlehouse.com/bh_login/user_db?service=fs',
                                headers = {'x-bhlogin-api-secret': SpinConfig.config['battlehouse_api_secret']})
        response.raise_for_status()
        rows = SpinJSON.loads(response.content)['result']

        # add derived fields
        for row in rows:
            if row.get('country'):
                row['country_tier'] = str(SpinConfig.country_tier_map.get(row['country'], 4))

        for table, schema in ((bh_users_table, bh_users_schema(sql_util)),
                              ):
            # get rid of temp tables
            cur.execute("DROP TABLE IF EXISTS "+sql_util.sym(table+'_temp'))
            sql_util.ensure_table(cur, table+'_temp', schema)
            con.commit()

        field_names = [name for name, type in bh_users_schema(sql_util)['fields']]
        cur.executemany("INSERT INTO "+sql_util.sym(bh_users_table+'_temp')+" " + \
                        "("+(','.join(field_names))+") " + \
                        "VALUES("+(','.join(["%s"] * len(field_names)))+")",
                        (tuple(row.get(name,None) for name in field_names) for row in rows))

        for table in (bh_users_table,):
            # t -> t_old, t_temp -> t
            cur.execute("RENAME TABLE "+\
                        sql_util.sym(table)+" TO "+sql_util.sym(table+'_old')+","+\
                        sql_util.sym(table+'_temp')+" TO "+sql_util.sym(table))
            con.commit()

            # kill t_old
            cur.execute("DROP TABLE "+sql_util.sym(table+'_old'))
            con.commit()
