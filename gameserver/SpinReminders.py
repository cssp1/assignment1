#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# utility for sending out reminders via email or hipchat, used by dev_reminders.py and report_slow_mysql.py

import smtplib, urllib, urllib2, getpass, os, time
from email.mime.text import MIMEText
from email.header import Header
import SpinJSON
import SpinConfig

def compose_message(header_from, header_to, subject, body):
#    return 'From: %s\r\nTo: %s\r\nDate: %s\r\nSubject: %s\r\n\r\n%s\n' % (header_from, header_to, email.Utils.formatdate(localtime=False), subject, body)
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = header_from
    msg['To'] = Header(header_to)
    return msg.as_string()

def send_reminder_email(sender_name, cclist, subject, body):
    sender_email = getpass.getuser() + '@spinpunch.com' # necessary to pass SPF filters
    message = compose_message('"%s" <%s>' % (sender_name, sender_email),
                              ', '.join(['"%s" <%s>' % (cc['name'],cc['address']) for cc in cclist]),
                              subject,
                              body)
    smtplib.SMTP('localhost').sendmail(sender_email, [cc['address'] for cc in cclist], message)

def send_reminder_hipchat(room, ats, subject, body):
    token = os.getenv('HIPCHAT_TOKEN') or open(os.path.join(os.getenv('HOME'), '.ssh', 'hipchat.token')).read().strip()
    url = "https://api.hipchat.com/v2/room/%s/notification?auth_token=%s" % (room, token)
    req_body = SpinJSON.dumps({'message':', '.join(ats) + ' ' + subject + ': ' + body[:2500], 'message_format':'text'})
    req = urllib2.Request(url)
    req.add_header('Content-Type', 'application/json')
    req.add_data(req_body)
    urllib2.urlopen(req).read()

def send_reminder_slack(sender_name, channel, ats, subject, body):
    token = os.getenv('SLACK_TOKEN') or SpinConfig.config.get('slack_token','') or open(os.path.join(os.getenv('HOME'), '.ssh', 'slack.token')).read().strip()
    url = "https://"+SpinConfig.config['slack_subdomain']+".slack.com/services/hooks/incoming-webhook?token=%s" % token
    MAXLEN = 2500
    ellipsis = '\n... (and more)' if len(body) > MAXLEN else ''
    req_body = SpinJSON.dumps({'username':sender_name.lower(), 'channel':channel, 'text':', '.join(ats) + ' ' + subject + ': ' + body[:MAXLEN] + ellipsis})
    req = urllib2.Request(url)
    req.add_header('Content-Type', 'application/json')
    req.add_data(req_body)
    urllib2.urlopen(req).read()

def send_reminder_mattermost(sender_name, channel, ats, subject, body):
    webhook_url = os.getenv('MATTERMOST_WEBHOOK_URL') or SpinConfig.config.get('mattermost_webhook_url','') or open(os.path.join(os.getenv('HOME'), '.ssh', 'mattermost-webhook-url')).read().strip()
    assert webhook_url.startswith('https://')
    MAXLEN = 2500
    ellipsis = '\n... (and more)' if len(body) > MAXLEN else ''
    req_json = {'text':', '.join(ats) + ' ' + subject + ': ' + body[:MAXLEN] + ellipsis}
    if channel:
        req_json['channel'] = channel
    req_body = SpinJSON.dumps(req_json)
    req = urllib2.Request(webhook_url)
    #req.add_header('Content-Type', 'application/json')
    req.add_data(urllib.urlencode({'payload':req_body}))
    urllib2.urlopen(req).read()

def send_reminder_amazon_sns(region, topic_arn, subject, body):
    if not region:
        #import boto.utils
        #region = boto.utils.get_instance_metadata()['placement']['availability-zone'][0:-1]
        region = topic_arn.split(':')[3] # is this consistently the region?
    import boto.sns
    con = boto.sns.connect_to_region(region)
    con.publish(topic = topic_arn, message = body, subject = subject)

def send_reminder_file(filename, subject, body):
    fd = open(filename, 'a+')
    ui_time = time.strftime('%Y-%m-%dZ%H:%M:%S', time.gmtime())
    fd.write('Time: %s\nSubject: %s\n%s\n---\n' % (ui_time, subject, body))
    fd.flush()
    fd.close()

def send_reminders(sender_name, recip_list, subject, body, dry_run = False):
    if dry_run:
        print 'body is:', body
        return
    for recip in recip_list:
        if recip['type'] == 'email':
            send_reminder_email(sender_name, recip['to'], subject, body)
        elif recip['type'] == 'hipchat':
            send_reminder_hipchat(recip['room'], recip['ats'], subject, body)
        elif recip['type'] == 'slack':
            send_reminder_slack(sender_name, recip['channel'], recip.get('ats',[]), subject, body)
        elif recip['type'] == 'mattermost':
            send_reminder_mattermost(sender_name, recip.get('channel'), recip.get('ats',[]), subject, body)
        elif recip['type'] == 'amazon_sns':
            send_reminder_amazon_sns(recip.get('region'), recip['topic_arn'], subject, body)
        elif recip['type'] == 'file':
            send_reminder_file(recip['filename'], subject, body)

if __name__=='__main__':
    import getopt, sys
    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['dry-run','from=','subject=','body=','body-from=','recipient=','recipients='])
    dry_run = False
    subject = 'SpinReminders Subject'
    body = 'SpinReminders Body'
    sender_name = 'SpinReminders'
    recipients = []
    for key, val in opts:
        if key == '--dry-run': dry_run = True
        elif key == '--from': sender_name = val
        elif key == '--subject': subject = val
        elif key == '--body': body = val
        elif key == '--body-from': body = open(val).read().strip()
        elif key == '--recipient': recipients.append(SpinJSON.loads(val))
        elif key == '--recipients': recipients += SpinJSON.loads(val)

    send_reminders(sender_name, recipients, subject, body, dry_run=dry_run)
