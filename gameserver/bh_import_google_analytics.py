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
import SpinMySQLdb

time_now = int(time.time())

def bh_summary_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('pageviews', 'INT8 NOT NULL'),
                       ('sessions', 'INT8 NOT NULL'),
                       ('new_users', 'INT8 NOT NULL'),
                       ('dau', 'INT8 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }
def bh_detail_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('referer', 'VARCHAR(1024)'),
                       ('path', 'VARCHAR(1024)'),
                       ('count', 'INT4 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }
def bh_clicks_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('click', 'VARCHAR(1024) NOT NULL'),
                       ('count', 'INT4 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }
def bh_login_campaign_summary_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('event_name', 'VARCHAR(1024) NOT NULL'),
                       ('event_data', 'VARCHAR(1024)'),
                       ('campaign_name', 'VARCHAR(1024)'),
                       ('campaign_source', 'VARCHAR(1024)'),
                       ('campaign_id', 'VARCHAR(1024)'),
                       ('count', 'INT4 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }
def bh_login_summary_schema(sql_util):
    return {'fields': [('day', 'INT8 NOT NULL'),
                       ('event_name', 'VARCHAR(1024) NOT NULL'),
                       ('event_data', 'VARCHAR(1024)'),
                       ('count', 'INT4 NOT NULL'),
                       ],
            'indices': {'by_interval': {'unique':False, 'keys': [('day','ASC')]}}
            }

# Google Analytics API boilerplate
from apiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

import httplib2

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


def get_report(analytics, day_start, dt, list_of_metrics, list_of_dimensions = None,
               dimension_filter_clauses = None):
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
    if dimension_filter_clauses:
        request['dimensionFilterClauses'] = dimension_filter_clauses

    report = analytics.reports().batchGet(body={'reportRequests': [request]}).execute()['reports'][0]
    rows = report['data'].get('rows', [])
    if list_of_dimensions:
        ret = []
        for row in rows:
#            if verbose: print row
            d = dict((met, int(row['metrics'][0]['values'][i])) for i, met in enumerate(list_of_metrics))
            d.update(dict((dim, row['dimensions'][j]) for j, dim in enumerate(list_of_dimensions)))
            ret.append(d)
        return ret
    else:
        return [dict((met, int(row['metrics'][0]['values'][i])) for i, met in enumerate(list_of_metrics)) for row in rows]

def get_summary_report(analytics, day_start, dt):
    assert dt == 86400 # ga:newUsers requires one-day query
    report = get_report(analytics, day_start, dt, ['ga:pageviews','ga:sessions','ga:newUsers','ga:1dayUsers'], ['ga:date'])
    return report
def get_detail_report(analytics, day_start, dt):
    report = get_report(analytics, day_start, dt, ['ga:pageviews'], ['ga:fullReferrer', 'ga:hostname', 'ga:pagePath'])
    return report
def get_event_report(analytics, categories, day_start, dt, extra_dimensions = [], extra_filters = []):
    filter_clause = {'dimensionName': 'ga:eventCategory',
                     'expressions': categories}
    if len(categories) > 1:
        filter_clause['operator'] = 'IN_LIST'
    else:
        filter_clause['operator'] = 'EXACT'

    report = get_report(analytics, day_start, dt, ['ga:totalEvents'], ['ga:eventAction', 'ga:eventLabel'] + extra_dimensions,
                        dimension_filter_clauses = [{'filters': [filter_clause] + extra_filters}])
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
    con = SpinMySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])
    bh_summary_table = cfg['table_prefix']+'bh_daily_summary'
    bh_detail_table = cfg['table_prefix']+'bh_daily_detail'
    bh_clicks_table = cfg['table_prefix']+'bh_daily_clicks'
    bh_login_summary_table = cfg['table_prefix']+'bh_login_daily_summary'
    bh_login_campaign_summary_table = cfg['table_prefix']+'bh_login_campaign_daily_summary'

    cur = con.cursor(SpinMySQLdb.cursors.DictCursor)

    for table, schema in ((bh_summary_table, bh_summary_schema(sql_util)),
                          (bh_detail_table, bh_detail_schema(sql_util)),
                          (bh_clicks_table, bh_clicks_schema(sql_util)),
                          (bh_login_summary_table, bh_login_summary_schema(sql_util)),
                          (bh_login_campaign_summary_table, bh_login_campaign_summary_schema(sql_util)),
                          ):
        sql_util.ensure_table(cur, table, schema)
        con.commit()

    # find applicable time range
    start_time = calendar.timegm([2016,12,5,0,0,0]) # start collecting data December 5, 2016
    end_time = 86400 * (time_now // 86400) # start of today

    analytics = initialize_analyticsreporting()

    def do_update(cur, table, interval, day_start, dt):

        if table == bh_summary_table:
            report = get_summary_report(analytics, day_start, dt)
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",pageviews,sessions,new_users,dau) " + \
                            "VALUES(%s,%s,%s,%s,%s)",
                            [(day_start, row['ga:pageviews'], row['ga:sessions'], row['ga:newUsers'], row['ga:1dayUsers']) for row in report])

        elif table == bh_detail_table:
            report = get_detail_report(analytics, day_start, dt)
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",referer,path,count) " + \
                            "VALUES(%s,%s,%s,%s)",
                            [(day_start, row['ga:fullReferrer'], row['ga:hostname']+row['ga:pagePath'], row['ga:pageviews']) for row in report])

        elif table == bh_clicks_table:
            report = get_event_report(analytics, ["outbound-article","outbound-widget"], day_start, dt)
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",click,count) " + \
                            "VALUES(%s,%s,%s)",
                            [(day_start, '"%s" (%s)' % (row['ga:eventLabel'],row['ga:eventAction']), row['ga:totalEvents']) for row in report])
        elif table == bh_login_summary_table:
            report = get_event_report(analytics, ["bhlogin"], day_start, dt)
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",event_name,event_data,count) " + \
                            "VALUES(%s,%s,%s,%s)",
                            [(day_start,
                              row['ga:eventAction'],
                              row.get('ga:eventLabel',None),
                              row['ga:totalEvents']) for row in report])
        elif table == bh_login_campaign_summary_table:

            # need two separate queries here, due to quirkiness of the Google Analytics Reporting API

            # it silently drops rows that don't have values along extra_dimensions

            # first, query NON-Google Adwords events, which use campaign/source/code to disambiguate
            report = get_event_report(analytics, ["bhlogin"], day_start, dt,
                                      extra_dimensions = ['ga:campaign', 'ga:source', 'ga:campaignCode'],
                                      extra_filters =[{'dimensionName': 'ga:source',
                                                       'expressions': ['google'],
                                                       'not': True,
                                                       'operator': 'EXACT'},
                                                      {'dimensionName': 'ga:medium',
                                                       'expressions': ['cpc'],
                                                       'not': True,
                                                       'operator': 'EXACT'}])
            cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                            "("+sql_util.sym(interval)+",event_name,event_data,campaign_name,campaign_source,campaign_id,count) " + \
                            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                            [(day_start,
                              row['ga:eventAction'],
                              row.get('ga:eventLabel',None),
                              row.get('ga:campaign',None),
                              row.get('ga:source',None),
                              row.get('ga:campaignCode',None),
                              row['ga:totalEvents']) for row in report])

            # second, grab ONLY Google Adwords events (as identified by google/cpc source/medium)
            report = get_event_report(analytics, ["bhlogin"], day_start, dt,
                                      extra_dimensions = ['ga:campaign'],
                                      extra_filters =[{'dimensionName': 'ga:source',
                                                       'expressions': ['google'],
                                                       'operator': 'EXACT'},
                                                      {'dimensionName': 'ga:medium',
                                                       'expressions': ['cpc'],
                                                       'operator': 'EXACT'}])

            try:
                to_insert = [(day_start,
                              row['ga:eventAction'],
                              row.get('ga:eventLabel',None),
                              'google', # campaign
                              'google', # source
                              row.get('ga:campaign',None), # note: Google Adwords Campaign name ->Code
                              row['ga:totalEvents']) for row in report]
                cur.executemany("INSERT INTO "+sql_util.sym(table)+" " + \
                                "("+sql_util.sym(interval)+",event_name,event_data,campaign_name,campaign_source,campaign_id,count) " + \
                                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                                to_insert)
            except:
                print cur._last_executed
                print '\n'.join(map(repr, to_insert))
                raise

    for table, affected, interval, dt in ((bh_summary_table, set(), 'day', 86400),
                                          (bh_detail_table, set(), 'day', 86400),
                                          (bh_clicks_table, set(), 'day', 86400),
                                          (bh_login_summary_table, set(), 'day', 86400),
                                          (bh_login_campaign_summary_table, set(), 'day', 86400),
                                          ):
        SpinETL.update_summary(sql_util, con, cur, table, affected, [start_time,end_time], interval, dt, verbose=verbose, dry_run=dry_run,
                               execute_func = do_update, resummarize_tail = 2*86400)
