#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinJSON
import time
import base64, hashlib

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

# return the API signature for a given HTTP body
def make_signature(config, body):
    return hashlib.sha1(str(body)+str(config['xsolla_project_key'])).hexdigest()

# return the (url,method,headers,body) for a request to update the Xsolla virtual currency settings for this game.
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

    # currency/price/quantity triplets are redundant from Xsolla's point of view, so only emit one
    by_currency_and_price_and_quantity = {}

    # Xsolla looks up SKUs by currency and price, so we cannot have
    # SKUs at the same currency and price with different Gamebucks quantities!
    by_currency_and_price = {}
    by_currency_and_amount = {}

    # skip SKUs where the "requires" predicate has an A/B test in it
    def skip_predicate(pred, depth = 0):
        if pred['predicate'] == 'AND':
            return any(skip_predicate(p, depth=depth+1) for p in pred['subpredicates'])
        elif pred['predicate'] == 'OR':
            return any(skip_predicate(p, depth=depth+1) for p in pred['subpredicates'])
        elif pred['predicate'] == 'NOT':
            return not skip_predicate(pred['subpredicates'][0], depth=depth+1)
        elif pred['predicate'] == 'ANY_ABTEST' and not pred['key'].endswith('_override'):
            return True
        elif pred['predicate'] == 'ALWAYS_FALSE':
            return True
        return False

    for spellname, data in gamedata['spells'].iteritems():
        if data.get('currency','').startswith('xsolla:'):
            currency = data['currency'].split(':')[1]
            if currency == '*': continue # arbitrary

            # it's really hard to figure out which SKUs to include just by looking at the predicates,
            # so use a hacky method for now...
            if 'D1_' in spellname or 'D3_' in spellname or \
               ('D2_' not in spellname) or \
               'SALE_' in spellname or \
               'P050XY' in spellname:
                # turn off this SKU
                continue

            if 0 and 'requires' in data:
                if skip_predicate(data['requires']):
                    continue

            if currency not in body_json['packets']:
                body_json['packets'][currency] = []

            key3 = (currency, data['price'], data['quantity'])
            if key3 in by_currency_and_price_and_quantity: continue # currency/price/quantity triplet is redundant - skip this

            packet = {'enabled': True,
                      'sku': spellname,
                      'amount': data['quantity'],
                      'price': data['price'],
                      'image_url': '//spinpunch-public.spinpunch.com/facebook_assets/'+gamedata['store']['fb_open_graph_gamebucks_icon'],
                      'description': { 'en': data['ui_name'].replace('%GAMEBUCKS_QUANTITY', '%d' % data['quantity']).replace('%GAME_NAME', gamedata['strings']['game_name']).replace('%GAMEBUCKS_NAME', gamedata['store']['gamebucks_ui_name']).replace('%ITEM_BUNDLE', '') },
                      }
            by_currency_and_price_and_quantity[key3] = packet

            body_json['packets'][currency].append(packet)

            # keep track of any overlap in currency/price point, since Xsolla can't discriminate these
            key2 = (currency, data['price'])
            if key2 in by_currency_and_price:
                other_spellname, other_quantity = by_currency_and_price[key2]
                raise Exception('Xsolla SKU currency/price overlap! %s %s %r %d with %s %r %d from %s\n%r\n\n' % (spellname, currency, data['price'], data['quantity'], currency, data['price'], other_quantity, other_spellname, data['requires']))
            else:
                by_currency_and_price[key2] = spellname, data['quantity']

            key2a = (currency, data['quantity'])
            if key2a in by_currency_and_amount:
                other_spellname, other_price = by_currency_and_amount[key2a]
                raise Exception('Xsolla SKU currency/amount overlap! %s %s %r %d with %s %r %d from %s\n%r\n\n' % (spellname, currency, data['price'], data['quantity'], currency, other_price, data['quantity'], other_spellname, data['requires']))
            else:
                by_currency_and_amount[key2a] = spellname, data['price']

    return 'https://api.xsolla.com/merchant/projects/%s/virtual_currency' % config['xsolla_project_id'], 'PUT', make_headers(config), SpinJSON.dumps(body_json) # this must be an HTTP "PUT" to work


# return the (url,method,headers,body) for a request to generate an Xsolla "token" to start the purchase flow
# @param config - from SpinConfig config.json
def make_token_request(config, game_id, frame_platform,
                       player_id, social_id, user_xs_id, user_email, user_currency, user_currency_price, user_country, user_language,
                       spellname, spellarg,
                       gamebucks_quantity, gamebucks_ui_description,
                       player_level, user_account_creation_time,
                       ):
    is_sandbox = (not config.get('secure_mode', True)) or config.get('xsolla_sandbox_mode', False)
    xsolla_mode = config.get('xsolla_mode', 'virtual_currency')
    assert xsolla_mode in ('virtual_currency', 'simple_checkout')

    body_json = {
        'user': { 'id': { 'value': user_xs_id, 'hidden': True } },
        'settings': { 'project_id': config['xsolla_project_id'],
                      'currency': user_currency },
        'purchase': { 'description': {'value': gamebucks_ui_description } },
        'custom_parameters': { 'user_level': player_level,
                               'spin_game_id': game_id, 'spin_frame_platform': frame_platform, 'spin_player_id': player_id, 'spin_social_id': social_id,
                               'spin_spellname': spellname,
                               'registration_date': unparse_time(user_account_creation_time) }
    }

    if spellarg:
        body_json['custom_parameters']['spin_spellarg'] = SpinJSON.dumps(spellarg)

    if xsolla_mode == 'virtual_currency':
        body_json['purchase']['virtual_currency'] = { 'quantity': gamebucks_quantity }
    elif xsolla_mode == 'simple_checkout':
        body_json['purchase']['checkout'] = {'amount': user_currency_price, 'currency': user_currency}

    if is_sandbox:
        body_json['settings']['mode'] = 'sandbox'
    if user_language:
        assert len(user_language) == 2
        body_json['settings']['language'] = user_language
    if user_country and user_country != 'unknown':
        assert len(user_country) == 2
        body_json['user']['country'] = { 'value': user_country.upper(), 'allow_modify': False } # ?

    if user_email:
        body_json['user']['email'] = { 'value': user_email }

    body_json['user']['name'] = {'value': user_email or ' ' # what to show in the corner of the GUI
                                 }

    return 'https://api.xsolla.com/merchant/merchants/%s/token' % config['xsolla_merchant_id'], 'POST', make_headers(config), SpinJSON.dumps(body_json)

if __name__ == '__main__':
    import SpinConfig
    import getopt, sys

    mode = 'test'
    dry_run = False
    game_id = SpinConfig.game()

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['dry-run','update-slates'])

    for key, val in opts:
        if key == '-g': game_id = val
        elif key == '--dry-run': dry_run = True
        elif key == '--update-slates': mode = 'update-slates'

    if mode == 'test':
        print make_token_request(SpinConfig.config, game_id, 'fb', 1111, 'fb1234', 'xs1234', 'example@example.com',
                                 'USD', 1.00, 'us', 'en',
                                 'BUY_GAMEBUCKS_100_TEST', None,
                                 100, '100 Gamebucks', 25, int(time.time()) - 10*86400)

    elif mode == 'update-slates':
        import requests
        gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename(override_game_id = game_id)))
        url, method, headers, body = make_virtual_currency_settings_update(SpinConfig.config, gamedata)
        if dry_run:
            print 'update:', SpinJSON.dumps(SpinJSON.loads(body), pretty=True)
        else:
            req = getattr(requests, method.lower())(url, headers=headers, data=body)
            print req.status_code, req.text
