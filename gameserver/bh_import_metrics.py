#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# import metrics from BHLogin's database (via HTTP API) into the skynet SQL tables

import sys, time, getopt
import SpinConfig
import SpinSQLUtil
import SpinJSON
import SpinSingletonProcess
import SpinMySQLdb
import requests
import urllib

time_now = int(time.time())

def bh_metrics_schema(sql_util):
    return {'fields': [('time', 'INT8 NOT NULL'),
                       ('event_name', 'VARCHAR(255) NOT NULL'),
                       ('user_id', 'VARCHAR(255)'),
                       ('session_id', 'VARCHAR(255)'),
                       ('label', 'VARCHAR(255)'),
                       ('ip', 'VARCHAR(64)'),
                       ('uri', 'VARCHAR(1024)'),
                       ('referer', 'VARCHAR(1024)'),
                       ('user_agent', 'VARCHAR(255)'),

                       ('campaign_name', 'VARCHAR(255)'),
                       ('campaign_source', 'VARCHAR(255)'),
                       ('campaign_medium', 'VARCHAR(255)'),
                       ('campaign_code', 'VARCHAR(255)'),
                       ('service_url', 'VARCHAR(1024)'),
                       ('service', 'VARCHAR(64)'),
                       ],
            'indices': {'by_time': {'unique':False, 'keys': [('time','ASC')]}}
            }

if __name__ == '__main__':
    verbose = True
    dry_run = False
    commit_interval = 1000

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['dry-run'])

    for key, val in opts:
          if key == '-q': verbose = False
          elif key == '--dry-run': dry_run = True

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    cfg = SpinConfig.get_mysql_config('skynet')
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    with SpinSingletonProcess.SingletonProcess('bh_import_metrics'):

        bh_metrics_table = cfg['table_prefix']+'bh_metrics'

        cur = con.cursor(SpinMySQLdb.cursors.DictCursor)
        sql_util.ensure_table(cur, bh_metrics_table, bh_metrics_schema(sql_util))
        con.commit()

        # find most recent already-converted action
        start_time = -1
        end_time = time_now - 10  # skip entries too close to "now" to ensure all events for a given second have all arrived

        cur.execute("SELECT MAX(time) AS maxtime FROM "+sql_util.sym(bh_metrics_table))
        rows = cur.fetchall()
        if rows and rows[0]['maxtime'] is not None:
            start_time = max(start_time, rows[0]['maxtime'] + 1)
        con.commit()

        if verbose:  print 'start_time', start_time, 'end_time', end_time

        response = requests.get('https://www.battlehouse.com/bh_login/metrics_dump?service=fs&' + \
                                urllib.urlencode({'start_time': start_time, 'end_time': end_time}),
                                headers = {'x-bhlogin-api-secret': SpinConfig.config['battlehouse_api_secret']})
        response.raise_for_status()
        rows = SpinJSON.loads(response.content)['result']
        affected_days = set()

        batch = 0
        total = 0

        FIELDS = set(x[0] for x in bh_metrics_schema(sql_util)['fields'])

        for row in rows:
            keyvals = [('time',row['time']),
                       ('event_name',row['event_name'])]

            for k, v in row['data'].iteritems():
                if k in FIELDS:
                    keyvals.append((k, v))

            sql_util.do_insert(cur, bh_metrics_table, keyvals)

            batch += 1
            total += 1
            affected_days.add(86400*(row['time']//86400))

            if commit_interval > 0 and batch >= commit_interval:
                batch = 0
                con.commit()
                if verbose: print total, 'inserted'

        con.commit()
        if verbose: print 'total', total, 'inserted', 'affecting', len(affected_days), 'day(s)'
