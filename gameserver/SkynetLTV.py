#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

from SkynetLib import decode_params, standin_spin_params, spin_targets, bid_coeff
import SpinConfig
import SpinUpcache

######################
# SKYNET LTV ESTIMATOR
# this is an extension on top of SkynetLib that also works with upcache
# NOTE: the following functions operate directly on upcache entries called "user"

# check if user is a member of FACEBOOK VIRTUAL GOOD PURCHASERS AUDIENCES
# if so, return the appropriate 'keyword' targeting value from SkynetLib, otherwise return None
def is_online_spender(user):
    if 'acquisition_ad_skynet' in user:
        source_tgt = decode_params(standin_spin_params, user['acquisition_ad_skynet'], error_on_invalid = False)
        if source_tgt and ('keyword' in source_tgt) and type(source_tgt['keyword']) is list:
            for entry in source_tgt['keyword']:
                if type(entry) is dict:
                    if entry.get('name','unknown').startswith('Online spenders'):
                        return source_tgt['keyword']
    return None

# parse an upcache entry into a Skynet-compatible "tgt", making optional use of post-install behavior
# return None if we can't figure out an appropriate tgt
def upcache_to_tgt(game_id, gamedata, user, time_now, use_post_install_data):
    # make sure accounts have a reasonable creation time
    if time_now - user.get('account_creation_time',time_now) < 1: return None
    tgt = {'game':game_id, 'purpose': 'analytics2'}

    # COUNTRY
    if 'country' not in user: return None
    for value in spin_targets['country']['values']:
        if user['country'] == value['val']:
            tgt['country'] = value['val']
            break
        elif (',' in value['val']) and (user['country'] in value['val'].split(',')):
            tgt['country'] = value['val']
            break
        elif value['val'].startswith('fallback_tier') and SpinConfig.country_tier_map.get(user['country'],4) == int(value['val'][-1]):
            tgt['country'] = value['val']
            break

    if 'country' not in tgt: return None # country not found

    # AGE GROUP
    years_old = -1
    if 'birthday' in user:
        try:
            years_old = SpinUpcache.birthday_to_years_old(user['birthday'], user['account_creation_time'])
        except:
            years_old = -1
    if years_old < 0: # unknown
        tgt['age_range'] = [30,65] # this might overestimate LTV of young players!
    elif years_old < 18:
        tgt['age_range'] = [18,24]
    elif years_old >= 65:
        tgt['age_range'] = [55,64]
    else:
        for value in spin_targets['age_range']['values']:
            if years_old >= value['val'][0] and years_old <= value['val'][1]:
                tgt['age_range'] = value['val']
                break
    if 'age_range' not in tgt: return None

    # FACEBOOK VIRTUAL GOOD PURCHASERS AUDIENCES
    online_spender_keyword = is_online_spender(user)
    if online_spender_keyword:
        tgt['keyword'] = online_spender_keyword

    # scale by CC L3 / CC L2 data, if available
    if use_post_install_data >= 240:
        if time_now - user['account_creation_time'] >= 240*60*60:
            has_cc3 = SpinUpcache.player_history_within(user, gamedata['townhall']+'_level', 3, 10)
            tgt['townhall3_within_10days'] = 1 if has_cc3 else 0
        else:
            return None
    elif use_post_install_data >= 3:
        if time_now - user['account_creation_time'] >= 3*60*60:
            has_cc2 = SpinUpcache.player_history_within(user, gamedata['townhall']+'_level', 2, 0, hours=3)
            tgt['townhall2_within_1day'] = 1 if has_cc2 else 0
        else:
            return None
    elif use_post_install_data > 0:
        if time_now - user['account_creation_time'] >= 2*60*60:
            tgt['tutorial_within_2hrs'] = 1 if user.get('completed_tutorial',False) else 0
        else:
            return None

    return tgt

def ltv_estimate_available(game_id, gamedata, user, time_now, use_post_install_data = None):
    return upcache_to_tgt(game_id, gamedata, user, time_now, use_post_install_data = use_post_install_data) is not None

# actual 90-day LTV estimator. Returns None for no estimate available.
def ltv_estimate(game_id, gamedata, user, time_now, use_post_install_data = None):
    tgt = upcache_to_tgt(game_id, gamedata, user, time_now, use_post_install_data = use_post_install_data)
    if tgt is None: return None
    coeff, install_rate, ui_info = bid_coeff(spin_targets, tgt, base = 1, use_bid_shade = False, use_install_rate = False)
    return coeff
