#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinJSON
import time
import base64

#
# XSOLLA API tools - see http://developers.xsolla.com/
#

# This requires a bunch of per-game setup on the Xsolla merchant site.
# (including, possibly, creating "packages" for all currency price points).
# Also the config.json entries referenced by "config" below.

def unparse_time(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S+0000', time.gmtime(t))

# return the set of HTTP headers needed to get the API to work
def make_headers(config):
    return {'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': 'Basic '+str(base64.b64encode(str(config['xsolla_merchant_id'])+':'+str(config['xsolla_api_key'])))}

# return the (method,headers,body) for a request to update the Xsolla virtual currency settings for this game.
# This tells Xsolla about all the possible SKUs (including predicate-based discounts, which are protected by
# the server-side order path).
# This currently steals the SKUs from the Facebook Open Graph virtual currency.

# To use:
# curl https://api.xsolla.com/merchant/projects/PROJECT_ID/virtual_currency -X PUT -H 'Content-Type:application/json' -u 'MERCHANT_ID:API_KEY' -H 'Accept:application/json' -d "`./SpinXsolla.py`"

def make_virtual_currency_settings_update(config, gamedata):
    body_json = { 'vc_name': {'en': gamedata['store']['gamebucks_ui_name']},
                  'base': dict((currency, float(str_amount)) for currency, str_amount in gamedata['store']['gamebucks_open_graph_prices']),
                  'default_currency': gamedata['store']['gamebucks_open_graph_prices'][0][0],
                  'min': 0, 'max': 0, 'is_currency_discrete': True,
                  'type': 'packets', 'allow_user_sum': False, # do not allow users to change the purchase amount
                  'packets': {}
                  }
    # now the currency slates
    for spellname, data in gamedata['spells'].iteritems():
        if 'open_graph_prices' in data and data.get('currency','').startswith('fbpayments:'):
            currency = data['currency'].split(':')[1]
            if currency not in body_json['packets']:
                body_json['packets'][currency] = []
            packet = {'amount': data['quantity'],
                      'price': data['price'],
                      'image_url': '//s3.amazonaws.com/'+config['public_s3_bucket']+'/facebook_assets/'+gamedata['store']['fb_open_graph_gamebucks_icon'],
                      'description': { 'en': data['ui_name'].replace('%GAMEBUCKS_QUANTITY', '%d' % data['quantity']).replace('%GAME_NAME', gamedata['strings']['game_name']).replace('%GAMEBUCKS_NAME', gamedata['store']['gamebucks_ui_name']) },
                      }
            body_json['packets'][currency].append(packet)
    return 'PUT', make_headers(config), SpinJSON.dumps(body_json) # this must be an HTTP "PUT" to work


# return the (method,headers,body) for a request to generate an Xsolla "token" to start the purchase flow
# @param config - from SpinConfig config.json
def make_token_request(config,
                       user_xs_id, user_email, user_currency, user_country, user_language,
                       gamebucks_quantity, gamebucks_ui_description,
                       player_level, user_account_creation_time,
                       ):
    is_sandbox = (not config.get('secure_mode', True))

    body_json = {
        'user': { 'id': { 'value': user_xs_id, 'hidden': True } },
        'settings': { 'project_id': config['xsolla_project_id'],
                      'currency': user_currency },
        'purchase': { 'virtual_currency': { 'quantity': gamebucks_quantity },
                      'description': { 'value': gamebucks_ui_description } },
        'custom_parameters': { 'user_level': player_level,
                               'registration_date': unparse_time(user_account_creation_time) }
    }
    if is_sandbox:
        body_json['settings']['mode'] = 'sandbox'
    if user_language:
        assert len(user_language) == 2
        body_json['settings']['language'] = user_language
    if user_country:
        assert len(user_country) == 2
        body_json['user']['country'] = { 'value': user_country.upper(), 'allow_modify': False } # ?

    if user_email:
        body_json['user']['email'] = { 'value': user_email }

    return 'POST', make_headers(config), SpinJSON.dumps(body_json)

if __name__ == '__main__':
    import SpinConfig
    if 0:
        print make_token_request(SpinConfig.config, 'xs1234', 'example@example.com',
                                 'USD', 'us', 'en', 100, '100 Gamebucks', 25, int(time.time()) - 10*86400)
    gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))
    print make_virtual_currency_settings_update(SpinConfig.config, gamedata)[2]
