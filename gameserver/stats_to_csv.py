#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# NOTE: this script is mis-named. It converts the cumulative JSON
# stats log file logs/stats.json into nice HTML graphs. It does not
# output CSV anymore, despite the name.

try:
    import simplejson as json
except:
    import json
import sys, time, string
import csv
import getopt
import SpinConfig

WEEKS_SINCE_LAUNCH = int((time.time() - SpinConfig.game_launch_date())/(60*60*24*7))

FIELDS = ["date"]

SEARCH_KEYS = [["ALL", ['ALL']],
               ["country_tier", ['1', '2', '3', '4']],
#              ["country", ['us', 'ca', 'gb', 'ph', 'tr', 'au', 'se', 'nl', 'fi']],
               ["acquisition_campaign", [
                  '5340','5343',
                  '5341', '5342', '5350', '5351', '5352', '5353', '5360', '5361', '5362',
                  '5344_EPT12DEnUS', '5345_EPTR', '5346_EPT12DE_fr', '5347_EPUK', '5348_AWT12DE', '5349_EMT12DE',
                  '5501_EMT12DEnUS'
#                  'facebook_app_request', 'facebook_friend_invite'
                  ]],
#               "join_week": [str(x) for x in range(WEEKS_SINCE_LAUNCH+2)],
#               "days_since_joined": [str(x) for x in range(11)],
#              "is_paying_user": ['0', '1'],
#               "is_whale": ['0', '1'],
#               ["T004_first_purchase_one_muffin", ['0', '1']],
               ["T009_chrome_audio", ['chrome_audio_on', 'chrome_audio_off']],
               ["T010_flashy_loot", ['flashy_loot_on', 'flashy_loot_off']],
               ]

#SEARCH_KEYS = [["ALL", ['ALL']]]

METRICS_VALUES = [
    ['unique_users', 'DAU', 'number', 1, 'time', None],
    ['revenue', 'Daily Revenue', 'big_money', 1, 'time', None],
    ['AvgRev/DAU', 'ARPDAU, 7-day moving average', 'little_money', 7, 'linear', 'unique_users'],
    ['AvgRev/PDAU', 'ARPPDAU, 7-day moving average', 'little_money', 7, 'linear', 'unique_paying_users'],
#    ['unique_paying_users', 'PDAU', 'number', 1, 'time', None],
    ['unique_new_users', 'New Users', 'number', 1, 'time', None],
    ['tutorial_completion_rate', 'Tutorial Completion Rate', 'percent', 1, 'linear', 'unique_new_users'],
    ['trailing_retention_1d', '1-Day Retention (by Day 2)', 'percent', 1, 'linear', 'trailing_retention_1d_N'],
    ['trailing_retention_2d', '2-Day Retention (by Day 3)', 'percent', 1, 'linear', 'trailing_retention_2d_N'],
    ['trailing_retention_7d', '7-Day Retention (by Day 14)', 'percent', 1, 'linear', 'trailing_retention_7d_N'],
    ['trailing_retention_30d', '30-Day Retention (by Day 60)', 'percent', 1, 'linear', 'trailing_retention_30d_N'],
    ['trailing_avg_receipts_1d', '1-Day Receipts Per User', 'little_money', 1, 'linear', 'trailing_avg_receipts_1d_N'],
    ['trailing_avg_receipts_3d', '3-Day Receipts Per User', 'little_money', 1, 'linear', 'trailing_avg_receipts_3d_N'],
    ['trailing_avg_receipts_7d', '7-Day Receipts Per User', 'little_money', 1, 'linear', 'trailing_avg_receipts_7d_N'],
    ['trailing_avg_receipts_60d', '60-Day Receipts Per User', 'little_money', 1, 'linear', 'trailing_avg_receipts_60d_N'],
    ['trailing_avg_visits_0d', 'First-day Visits Per User', 'number', 1, 'linear', 'trailing_avg_receipts_0d_N'],
    ['trailing_avg_visits_3d', '3-Day Visits Per User', 'number', 1, 'linear', 'trailing_avg_receipts_3d_N'],
    ['trailing_ltv_est_60d', '60-Day User LTV est (60-day Receipts/User excl. accounts younger than 30 days)', 'little_money', 1, 'linear', 'trailing_ltv_est_60d_N'],
    ['trailing_total_receipts_60d', '60-Day Total Receipts', 'big_money', 1, 'linear', None],
    ]
USERDB_VALUES = [
    ['friends_in_game', 'Avg # Friends In Game', 'number', 1, 'linear', 'N'],
    ['k_factor', 'K Factor (lower bound)', 'percent', 1, 'linear', 'N'],
    ]

CATEGORIES = ['%s_%s' % (prefix,suffix) for prefix, suffixlist in SEARCH_KEYS for suffix in suffixlist]
FIELDS += ['%s_%s' % (value[1],category) for category in CATEGORIES for value in METRICS_VALUES]

# indexed from 0 for JavaScript
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

VALUE_FORMATS = {
    'big_money': '$%.2f',
    'little_money': '$%.3f',
    'number': '%g',
    'percent': '%.1f%%'
    }
ICU_FORMATS = {
    'big_money': '\u00A4 #,##0',
    'little_money': '\u00A4 #,##0.00', # shows cents
    'number': '#,##0',
    'percent': '##0 %'
    }

if __name__ == "__main__":
    # use the getopt library to parse command-line arguments
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['mode=','quiet'])
    if len(args) < 1:
        print 'usage: %s foo.json > foo.csv' % sys.argv[0]
        sys.exit(1)

    infiles = args

    mode = 'stats'
    verbose = True

    for key, val in opts:
        if key == '--mode':
            mode = val
        elif key == '--quiet':
            verbose = False

    # list of samples by ptime
    metrics_samples = {}
    userdb_samples = {}

    # we have to store, filter, and sort lines of data because they
    # aren't necessarily in chronological order, and some days may have
    # been computed more than once.

    for filename in infiles:
        for line in open(filename).readlines():
            input = json.loads(line)

            kind = input.get('type', 'daily_metrics')

            if kind == 'daily_metrics':
                samples = metrics_samples
            elif kind == 'userdb_scan':
                samples = userdb_samples
            else:
                sys.stderr.write('ignoring unhandled sample type %s\n' % kind)
                continue

            ptime = input['ptime']
            if ptime not in samples:
                    samples[ptime] = input
            else:
                # replace existing sample if computed_time is greater
                if int(input['computed_time']) > int(samples[ptime]['computed_time']):
                   samples[ptime] = input

    if verbose:
        sys.stderr.write('got %d days of metrics samples\n' % len(metrics_samples))
        sys.stderr.write('got %d days of userdb samples\n' % len(userdb_samples))

    # sort analytics samples into linear array in ascending time order
    metrics_data = sorted(metrics_samples.values(), key = lambda x: x['time'])
    userdb_data = sorted(userdb_samples.values(), key = lambda x: x['time'])

    # NEW HTML CODE
    if 1:
        writer = sys.stdout
        writer.write('''<html>
        <head title="Mars Frontier Analytics">
        <!--Load the AJAX API-->
        <script type="text/javascript" src="https://www.google.com/jsapi"></script>
        <script type="text/javascript">

        // Load the Visualization API and the piechart package.
        google.load('visualization', '1.0', {'packages':['corechart']});

        // Set a callback to run when the Google Visualization API is loaded.
        google.setOnLoadCallback(drawCharts);
        function drawCharts() {
            var data, options, chart;

            // Set chart options
            options = {'title':'',
                       'legend':'none',
                       'width':500,
                       'height':250};
            ''')

        charts = []

        def make_chart(i, source_data, pretty_title, valuename, dbkey, dbval, format, window, extrap, nfield):
            ret = ['''
            data = new google.visualization.DataTable();
            data.addColumn('date', 'Date');
            data.addColumn('number', 'Val');
            data.addColumn({type:'string', role:'tooltip'});
            data.addColumn({type:'boolean', role:'certainty'});
            data.addRows([''']

            n_nonzero = 0

            last_point = len(source_data)
            if extrap == 'omit':
                last_point -= 1

            for j in xrange(last_point):

                month, day, year = map(int, source_data[j]['ptime'].split('/'))

                n_total = 0
                value = 0
                N = 0

                for k in range(window):
                    if j-k < 0:
                        continue
                    n_total += 1
                    data = source_data[j-k]
                    if dbkey not in data['index']:
                        value += 0
                    elif dbval not in data['index'][dbkey]:
                        value += 0
                    elif valuename not in data['index'][dbkey][dbval]:
                        value += 0
                    else:
                        value += data['index'][dbkey][dbval][valuename]
                        if nfield and nfield in data['index'][dbkey][dbval]:
                            N += data['index'][dbkey][dbval][nfield]

                value /= float(n_total)
                N /= float(n_total)

                if value != 0:
                    n_nonzero += 1
                elif n_nonzero == 0:
                    continue

                certainty = 'true'

                if j >= (len(source_data)-1):
                    if extrap == 'time':
                        certainty = 'false'
                        duration = data['end_time']-data['time']
                        value *= (24*60*60)/float(duration)

                str_value = VALUE_FORMATS[format] % (100.0*value if format == 'percent' else value)

                # note: JavaScript uses 0-11 for months!
                tooltip = '%s %d: %s' % (MONTH_NAMES[month-1], day, str_value)
                if nfield:
                    tooltip += ' (N=%d)' % N
                str = '[new Date(%d, %d, %d), %g, "%s", %s]' % (year, month-1, day, value, tooltip, certainty)
                if j != len(source_data)-1:
                    str += ','
                ret.append(str)

            if n_nonzero < 2:
                if verbose:
                    sys.stderr.write('not enough data yet for %s:%s:%s\n' % (valuename, dbkey, dbval))
                # empty chart
                return None

            title = pretty_title+' (%s : %s)' % (dbkey, dbval)

            width = 500
            if dbkey == "ALL":
                width = 600
                height = 300
            else:
                width = 500
                height = 150

            ret.append(']);')
            ret.append("options['title'] = '"+title+"';")
            ret.append("options['width'] = %d;" % width)
            ret.append("options['height'] = %d;" % height)
            ret.append("options['vAxis']= {'format':'%s'};" % ICU_FORMATS[format])
            ret.append('''
            // Instantiate and draw our chart, passing in some options.
            chart = new google.visualization.LineChart(document.getElementById('chart%d_div'));
            chart.draw(data, options);
            ''' % i)
            return string.join(ret, '\n')

        counter = 0
        for name, pretty_name, format, window, extrap, nfield in METRICS_VALUES:
            for dbkey, dbval_list in SEARCH_KEYS:
                for dbval in dbval_list:
                    charts.append(make_chart(counter, metrics_data, pretty_name, name, dbkey, dbval, format, window, extrap, nfield)); counter += 1

        for name, pretty_name, format, window, extrap, nfield in USERDB_VALUES:
            for dbkey, dbval_list in SEARCH_KEYS:
                for dbval in dbval_list:
                    charts.append(make_chart(counter, userdb_data, pretty_name, name, dbkey, dbval, format, window, extrap, nfield)); counter += 1


        for chart in charts:
            if chart:
                writer.write(chart)

        writer.write('''
        }
        </script>
        </head>

        <body>''')
        writer.write('Charts produced at '+time.strftime('%c')+' UTC time<br>\n')
        writer.write('Last data sample is dated <b>'+metrics_data[-1]['ptime']+'</b><br>\n')
        writer.write('Dotted lines indicate projections based on less than 24 hours of data<p>\n')

        writer.write('<!--Div that will hold the charts-->\n')
        for i in range(len(charts)):
            writer.write('<div id="chart%d_div"></div>\n' % i)

        writer.write('''</body></html>\n''')


    # OLD CSV CODE
    if 0:
        # ok now get ready to write the CSV file
        writer = csv.DictWriter(sys.stdout, FIELDS, dialect='excel')
        writer.writerow(dict((fn,fn) for fn in FIELDS))

        index = input['index']
        out = {}
        out['date'] = input['ptime']
        for prefix, suffixlist in SEARCH_KEYS:
            for suffix in suffixlist:
                if prefix in index:
                    if suffix in index[prefix]:
                        for value_in, value_out, format in METRICS_VALUES:
                            if value_in in index[prefix][suffix]:
                                out['%s_%s_%s' % (value_out,prefix,suffix)] = index[prefix][suffix][value_in]

        # write the output row to the CSV file
        try:
            writer.writerow(out)
        except:
            sys.stderr.write('PROBLEM ROW: '+repr(out)+'\n')
            raise
