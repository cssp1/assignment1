#!/usr/bin/env python

"""Hello Analytics Reporting API V4."""

# see https://developers.google.com/analytics/devguides/reporting/core/v4/basics#dimensions

from apiclient.discovery import build
from oauth2client.service_account import ServiceAccountCredentials

import httplib2
from oauth2client import client
from oauth2client import file
from oauth2client import tools
import sys, os

SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
DISCOVERY_URI = ('https://analyticsreporting.googleapis.com/$discovery/rest')
KEY_FILE_LOCATION = os.path.join(os.getenv('HOME'), '.ssh', 'battlehouse-google-analytics1-key.p12')
SERVICE_ACCOUNT_EMAIL = open(os.path.join(os.getenv('HOME'), '.ssh', 'battlehouse-google-analytics1-service-account-email.txt')).readline().strip()
VIEW_ID = '126674942' # bh.com ALL


def initialize_analyticsreporting():
  """Initializes an analyticsreporting service object.

  Returns:
    analytics an authorized analyticsreporting service object.
  """

  credentials = ServiceAccountCredentials.from_p12_keyfile(
    SERVICE_ACCOUNT_EMAIL, KEY_FILE_LOCATION, 'notasecret', scopes=SCOPES)

  http = credentials.authorize(httplib2.Http())

  # Build the service object.
  analytics = build('analytics', 'v4', http=http, discoveryServiceUrl=DISCOVERY_URI)

  return analytics


def get_report(analytics):
  # Use the Analytics Service Object to query the Analytics Reporting API V4.
  return analytics.reports().batchGet(
      body={
        'reportRequests': [
        {
          'viewId': VIEW_ID,
          'dateRanges': [{'startDate': '2016-09-10', 'endDate': '2016-09-10'},
                         {'startDate': '2016-09-11', 'endDate': '2016-09-11'}],
          'metrics': [{'expression': 'ga:pageviews'},
                      {'expression': 'ga:sessions'},
                      {'expression': 'ga:newUsers'}],
          'dimensions': [{'name': 'ga:fullReferrer'},
                         {'name': 'ga:pagePath'}
                         ]
        }]
      }
  ).execute()


def print_response(response):
  """Parses and prints the Analytics Reporting API V4 response"""

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


def main():

  analytics = initialize_analyticsreporting()
  response = get_report(analytics)
  print_response(response)

if __name__ == '__main__':
  main()
