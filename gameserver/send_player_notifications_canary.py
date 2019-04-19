#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# cut-down version of send_player_notifications.py that sends a canary message to InboxBooster
# for deliverability checks.

import sys, re, getopt
import SpinJSON
import SpinConfig
import Mailgun
import Notification2
import requests

opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['dry-run', 'key', 'email='])

email = None
notif_key = 'retain_23h_incentive' # which FB notification to send
dry_run = False
verbose = True
n2_class = Notification2.USER_ENGAGED
ref_suffix = ''

for key, val in opts:
    if key == '-q':
        verbose = False
    elif key == '--dry-run':
        dry_run = True
    elif key == '--email':
        email = val
    elif key == '--key':
        notif_key = key

if not email:
    raise Exception('must specify --email')

def linebreaks_to_p_br(text):
    """ replace \n\n with </p><p> and \n with <br> for HTML formatting """
    return text.replace('\n\n', '</p><p>').replace('\n', '<br>')

def make_html_safe(text):
    return text.replace('<','&lt;').replace('>','&gt;').replace('&','&amp;')

if 'mailgun_bulk' in SpinConfig.config:
    mailgun = Mailgun.Mailgun(SpinConfig.config['mailgun_bulk'])
else:
    raise Exception('no "mailgun_bulk" in config.json')

# language-neutral version of gamedata['fb_notifications'] for general config settings
fb_notifications_config = SpinJSON.load(open(SpinConfig.gamedata_component_filename('fb_notifications_compiled.json')))
requests_session = requests.session()

if notif_key not in fb_notifications_config['notifications']:
    raise Exception('no such notification "%s"' % notif_key)

config = fb_notifications_config['notifications'][notif_key]

if 'email' not in config:
    raise Exception('no "email" in notification config')

ui_name = config['ui_name']
if isinstance(ui_name, dict): # A/B test
    key_list = sorted(ui_name.keys())
    key = key_list[0]
    assert key.startswith('ui_')
    ui_name = ui_name[key]
    ref_suffix += '_'+key[3:]

template_html_name = 'email_notification_html.html.inlined' if email.lower().endswith('gmail.com') else \
                     'email_notification_html.html'
template_html = open(template_html_name).read().decode('utf-8')
template_plaintext = open('email_notification_plaintext.txt').read().decode('utf-8')

replacements = {'{{ UI_SUBJECT }}': config['email']['ui_subject'],
                '{{ GAME_URL }}': 'https://apps.facebook.com/%s/?fb_source=notification&ref=%s&fb_ref=%s&utm_medium=email' % (SpinConfig.config['facebook_app_namespace'], config['ref'], '%s_%s%s' % (config['ref'], n2_class, ref_suffix)),
                '{{ UI_CTA }}': config['email']['ui_cta'],
                '{{ UI_HEADLINE }}': config['email']['ui_headline'],
                '{{ UI_BODY }}': ui_name,
                '{{ UNSUBSCRIBE_URL }}': '%unsubscribe_url%'} # use Mailgun's native replacement

expr = re.compile('|'.join(replacements.keys()))
ui_body_plaintext = expr.sub(lambda match: replacements[match.group(0)], template_plaintext)

# prevent unwanted HTML injection
for k in replacements:
    if k.startswith('UI_'):
        replacements[k] = linebreaks_to_p_br(make_html_safe(replacements[k]))

ui_body_html = expr.sub(lambda match: replacements[match.group(0)], template_html)

req = mailgun.send(email,
                   config['email']['ui_subject'],
                   ui_body_plaintext,
                   ui_body_html = ui_body_html,
                   tags = ['%s_%s_%s%s' % (SpinConfig.game().upper(), config['ref'], n2_class, ref_suffix)])

if dry_run:
    print req
else:
    mg_response = getattr(requests_session, req['method'].lower())(req['url'], data = req['params'], headers = req['headers'])
    if verbose:
        print 'Mailgun Sent! response: %d %r' % (mg_response.status_code, mg_response.json())
