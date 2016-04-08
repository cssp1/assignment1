#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# send out notifications triggered by SQL metrics

import sys, time, getopt, socket
import SpinReminders
import SpinConfig
import SpinSQLUtil
import SpinJSON
import MySQLdb
from SpinLog import pretty_time

time_now = int(time.time())

# return a list of strings describing metrics alerts
def get_issues(data, game_id):
    issues = []
    if data['hau'] > 10:
        hau = float(data['hau']) # denominator for per-HAU metrics
        if data['cdn_fails'] and float(data['cdn_fails'])/hau >= 0.2:
            issues.append('CDN Issues per HAU >= 0.2')
        if data['browser_fails'] and float(data['browser_fails'])/hau >= 0.2:
            issues.append('Browser Issues per HAU >= 0.2')

        # alert only on 5k+/day notifications. SG has auto-targeting enabled, so no warning is needed.
        if data['fb_notifications_sent_24h'] > 5000 and game_id != 'sg':
            ctr = float(data['fb_notifications_clicked_24h'])/float(data['fb_notifications_sent_24h'])

            # Add an 8% "fudge factor" to account for notification clicks that don't result
            # in a full login and are therefore not recorded in SQL. This is intended to
            # cut down on false alarms where Facebook's CTR metric is not actually too low.
            ctr *= 1.08

            if ctr < 0.17:
                issues.append('FB App-to-User Notification CTR < 17% during last 24h')
    return issues

if __name__ == '__main__':
    verbose = True
    dry_run = False
    game_id = SpinConfig.game()
    recipients = SpinConfig.config.get('alarms_recipients', [])
    dbname = None

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['dry-run','dbname=','recipients='])

    for key, val in opts:
        if key == '-q': verbose = False
        elif key == '--dry-run': dry_run = True
        elif key == '--dbname': dbname = key
        elif key == '--recipients': recipients = SpinJSON.loads(val)

    sql_util = SpinSQLUtil.MySQLUtil()
    if not verbose: sql_util.disable_warnings()

    if dbname is None:
        dbname = '%s_upcache' % game_id
    cfg = SpinConfig.get_mysql_config(dbname)
    con = MySQLdb.connect(*cfg['connect_args'], **cfg['connect_kwargs'])

    cur = con.cursor(MySQLdb.cursors.DictCursor)
    sessions_hourly_summary_table = cfg['table_prefix']+game_id+'_sessions_hourly_summary'
    client_trouble_table = cfg['table_prefix']+game_id+'_client_trouble'
    fb_notifications_table = cfg['table_prefix']+game_id+'_fb_notifications'

    # find last data point in sessions-hourly-summary
    last_valid_hour = None

    cur.execute('SELECT MAX(hour) - 3600 AS last_valid_hour FROM %s' % sql_util.sym(sessions_hourly_summary_table))
    rows = cur.fetchall()
    if rows and rows[0]:
        last_valid_hour = rows[0]['last_valid_hour']

    if not last_valid_hour: # no data
        sys.exit(0)

    raw_data = {}

    # get the HAU data point
    cur.execute('SELECT SUM(hau) AS hau FROM %s WHERE hour = %%s' % (sql_util.sym(sessions_hourly_summary_table)), [last_valid_hour,])
    rows = cur.fetchall()
    raw_data['hau'] = rows[0]['hau']

    # get the browser-issues data points
    cur.execute('''SELECT SUM(IF(event_name = '0660_asset_load_fail',1,0)) AS cdn_fails,
                          SUM(IF(event_name NOT IN ('0660_asset_load_fail','0631_direct_ajax_failure_falling_back_to_proxy','0645_direct_ws_failure_falling_back_to_proxy','0673_client_cannot_log_in_under_attack'),1,0)) AS browser_fails
                   FROM %s WHERE time >= %%s AND time < %%s''' % sql_util.sym(client_trouble_table),
                [last_valid_hour, last_valid_hour + 3600])
    rows = cur.fetchall()
    if rows and rows[0]:
        raw_data['cdn_fails'] = rows[0]['cdn_fails']
        raw_data['browser_fails'] = rows[0]['browser_fails']

    # get the FB notification data points
    # (look at 24h time window for FB notifications to avoid spurious single-hour alerts)
    cur.execute('''SELECT SUM(IF(event_name = '7130_fb_notification_sent',1,0)) AS sent,
                          SUM(IF(event_name = '7131_fb_notification_hit',1,0)) AS clicked
                   FROM %s WHERE time >= %%s AND time < %%s''' % sql_util.sym(fb_notifications_table),
                [last_valid_hour - 23*3600, last_valid_hour + 3600])
    rows = cur.fetchall()
    if rows and rows[0]:
        raw_data['fb_notifications_sent_24h'] = rows[0]['sent']
        raw_data['fb_notifications_clicked_24h'] = rows[0]['clicked']

    con.commit()

    issues = get_issues(raw_data, game_id)

    subject = '%s: Automated alert from %s' % (game_id.upper(), socket.gethostname())
    body = None

    if issues or dry_run:
        body = 'For hour beginning %s (%d):\n' % (pretty_time(time.gmtime(last_valid_hour)), last_valid_hour)
        if issues:
            body += '\n'.join(['ALERT: '+iss for iss in issues])
        else:
            body += '(no alerts)'
        body += '\n\nRaw Data:\n' + '\n'.join(['%-30s: ' % k + (('%10d' % v) if v is not None else '-') for k,v in sorted(raw_data.items())])

    if dry_run:
        print '--- SUBJECT ---\n', subject, '\n--- BODY ---\n', body

    elif body:
        SpinReminders.send_reminders('report_mysql_alarms.py', recipients, subject, body, dry_run = dry_run)
