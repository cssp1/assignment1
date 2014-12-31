#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# run after receiving a Facebook Realtime Updates API notification about a payment status change

import SpinNoSQL
import SocialIDCache
import SpinFacebook
import SpinConfig
import SpinJSON
import sys, getopt, time, urllib, urllib2

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
    access_token = SpinConfig.config['facebook_app_access_token']

    client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
    social_id_table = SocialIDCache.SocialIDCache(client)

    response = None
    attempt = 0
    while (not response) and (attempt < 10):
        attempt += 1
        try:
            url = SpinFacebook.versioned_graph_endpoint('payment', payment_id)+'?'+urllib.urlencode({'access_token':access_token})
            my_timeout = 30
            conn = urllib2.urlopen(urllib2.Request(url))
            response = SpinJSON.loads(conn.read())
        except KeyboardInterrupt:
            raise
        except:
            response = None
    if (not response):
        raise Exception('Facebook API failure on payment '+payment_id)

    if response.get('user',None):
        facebook_id = response['user']['id']
        user_id = social_id_table.social_id_to_spinpunch('fb'+facebook_id, False)
        if not user_id:
            raise Exception('unknown facebook_id %s' % facebook_id)
    elif len(response.get('request_id','').split('_'))==4:
        user_id = int(response['request_id'].split('_')[1])
    else:
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
