#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# import data from Google Analytics API into the SQL database for futher processing

# API docs: https://developers.google.com/analytics/devguides/reporting/core/v4/basics#dimensions

import sys, os, time, getopt, calendar
import SpinConfig
import SpinETL
import SpinSQLUtil
import MySQLdb

time_now = int(time.time())

def bh_summary_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('pageviews', 'INT8 NOT NULL'),
                       ('sessions', 'INT8 NOT NULL'),
                       ('new_users', 'INT8 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }
def bh_detail_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('referer', 'VARCHAR(1024)'),
                       ('path', 'VARCHAR(1024)'),
                       ('count', 'INT4'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }

# Google Analytics API boilerplate
from apiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

import httplib2
from oauth2client import client
from oauth2client import file
from oauth2client import tools

SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
DISCOVERY_URI = ('https://analyticsreporting.googleapis.com/$discovery/rest')
KEY_FILE_LOCATION = os.path.join(os.getenv('HOME'), '.ssh', 'battlehouse-google-analytics1-key.p12')
SERVICE_ACCOUNT_EMAIL = open(os.path.join(os.getenv('HOME'), '.ssh', 'battlehouse-google-analytics1-service-account-email.txt')).readline().strip()
VIEW_ID = '126674942' # bh.com ALL


def initialize_analyticsreporting():
    credentials = ServiceAccountCredentials.from_p12_keyfile(
      SERVICE_ACCOUNT_EMAIL, KEY_FILE_LOCATION, 'notasecret', scopes=SCOPES)

    http = credentials.authorize(httplib2.Http())

    # Build the service object.
    return build('analytics', 'v4', http=http, discoveryServiceUrl=DISCOVERY_URI)


def get_report(analytics, day_start, dt, list_of_metrics, list_of_dimensions = None):
    # Use the Analytics Service Object to query the Analytics Reporting API V4.
    # can only retrieve one full UTC day of data at a time
    assert day_start % 86400 == 0
    assert dt == 86400

    day_str = time.strftime('%Y-%m-%d', time.gmtime(day_start))
    request = {
        'viewId': VIEW_ID,
        'dateRanges': [{'startDate': day_str, 'endDate': day_str}], # note: could retrieve more than 1 day if we wanted
        'metrics': [{'expression': met} for met in list_of_metrics]
        }
    if list_of_dimensions:
        request['dimensions'] = [{'name': dim} for dim in list_of_dimensions]

    report = analytics.reports().batchGet(body={'reportRequests': [request]}).execute()['reports'][0]
    rows = report['data']['rows']
    if list_of_dimensions:
        ret = []
        for row in rows:
            d = dict((met, int(row['metrics'][0]['values'][i])) for i, met in enumerate(list_of_metrics))
            d.update(dict((dim, row['dimensions'][j]) for j, dim in enumerate(list_of_dimensions)))
            ret.append(d)
        return ret
    else:
        return [dict((met, int(row['metrics'][0]['values'][i])) for i, met in enumerate(list_of_metrics)) for row in rows]

def get_summary_report(analytics, day_start, dt):
    report = get_report(analytics, day_start, dt, ['ga:pageviews','ga:sessions','ga:newUsers'])
    return report
def get_detail_report(analytics, day_start, dt):
    report = get_report(analytics, day_start, dt, ['ga:pageviews'], ['ga:fullReferrer', 'ga:pagePath'])
    return report

def print_response(response):
    for report in response.get('reports', []):
        columnHeader = report.get('columnHeader', {})
        dimensionHeaders = columnHeader.get('dimensions', [])
        metricHeaders = columnHeader.get('metricHeader', {}).get('metricHeaderEntries', [])
        rows = report.get('data', {}).get('rows', [])

    for row in rows:
        dimensions = row.get('dimensions', [])
        dateRangeValues = row.get('metrics', [])

        for header, dimension in zip(dimensionHeaders, dimensions):
            print header + ': ' + dimension

        for i, values in enumerate(dateRangeValues):
            print 'Date range (' + str(i) + ')'
            for metricHeader, value in zip(metricHeaders, values.get('values')):
                print metricHeader.get('name') + ': ' + value


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
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    bh_summary_table = cfg['table_prefix']+'bh_daily_summary'
    bh_detail_table = cfg['table_prefix']+'bh_daily_detail'

    cur = con.cursor(MySQLdb.cursors.DictCursor)

    for table, schema in ((bh_summary_table, bh_summary_schema(sql_util)),
                          (bh_detail_table, bh_detail_schema(sql_util))):
        sql_util.ensure_table(cur, table, schema)
        con.commit()

    # find applicable time range
    start_time = calendar.timegm([2016,9,1,0,0,0]) # start collecting data September 1, 2016
    end_time = 86400 * ((time_now // 86400) - 1) # start of yesterday

    analytics = initialize_analyticsreporting()

    def do_update(cur, table, interval, day_start, dt):

        if table == bh_summary_table:
            report = get_summary_report(analytics, day_start, dt)
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",pageviews,sessions,new_users) " + \
                            "VALUES(%s,%s,%s,%s)",
                            ((day_start, row['ga:pageviews'], row['ga:sessions'], row['ga:newUsers']) for row in report))

        elif table == bh_detail_table:
            report = get_detail_report(analytics, day_start, dt)
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",referer,path,count) " + \
                            "VALUES(%s,%s,%s,%s)",
                            ((day_start, row['ga:fullReferrer'], row['ga:pagePath'], row['ga:pageviews']) for row in report))

    for table, affected, interval, dt in ((bh_summary_table, set(), 'day', 86400),
                                          (bh_detail_table, set(), 'day', 86400),):
        SpinETL.update_summary(sql_util, con, cur, table, affected, [start_time,end_time], interval, dt, verbose=verbose, dry_run=dry_run,
                               execute_func = do_update, resummarize_tail = 2*86400)
