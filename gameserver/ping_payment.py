#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Run this after receiving a Facebook Realtime Updates API notification about a payment status change.
# Since the notification includes no more info than just the payment ID and the fact that something changed,
# we have to poll the payment Graph API data, and then, if we want the game server to do something about it,
# we queue an asynchronous mail message to the affected player. (the server will handle any necessary actions
# next time it checks the player's mail).

import SpinNoSQL
import SocialIDCache
import SpinFacebook
import SpinConfig
import SpinJSON
from urllib import urlencode
import requests
import sys, getopt, time

time_now = int(time.time())
verbose = False

if __name__ == '__main__':
    dry_run = False
    skip_good = False

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['dry-run','skip-good','verbose'])
    if len(args) < 1:
        sys.exit(1)

    for key, val in opts:
        if key == '--dry-run': dry_run = True
        elif key == '--skip-good': skip_good = True
        elif key == '-v' or key == '--verbose': verbose = True

    payment_id = args[0]

    requests_session = requests.Session()
    client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    social_id_table = SocialIDCache.SocialIDCache(client)

    response = None
    err_msg = None
    attempt = 0
    while (not response) and (attempt < 10):
        attempt += 1
        try:
            url = SpinFacebook.versioned_graph_endpoint_secure('payment', payment_id)+'&'+\
                                                               urlencode({'fields': SpinFacebook.PAYMENT_FIELDS})
            resp = requests_session.get(url, timeout = 30)
            resp.raise_for_status()
            response = SpinJSON.loads(resp.content)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            err_msg = repr(e)
            response = None
    if (not response):
        raise Exception('Facebook API failure on payment %s: %s' % (payment_id, e))

    user_id = None

    # first try getting user_id via facebook_id
    if response.get('user',None):
        facebook_id = response['user']['id']
        user_id = social_id_table.social_id_to_spinpunch('fb'+facebook_id, False)
        if not user_id:
            print 'strange: unknown facebook_id %s' % facebook_id

    # fallback - pull user_id from new request_id format
    if (not user_id) and len(response.get('request_id','').split('_'))>=4:
        user_id = int(response['request_id'].split('_')[1])

    if not user_id:
        if verbose:
            print "HERE", response
        user_id = None
        # sometimes Facebook's API does not return a "user" :(
        # look it up by grepping the credits log...
        #print 'need to get user_id for payment '+payment_id,
        st = time.gmtime(SpinFacebook.parse_fb_time(response['created_time']))
        day = '%04d%02d%02d' % (st.tm_year, st.tm_mon, st.tm_mday)
        log_file = 'logs/%s-credits.json' % day
        for line in open(log_file).xreadlines():
            if response['request_id'] in line:
                event = SpinJSON.loads(line)
                user_id = event['user_id']
                #print 'FOUND!', user_id
                break
        if not user_id:
            raise Exception('could not find user_id for payment '+payment_id)

    print 'PAYMENT', payment_id, 'for user %7d' % user_id,

    skip = False
    if skip_good:
        good = False
        for action in response['actions']:
            if action['type'] == 'charge' and action['status'] == 'completed':
                good = 'completed'
            elif action['type'] == 'charge' and action['status'] == 'failed':
                good = 'failed benignly' # benign failure
            elif action['type'] in ('chargeback','refund','decline') and action['status'] == 'completed':
                good = False
            elif action['type'] == 'chargeback_reversal' and action['status'] == 'completed':
                good = 'reversed'
        if good:
            print 'IS OK (%s)' % good
            skip = True

    if not skip:
        msg = {'to':[user_id],
               'type':'FBRTAPI_payment',
               'time':time_now,
               'expire_time': time_now + SpinConfig.config['proxyserver'].get('FBRTAPI_payment_msg_duration', 30*24*60*60),
               'response': response,
               'payment_id': payment_id}

        if dry_run:
            print SpinJSON.dumps(msg, pretty=True)
            print '(dry run)'
        else:
            print 'SENDING!'
            client.msg_send([msg])
