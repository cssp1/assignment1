#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import sys, csv, calendar, time

def get_percent(x):
    return 0.01 * float(x[:-1])

def get_unix_time(x):
    m, d, y = map(int, x.split('/'))
    unix = calendar.timegm(time.struct_time([y, m, d, 0, 0, 0, -1, -1, -1]))
    # !! adjust from PST to GMT !!
    unix += 7*60*60
    return unix

# map from Facebook-provided CSV fields to JSON data types
TYPE_MAP = {
             'Date': str,
             'Campaign': str,
             'Campaign ID': str,
             'Impressions': int,
             'Social Impressions': int,
             'Social %': get_percent,
             'Clicks': int,
             'Social Clicks': int,
             'CTR': get_percent,
             'Social CTR': get_percent,
             'CPC': float,
             'CPM': float,
             'Spent': float,
             'Reach': int,
             'Frequency': float,
             'Social Reach': int,
             'Actions': int,
             'Page Likes': int,
             'App Installs': int,
             'Event Responses': None,
             'Unique Clicks': int,
             'Unique CTR': get_percent,
    }

# strip off UTF-8 BOM from Facebook-provided CSV files
def utf_8_encoder(lines):
    for line in lines:
        if line.startswith("\xef\xbb\xbf"):
            ret = line[3:]
        else:
            ret = line
        yield ret

class CSVToJSON (object):
    def __init__(self, source):
        source = utf_8_encoder(source)
        self.source = source
        self.reader = csv.reader(self.source)
        self.header = None
        # dict mapping field name -> column number
        self.header_map = {}

    def produce(self):
        for row in self.reader:
            if not self.header:
                self.header = row
                self.header_map = dict([(row[i], i) for i in xrange(len(row))])
                continue

            data = {}
            for i in xrange(len(row)):
                col = self.header[i]
                coerce = TYPE_MAP[col]
                if not coerce:
                    continue
                datum = coerce(row[i])
                data[col] = datum
                if col == 'Date':
                    data['time'] = get_unix_time(row[i])
            yield data

if __name__ == '__main__':

    converter = CSVToJSON(sys.stdin)
    for row in converter.produce():
        print row
    print converter.header
