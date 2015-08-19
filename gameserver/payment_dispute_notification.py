#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinConfig
import SpinJSON
import SpinUserDB
import sys, getopt, time, math
import base64, urllib2

time_now = int(time.time())
verbose = False

test_input = '''{"id":"example_payment","user":{"name":"Frank","id":"example3"},"actions":[{"type":"charge","status":"completed","currency":"USD","amount":"50.00","time_created":"2014-02-09T16:34:55+0000","time_updated":"2014-02-09T16:34:55+0000"}],"refundable_amount":{"currency":"USD","amount":"50.00"},"items":[{"type":"IN_APP_PURCHASE","product":"http:\/\/trprod.spinpunch.com\/OGPAPI?spellname=BUY_GAMEBUCKS_5000_FBP_P100M_USD&type=tr_sku","quantity":1}],"country":"US","request_id":"tr_1102945_8f64174bf243e51fedfeb2f468dcccb6_1541","created_time":"2014-02-09T16:34:55+0000","payout_foreign_exchange_rate":1,"disputes":[{"user_comment":"I bougth 50 dollars and press the x in the corner so I took me back to the game so I triedgain it did give me my 50 dollars worth in  gold I had a hundred in card so I tried again to get my other 50 dollars in gold and it declined my card that means that one of the payments went tru but I didn\'t got my gold!! pls help me","time_created":"2014-02-10T23:12:49+0000","user_email":"asdf\u0040example.com"}]}'''

def reverse_digits(n):
    if n <= 0: return '0'
    n = math.ceil(n)
    ret = ''
    while (n > 0):
        ret += '%d' % (n%10)
        n = n//10
    return ret

if __name__ == '__main__':
    dry_run = False
    opts, args = getopt.gnu_getopt(sys.argv[1:], 'v', ['dry-run','verbose'])

    for key, val in opts:
        if key == '--dry-run': dry_run = True
        elif key == '-v' or key == '--verbose': verbose = True

    if len(args) != 1:
        print 'usage: %s user_id (with JSON payment graph object on stdin)' % sys.argv[0]
        sys.exit(1)

    user_id = int(args[0])
    response = SpinJSON.load(sys.stdin)
    #response = SpinJSON.loads(test_input)

    user = SpinJSON.loads(SpinUserDB.driver.sync_download_user(user_id))
    player = SpinJSON.loads(SpinUserDB.driver.sync_download_player(user_id))

    zd_game_id = {'mf': 'mars_frontier', 'tr':'thunder_run', 'mf2': 'war_star_empire', 'bfm':'battlefront_mars', 'dv': 'days_of_valor', 'sg':'summoners_gate'}[SpinConfig.game()]
    player_name = user.get('alias', user.get('ag_username', user.get('kg_username', user.get('facebook_name', 'unknown'))))
    player_email = user.get('email', 'unknown')
    facebook_id = response['user']['id'] if 'user' in response else user.get('facebook_id', 'unknown')
    payment_id = str(response['id'])
    payment_amount = 'unknown'
    payment_currency = 'unknown'
    for action in response['actions']:
        if ('currency' in action) and ('amount' in action):
            payment_currency = action['currency']
            payment_amount = action['amount']
            break

    dispute_comments = []
    for item in response.get('disputes',[]):
        if 'user_email' in item: player_email = item['user_email']
        if 'user_comment' in item:
            dispute_comments.append('At %s the player said:\n"' % item['time_created'] + item['user_comment']+'"')

    money_spent = player['history'].get('money_spent',0)
    camo_money_spent = reverse_digits(money_spent)
    if money_spent >= 1000:
        pp_code = '3888'
    elif money_spent >= 100:
        pp_code = '2888'
    else:
        pp_code = '1866'

    body = {
        "ticket": {
        "requester": {"name": player_name,
                      "email": player_email},
        "subject": "Payment Dispute %s %s %s" % (payment_amount, payment_currency, payment_id),
        "comment": { "body": "Player %d has disputed payment %s for %s %s at Facebook.\n\nWE MUST UPDATE THE DISPUTE STATUS (https://developers.facebook.com/docs/howtos/payments/disputesrefunds/#updatedisputestatus) or Facebook will automatically refund this payment.\n\n%s" % \
                     (user_id, payment_id, payment_amount, payment_currency, '\n\n'.join(dispute_comments)) },
        "custom_fields": [{"id": 23205756,"value": zd_game_id},
                          {"id": 21701081,"value": str(user_id)},
                          {"id": 21760571,"value": SpinConfig.game()+"_"+str(user_id)+"_"+camo_money_spent},
                          {"id": 22001948,"value": str(facebook_id)}],
        "tags": ["pp_code_"+pp_code,"pp_code_nonzero",zd_game_id,"fb_payment_dispute"],
        }
        }

    request = urllib2.Request('https://'+SpinConfig.config['zendesk_subdomain']+'.zendesk.com/api/v2/tickets.json')
    request.add_header('Authorization', b'Basic %s' % base64.urlsafe_b64encode(SpinConfig.config['zendesk_api_user']+b'/token:'+SpinConfig.config['zendesk_api_token']))
    request.add_header('Content-Type', 'application/json')
    request.add_header('Accept', 'application/json')
    request.add_data(SpinJSON.dumps(body))
    if dry_run:
        print SpinJSON.dumps(body, pretty=True)
        SpinJSON.dump(body, open('/tmp/payment-dispute-output','w'), pretty=True, newline=True)
    else:
        print urllib2.urlopen(request).read()
