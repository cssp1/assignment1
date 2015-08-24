#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import sys, os, urllib, getopt, uuid, glob, copy, time, subprocess, datetime, math, re, gzip, hashlib

import SpinJSON, Timezones, SpinConfig, SpinFacebook, FastGzipFile
import pymongo # 3.0+ OK (I think!)

import socket
import SpinS3

from SkynetLib import spin_targets, bid_coeff, \
     encode_one_param, encode_params, decode_params, decode_filter, stgt_to_dtgt, match_params, standin_spin_params, \
     decode_adgroup_name, adgroup_name_is_bad, make_variable_regexp, adgroup_dtgt_filter_query, mongo_enc
from SkynetData import GAMES, TRUE_INSTALLS_PER_CLICK, TRUE_INSTALLS_PER_REPORTED_APP_INSTALL

HTTPLIB = 'requests'
if HTTPLIB == 'requests':
    import requests
else:
    import urllib2, MultipartPostHandler

dry_run = False
verbose = False
quiet = False

# to get this, follow steps under https://developers.facebook.com/docs/reference/ads-api/overview/ under "Provide Authentication"
access_token = SpinConfig.config['facebook_ads_api_access_token']

asset_path = os.path.join(os.getenv('HOME'), 'Dropbox', 'ArtBox', 'skynet')
s3_image_bucket = SpinConfig.config['facebook_ads_images_s3_bucket']
s3_image_path = 'skynet/'

time_now = int(time.time())

MAX_CACHE_AGE = 3600 # lifetime of reachestimate cache
NEW_CAMPAIGN_BUDGET = 2000000 # budget for newly-created campaigns, cents/day

# LOADING CREATIVES

def check_creative_filename(filename):
    assert '.' in filename
    assert len(filename.split('.')) == 2
    fore = filename.split('.')[0]
    assert '_' in fore
    assert len(fore.split('_')) == 2

def encode_filename(name):
    name = os.path.basename(name)
    check_creative_filename(name)
    return name.split('.')[0].split('_')[1]

def get_creatives(asset_path):
    image_files = sorted(glob.glob(os.path.join(asset_path, 'image_*.jpg')))
    title_files = sorted(glob.glob(os.path.join(asset_path, 'title_*.txt')))
    body_files =  sorted(glob.glob(os.path.join(asset_path, 'body_*.txt')))
    return { 'image': {'name':'image', 'key':'x', 'values': [{'val':encode_filename(name), 'coeff':1.0} for name in image_files]},
             'title': {'name':'title', 'key':'y', 'values': [{'val':encode_filename(name), 'coeff':1.0} for name in title_files]},
             'body':  {'name':'body',  'key':'z', 'values': [{'val':encode_filename(name), 'coeff':1.0} for name in body_files]} }

# GENERATING ADS LIST

def generate_combinations(table, campaign, keylist, base = {}):
    if len(keylist) == 0: return [base,]

    campaign_values = campaign[keylist[0]]
    table_data = table[keylist[0]]
    if table_data['values'] == 'LITERAL':
        table_values = 'LITERAL'
    else:
        table_values = [v['val'] if 'val' in v else v['val_match'] for v in table_data['values']]
    if campaign_values == 'ALL':
        assert table_values != 'LITERAL'
        campaign_values = [v['val'] for v in table_data['values'] if v.get('active',1)]

    ret = []
    for val in campaign_values:
        if table_values != 'LITERAL':
            data = None
            for entry in table_data['values']:
                if ('val' in entry and val == entry['val']) or \
                   ('val_match' in entry and re.match(make_variable_regexp(entry['val_match'][0]), val[0])):
                    data = entry
                    break
            if data is None:
                raise Exception('not found: %s:%s in %s' % (keylist[0], val, repr(table_values)))
            # skip inactive items
            if data.get('coeff',1) <= 0: continue
        newbase = copy.copy(base)
        newbase[keylist[0]] = val
        ret += generate_combinations(table, campaign, keylist[1:], newbase)
    return ret

def get_ad_stgt_list(campaign, param_table):
    if len(campaign) < 1: return []
    combos = generate_combinations(param_table, campaign, sorted(campaign.keys()))

    # special case - filter on image dimensions so that we can throw
    # big/small images into a matrix with ad types like [4,32] and
    # automatically get the right combinations.
    to_remove = []
    for c in combos:
        if 'image' in c:
            is_big = c['image'].startswith('big')
            if (c['ad_type'] in (32,432) and (not is_big)) or \
               (c['ad_type'] not in (32,432) and is_big):
                to_remove.append(c)
    for c in to_remove: combos.remove(c)

    ret = map(lambda p: encode_params(param_table, p), combos)
    return ret

# MONGODB INTERFACE

# put our own data fields in a namespace so we don't conflict with Facebook's fields
def spin_field(name): return 'spin_'+name
def is_spin_field(name): return name.startswith('spin_')

# perform field-by-field update (upsert) of a db entry
def update_fields_by_id(coll, item, primary_key = 'id'):
    assert primary_key in item
    coll.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).update_one({'_id':item[primary_key]}, {'$set': item}, upsert = True)
    return item

FB_MAX_TRIES = 10 # number of times to try FB API requests before giving up
FB_RETRY_DELAY = 2 # number of seconds to wait before retrying failed FB API requests
FB_TIMEOUT = 600 # timeout on FB API calls

def _fb_api(*args, **kwargs):
    if HTTPLIB == 'requests':
        return __fb_api_requests(*args, **kwargs)
    else:
        return __fb_api_urllib2(*args, **kwargs)

requests_session = None
def __fb_api_requests(url, url_params, post_params, upload_files, add_access_token = True, read_only = False, ignore_errors = False):
    global requests_session
    if requests_session is None: requests_session = requests.Session()

    if add_access_token:
        if url_params is None: url_params = {}
        url_params['access_token'] = access_token

    attempt = 0
    last_exc = None
    while attempt < FB_MAX_TRIES:
        if attempt > 0:
            time.sleep(FB_RETRY_DELAY)

        try:
            method = 'POST' if post_params or upload_files else 'GET'
            r = None

            if verbose:
                print method, "'"+url+"'",
                if post_params:
                    print ' '.join([" -F '%s=%s'" % (k,v) for k,v in post_params.iteritems()])
                else:
                    print

            if method == 'POST' and dry_run and (not read_only):
                if verbose: print '(dry run, skipping)'
                return False

            r = requests_session.request(method, str(url), params = url_params, data = post_params, files = upload_files, timeout = FB_TIMEOUT)
            if r.status_code != 200:
                last_exc = 'Request status %d: %s' % (r.status_code, r.content if r.content else 'noresponse')
                r.raise_for_status()
            return SpinJSON.loads(r.content)

        except requests.exceptions.RequestException as e:
            print 'RequestException %s: %s' % (repr(e), last_exc)
            attempt += 1

#        except ValueError as e:
#            open('/tmp/skynetfail-head.txt','w').write(repr(r.headers))
#            open('/tmp/skynetfail-body.txt','w').write(r.content)
#            raise

    raise Exception('too many FB API errors, last one was: '+ repr(last_exc))


def __fb_api_urllib2(url, url_params, post_params, upload_files, add_access_token = True, read_only = False, ignore_errors = False):
    opener = None

    if add_access_token:
        url += '?access_token=' + access_token

    if url_params:
        url += '&' + urllib.urlencode(url_params)

    if upload_files:
        for k,v in upload_files.iteritems():
            if post_params is None: post_params = {}
            post_params[k] = v
            opener = urllib2.build_opener(MultipartPostHandler.MultipartPostHandler)

    # see http://bugs.python.org/issue11898
    # http://bugs.python.org/file21747/python-2.7.1-fix-httplib-UnicodeDecodeError.patch
# --- Python-2.7.1/Lib/httplib.py.ark   2011-04-21 15:32:23.765795879 +0200
# +++ Python-2.7.1/Lib/httplib.py       2011-04-21 15:38:15.855787301 +0200
# @@ -792,8 +792,13 @@ class HTTPConnection:
#          # it will avoid performance problems caused by the interaction
#          # between delayed ack and the Nagle algorithim.
#          if isinstance(message_body, str):
# -            msg += message_body
# -            message_body = None
# +            try:
# +                msg += message_body
# +                message_body = None
# +            except UnicodeDecodeError:
# +                # This could be binary data - we can treat it like
# +                # something that isn't a str instance
# +                pass


    url = str(url)

    attempt = 0
    while attempt < FB_MAX_TRIES:
        try:
            method = 'POST' if post_params else 'GET'

            if verbose:
                print method, "'"+url+"'",
                if post_params:
                    #print 'PARAMS', urllib.urlencode(post_params)
                    print ' '.join([" -F '%s=%s'" % (k,v) for k,v in post_params.iteritems()])
                else:
                    print

            if method == 'POST' and dry_run and (not read_only):
                if verbose: print '(dry run, skipping)'
                return False

            if opener:
                conn = opener.open(url, post_params)
            else:
                my_timeout = 600
                conn = urllib2.urlopen(urllib2.Request(url, urllib.urlencode(post_params) if post_params else None), None, my_timeout)

            content_encoding = conn.info().getheader('Content-Encoding', None)
            if content_encoding == 'gzip':
                buf = gzip.GzipFile(fileobj=conn).read()
            else:
                buf = conn.read()

            result = SpinJSON.loads(buf)

        except urllib2.URLError as e:
            print 'urllib2.URLError with reason %s %s' % (repr(type(e.reason)), repr(e.reason))
            attempt += 1
            if attempt >= FB_MAX_TRIES:
                raise
            else:
                time.sleep(FB_RETRY_DELAY)
                continue
        except urllib2.HTTPError as e:
            print "HTTP ERROR", e.code, e.read()
            attempt += 1
            if attempt >= FB_MAX_TRIES:
                raise
            else:
                time.sleep(FB_RETRY_DELAY)
                continue
        except ValueError as e:
            open('/tmp/skynetfail-head.txt','w').write(repr(conn.info().headers))
            open('/tmp/skynetfail-body.txt','w').write(buf)
            raise
        break

    return result

def _fb_api_paged(url, url_params, post_params, dict_paging, ignore_errors = False):
    count = 0
    add_access_token = True # only necessary on first pass
    while True:
        result = _fb_api(url, url_params, post_params, None, add_access_token = add_access_token, ignore_errors = ignore_errors)

        if dict_paging:
            my_iter = result['data'].itervalues()
        else:
            my_iter = result['data']
        for item in my_iter:
            yield item
            count += 1

        if ('paging' in result) and ('next' in result['paging']):
            # somehow the JSON encoding of [] gets screwed up in the "next" URL, so use cursor "after" instead
            if ('cursors' in result['paging']) and ('after' in result['paging']['cursors']):
                url_params = url_params.copy()
                url_params['after'] = result['paging']['cursors']['after']
            else:
                url = result['paging']['next']
                url_params = None
                post_params = None
                add_access_token = False
        else:
            break

def fb_api(url, url_params = None, post_params = None, upload_files = None, is_paged = False, dict_paging = False, read_only = False, ignore_errors = False):
    if is_paged:
        return _fb_api_paged(url, url_params, post_params, dict_paging, ignore_errors = ignore_errors)
    else:
        return _fb_api(url, url_params, post_params, upload_files, read_only = read_only, ignore_errors = ignore_errors)

def _fb_api_batch(base_url, batch, read_only = False, ignore_errors = False):
    ret = [False]*len(batch)
    if dry_run and (not read_only): return ret

    # loop up to FB_MAX_TRIES times, retrying any requests that fail

    attempt = 0
    while attempt < FB_MAX_TRIES:
        indices = []
        this_batch = []
        for i in xrange(len(batch)):
            if ret[i] is False:
                this_batch.append(batch[i])
                indices.append(i)

        result = fb_api(base_url, post_params = {'batch': SpinJSON.dumps(this_batch)}, read_only = read_only, ignore_errors = False)
        this_error = None
        for j in xrange(len(this_batch)):
            r = result[j]
            if r and r['code'] == 200:
                # good result
                ret[indices[j]] = SpinJSON.loads(r['body'])
            else:
                # error
                this_error = "HTTP ERROR: %d %s" % (r['code'] if r else -1, r['body'] if r else 'empty')
                print this_error
        if this_error:
            attempt += 1
            if attempt >= FB_MAX_TRIES:
                pass # will trigger exception below
            else:
                time.sleep(FB_RETRY_DELAY)
                continue
        break

    if attempt >= FB_MAX_TRIES and (not ignore_errors):
        raise Exception('fb_api_batch: too many errors even after %d attempts' % FB_MAX_TRIES)

    if (not ignore_errors):
        for item in ret: assert item

    return ret

def fb_api_batch(base_url, batch, limit = 50, read_only = False, ignore_errors = False):
    assert limit <= 50 # facebook limits batches to 50
    if batch:
        batches = [batch[i:i+limit] for i in xrange(0, len(batch), limit)]
        for this_batch in batches:
            for r in _fb_api_batch(base_url, this_batch, read_only = read_only, ignore_errors = ignore_errors):
                yield r

# FACEBOOK INTERFACE

# fields we want to read back from the FB API on customaudiences objects
CUSTOM_AUDIENCE_FIELDS='id,account_id,approximate_count,data_source,delivery_status,lookalike_audience_ids,lookalike_spec,name,permission_for_actions,operation_status,time_updated,subtype'

def custom_audiences_pull(db, ad_account_id):
    db.fb_custom_audiences.create_index('name')
    for x in fb_api(SpinFacebook.versioned_graph_endpoint('customaudience', 'act_'+ad_account_id+'/customaudiences') + '?fields=' + CUSTOM_AUDIENCE_FIELDS,
                    is_paged = False)['data']: # doesn't seem to be paged
        if 'account_id' in x: x['account_id'] = str(x['account_id']) # FB sometimes returns these as numbers :P
        update_fields_by_id(db.fb_custom_audiences, mongo_enc(x))

def _custom_audience_create(db, ad_account_id, props):
    result = fb_api(SpinFacebook.versioned_graph_endpoint('customaudience', 'act_'+ad_account_id+'/customaudiences'), post_params = props)
    if result:
        # have to ask for all properties
        x = fb_api(SpinFacebook.versioned_graph_endpoint('customaudience', str(result['id'])) + '?fields=' + CUSTOM_AUDIENCE_FIELDS)
        if 'account_id' in x: x['account_id'] = str(x['account_id']) # FB sometimes returns these as numbers :P
        update_fields_by_id(db.fb_custom_audiences, mongo_enc(x))
        return result['id']
    else:
        return None

def custom_audience_create(db, ad_account_id, name, description = None):
    props = {'name': name}
    if description: props['description'] = description
    return _custom_audience_create(db, ad_account_id, props)

def lookalike_audience_create(db, ad_account_id, name, origin_audience_name, country, lookalike_type = 'similarity', lookalike_ratio = None, description = None):
    spec = {'country': country.upper()}
    if lookalike_ratio is not None:
        spec['ratio'] = lookalike_ratio
    else:
        spec['type'] = lookalike_type
    origin_audience_qs = {'name': origin_audience_name, 'account_id': str(ad_account_id)}
    origin_audience = db.fb_custom_audiences.find_one(origin_audience_qs, {'id':1})
    if not origin_audience:
        raise Exception('origin audience not found: '+repr(origin_audience_qs))

    props = {'name': name, 'origin_audience_id': origin_audience['id'],
             'lookalike_spec':SpinJSON.dumps(spec)}
    if description: props['description'] = description
    return _custom_audience_create(db, ad_account_id, props)

def _custom_audience_add(audience_id, app_id_facebook_id_list):
    app_id_list = list(set(x[0] for x in app_id_facebook_id_list))
    result = fb_api(SpinFacebook.versioned_graph_endpoint('customaudience', audience_id+'/users'),
                    post_params = {'payload': SpinJSON.dumps({'schema':'UID', 'data': [x[1] for x in app_id_facebook_id_list], 'app_ids': app_id_list})})
    print 'transmitted', result['num_received'], 'of which', result['num_invalid_entries'], 'were invalid'
    if verbose:
        print result
    return result['num_received']

def custom_audience_add(audience_id, app_id_facebook_id_list):
    limit = 5000 # 5000 with new /payload API
    added = 0
    batch = []
    for app_fb_id in app_id_facebook_id_list:
        batch.append(app_fb_id)
        if len(batch) >= limit:
            added += _custom_audience_add(audience_id, batch)
            batch = []
    if batch:
        added += _custom_audience_add(audience_id, batch)
    return added

ADGROUP_FIELDS = 'name,campaign_id,created_time,failed_delivery_checks,adgroup_status,bid_type,bid_info'
def adgroup_add_skynet_fields(x):
    stgt, tgt = decode_adgroup_name(standin_spin_params, x['name'])
    if stgt is not None:
        x[spin_field('stgt')] = stgt
        x[spin_field('dtgt')] = stgt_to_dtgt(stgt)
    return x

def adgroups_pull(db, campaign_id_list = None, ad_account_id = None, match_status = None):
    query = {'fields': ADGROUP_FIELDS}
    if match_status:
        assert type(match_status) is list
        query['adgroup_status'] = SpinJSON.dumps(map(adgroup_encode_status, match_status))

    if campaign_id_list is not None:
         by_campaign = [[update_fields_by_id(db.fb_adgroups, mongo_enc(adgroup_add_skynet_fields(x))) for x in \
                         fb_api(SpinFacebook.versioned_graph_endpoint('adgroup', id+'/adgroups'),
                                url_params = query,
                                is_paged=True)] for id in campaign_id_list]
         return sum(by_campaign, []) # return raw list of ads
    else:
        assert ad_account_id
        return [update_fields_by_id(db.fb_adgroups, mongo_enc(adgroup_add_skynet_fields(x))) for x in \
                fb_api(SpinFacebook.versioned_graph_endpoint('adgroup', 'act_'+ad_account_id+'/adgroups'), url_params = query, is_paged = True)]

def adgroup_decode_status(adgroup):
    STATUS = {
        0: 'pending',
        1: 'active',
        2: 'paused',
        3: 'deleted',
        4: 'pending_review',
        5: 'disapproved',
        6: 'preapproved',
        7: 'pending_billing_info',
        8: 'campaign_paused',
        9: 'adgroup_paused',
        10: 'campaign_group_paused'
        }
    s = adgroup.get('adgroup_status', adgroup.get('ad_status','UNKNOWN'))
    if type(s) is int:
        return STATUS[s].lower()
    else:
        return s.lower()
def adgroup_encode_status(s): return s.upper()

def adgroup_update_status_batch_element(adgroup, new_status = None, new_name = None):
    props = {}
    if new_status: props['adgroup_status'] = adgroup_encode_status(new_status)
    if new_name: props['name'] = new_name
    return (adgroup['id'], props)
def adgroup_update_status_batch(db, arglist):
    for arg, result in zip(arglist,
                           fb_api_batch(SpinFacebook.versioned_graph_endpoint('adgroup', ''),
                                        [{'method':'POST', 'relative_url': str(adgroup_id),
                                          'body': urllib.urlencode(new_props)} for adgroup_id, new_props in arglist])):
        adgroup_id, new_props = arg
        if result:
            db.fb_adgroups.update_one({'_id':adgroup_id}, {'$set': new_props}, upsert = False)

def adgroup_update_status(db, adgroup, *args, **kwargs):
    adgroup_update_status_batch(db, [adgroup_update_status_batch_element(adgroup, *args, **kwargs)])

BID_INFO_CODES = {
    'ACTION': 55, 'REACH': 44, 'CLICK': 1
}
BID_TYPE_CODES = {
    #'CPC': 1, 'CPM': 2, 'CPA': 9, 'oCPM': 7, 'ABSOLUTE_OCPM': 7,
    # Oct 2 breaking change
    'CPC': 'CPC', 'CPM': 'CPM', 'CPA': 'CPA', 'oCPM': 'ABSOLUTE_OCPM'
}
# comparison of bid types, taking into account how Facebook sometimes returns strings, ints, or enums
def bid_type_equals(t, c): return str(t).upper() in (BID_TYPE_CODES[c], str(BID_TYPE_CODES[c]), c)
def decode_bid_type(c):
    c = c.upper()
    if c == 'ABSOLUTE_OCPM':
        return 'oCPM'
    elif c in BID_TYPE_CODES:
        return c
    else:
        raise Exception('unknown bid type code '+repr(c))
def encode_bid_type(t):
    return 'ABSOLUTE_OCPM' if t.startswith('oCPM') else BID_TYPE_CODES[t]

def adgroup_get_bid(adgroup):
    if ('max_bid' in adgroup) and (bid_type_equals(adgroup['bid_type'], 'CPC') or bid_type_equals(adgroup['bid_type'], 'CPM')):
        ret = adgroup['max_bid']
    else:
        # API is really inconsistent with how it returns these
        ret = max(adgroup['bid_info'].get("clicks",0), adgroup['bid_info'].get("CLICKS",0), adgroup['bid_info'].get(str(BID_INFO_CODES['CLICK']),0),
                  adgroup['bid_info'].get("impressions",0), adgroup['bid_info'].get("IMPRESSIONS",0),
                  adgroup['bid_info'].get("actions",0), adgroup['bid_info'].get("ACTIONS",0), adgroup['bid_info'].get(str(BID_INFO_CODES['ACTION']),0))
    return ret
def adgroup_set_bid(adgroup, new_bid, o_bid_type = None):
    if o_bid_type:
        return {'bid_info':{o_bid_type:new_bid}}
    elif bid_type_equals(adgroup['bid_type'], 'CPC'):
        return {'bid_info':{'CLICKS':new_bid}}
    elif bid_type_equals(adgroup['bid_type'], 'CPM'):
#        return {'max_bid': new_bid}
        return {'bid_info':{'IMPRESSIONS':new_bid}}
    else:
        # auto-detect whether we are bidding for clicks or actions
        assert 'bid_info' in adgroup
        if max(adgroup['bid_info'].get("actions",0),adgroup['bid_info'].get("ACTIONS",0),adgroup['bid_info'].get(str(BID_INFO_CODES['ACTION']),0)) > \
           max(adgroup['bid_info'].get("clicks",0),adgroup['bid_info'].get("CLICKS",0),adgroup['bid_info'].get(str(BID_INFO_CODES['CLICK']),0)):
            o_bid_type = 'ACTIONS'
        else:
            o_bid_type = 'CLICKS'

#        return {'bid_info':{str(BID_INFO_CODES[o_bid_type]):new_bid}}
        return {'bid_info':{o_bid_type:new_bid}}

def adgroup_encode_bid(bid_type, bid, app_id, conversion_pixels):
    ret = {}
    if bid_type == 'CPA' or bid_type.startswith('oCPM'):
        if bid_type == 'CPA' or bid_type == 'oCPM_INSTALL':
            ret['conversion_specs'] = SpinJSON.dumps([{"action.type":["app_install"],"application":app_id}])
            o_bid_type = 'ACTIONS'
        elif bid_type == 'oCPM_CLICK':
            o_bid_type = 'CLICKS'
        else:
            o_bid_type = 'ACTIONS'
            event = '_'.join(bid_type.split('_')[1:])
            assert event in conversion_pixels
            ret['conversion_specs'] = SpinJSON.dumps([{"action.type":'offsite_conversion','offsite_pixel':int(conversion_pixels[event]['id'])}])
    elif bid_type == 'CPC':
        o_bid_type = 'CLICKS'
    elif bid_type == 'CPM':
        o_bid_type = 'IMPRESSIONS'
    else:
        raise Exception('unhandled bid_type '+bid_type)

    bid_dic = adgroup_set_bid(ret, bid, o_bid_type = o_bid_type)
    if 'max_bid' in bid_dic:
        ret['max_bid'] = bid_dic['max_bid']
    else:
        ret['bid_info'] = SpinJSON.dumps(bid_dic['bid_info'])
    return ret

def adcampaign_update_bid(db, adcampaign, new_bid):
    if not fb_api(SpinFacebook.versioned_graph_endpoint('adcampaign', adcampaign['id']),
                  post_params = {'bid_info': SpinJSON.dumps(adgroup_set_bid(adcampaign, new_bid)['bid_info'])}):
        return False
    db.fb_adcampaigns.update_one({'_id':adcampaign['id']}, {'$set': adgroup_set_bid(adcampaign, new_bid)}, upsert = False)
    return True

def adgroup_update_bid(db, adgroup, new_bid):
    if not fb_api(SpinFacebook.versioned_graph_endpoint('adgroup', adgroup['id']), post_params = adgroup_set_bid(adgroup, new_bid)):
        return False
    db.fb_adgroups.update_one({'_id':adgroup['id']}, {'$set': adgroup_set_bid(adgroup, new_bid)}, upsert = False)
    return True
def adgroup_update_bid_batch_send(adgroup, new_bid):
    return {'method': 'POST', 'relative_url': adgroup['id'], 'body': urllib.urlencode(adgroup_set_bid(adgroup, new_bid))}
def adgroup_update_bid_batch_receive(db, adgroup, new_bid, result):
    if result:
        db.fb_adgroups.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).update_one({'_id':adgroup['id']}, {'$set': adgroup_set_bid(adgroup, new_bid)}, upsert = False)
    return result

# format of bid_updates is [(adgroup0, bid0), (adgroup1, bid1), ...]
def adgroup_update_bid_batch(db, bid_updates):
    for upd, result in zip(bid_updates, fb_api_batch(SpinFacebook.versioned_graph_endpoint('adgroup', ''),
                                                     [adgroup_update_bid_batch_send(x[0], x[1]) for x in bid_updates])):
        adgroup, new_bid = upd
        old_bid = adgroup_get_bid(adgroup)
        success = adgroup_update_bid_batch_receive(db, adgroup, new_bid, result)
        new_bid_col = ANSIColor.red(str(new_bid)) if new_bid > old_bid else ANSIColor.green(str(new_bid))
        print '%-80s' % adgroup['name'], 'bid', 'updated' if success else 'NOT updated', old_bid, '->', new_bid_col

def pretty_cents(cents):
    sign = '-' if cents < 0 else ''
    return sign+'$%.2f' % (0.01*abs(cents))

# numeric counters inside adstats that we care about
ADSTATS_COUNTERS = ['spend', 'spent', 'frequency',
                    'clicks', 'unique_clicks', 'impressions', 'unique_impressions', 'reach',
                    'social_clicks', 'unique_social_clicks', 'social_impressions', 'unique_social_impressions', 'social_reach']
ADSTATS_DATA_FIELDS = ['relevance_score', 'actions'] # JSON object fields from adstats we want to store

# actual query of Facebook API for adstats
def _adstats_pull(db, adgroup_list, time_range = None):
    results = []
    do_store = (time_range is None) # don't store time-ranged results

    if time_range:
        # really awkward - API only lets you get daily stats in the advertiser's time zone!
        def chop_to_date(unix): return time.strftime('%Y-%m-%d', time.gmtime(unix))

        query = '?'+urllib.urlencode({'time_range': {'since': chop_to_date(time_range[0] + utc_pacific_offset(time_range[0])),
                                                     # FB API is inclusive of last day, so subtract one day
                                                     'until': chop_to_date(time_range[1] - 86400 + utc_pacific_offset(time_range[1]-86400))}})
    else:
        query = ''

    for adgroup, x in zip(adgroup_list,
                          fb_api_batch(SpinFacebook.versioned_graph_endpoint('adinsights', ''),
                                       [{'method':'GET', 'relative_url':adgroup['id']+'/insights'+query}
                                        for adgroup in adgroup_list], read_only = True)):
        if not x['data']:
            # this means the ad had no delivery
            results.append(None)
            continue

        x = x['data'][0]
        # make sure we got data for the right ad
        assert str(x['adgroup_id']) == str(adgroup['id'])

        if time_range:
            # make sure we got the right time range
            parsed_start_time = SpinFacebook.parse_fb_date(x['date_start'], utc_pacific_offset(time_range[0]))
            parsed_end_time = SpinFacebook.parse_fb_date(x['date_stop'], utc_pacific_offset(time_range[1])) + 86400

            if parsed_start_time != time_range[0] or \
               parsed_end_time != time_range[1]:
                raise Exception('asked for time_range %r %r %r but got %r (parsed %r %r %r %r)' % \
                                (time_range, SpinFacebook.unparse_fb_time(time_range[0]), SpinFacebook.unparse_fb_time(time_range[1]),
                                 x['adgroup_id'], parsed_start_time, parsed_end_time, x['date_start'], x['date_stop']))

        # Old API returned "spent" cents, new API returns "spend" dollars - convert back to cents
        if 'spend' in x:
            assert 'spent' not in x
            x['spent'] = int(100*x['spend']+0.5)
        elif 'spent' in x:
            assert 'spend' not in x

        # sometimes Facebook returns numeric fields as a string :P
        for FIELD in ADSTATS_COUNTERS:
            if FIELD in x and type(x[FIELD]) in (str, unicode):
                x[FIELD] = float(x[FIELD]) if '.' in x[FIELD] else int(x[FIELD])

        x[spin_field('adgroup_id')] = adgroup['id']
        x[spin_field('adgroup_name')] = adgroup['name'] # denormalize for quick queries

        if do_store and (not dry_run):
            # store in current adstats table
            update_fields_by_id(db.fb_adstats, mongo_enc(x), primary_key = spin_field('adgroup_id'))

            # record time series in at_time table
            x['time'] = time_range[1]
            x['_id'] = x['id']
            db.fb_adstats_at_time.update_one({'_id':x['_id']}, mongo_enc(x), upsert=True)

        results.append(x)

    if verbose:
        print "_adstats_pull:", results

    return results

# memoized version of adstats_pull, since we often query the same adgroups many times when doing analysis
ADSTATS_MEMO_LIFETIME = 900 # 15 minutes only
def adstat_memo_key(id, time_range):
    return str(id) + '_' + (('%d_%d' % tuple(time_range)) if time_range else 'NOW')
def adstats_pull(db, adgroup_list, time_range = None):
    results = []
    query = []
    query_indices = []
    for i in xrange(len(adgroup_list)):
        adgroup = adgroup_list[i]
        cached = db.fb_adstats_memo.find_one({'_id':adstat_memo_key(adgroup['id'], time_range)})
        if cached:
            results.append(cached)
        else:
            results.append(None)
            query.append(adgroup)
            query_indices.append(i)

    if query:
        fetch_time = datetime.datetime.utcnow()
        db.fb_adstats_memo.create_index(spin_field('fetch_time'), expireAfterSeconds=ADSTATS_MEMO_LIFETIME)
        uncached = _adstats_pull(db, query, time_range = time_range)
        for q in xrange(len(query)):
            if uncached[q]:
                stat = mongo_enc(uncached[q])
            else:
                # no data, make a blank entry
                # XXX probably better to teach downstream code how to handle missing data
                stat = {spin_field('adgroup_id'): query[q]['id']}
                for COUNTER in ADSTATS_COUNTERS:
                    stat[COUNTER] = 0
            stat[spin_field('fetch_time')] = fetch_time
            stat['_id'] = adstat_memo_key(query[q]['id'], time_range)
            db.fb_adstats_memo.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).replace_one({'_id':stat['_id']}, stat, upsert=True)
            results[query_indices[q]] = stat
    return results

# same as adstats_pull, but return the result in a form of a dict mapping from adgroup_id to stats
def adstats_pull_dict(*args, **kwargs):
    return dict([(x[spin_field('adgroup_id')], x) for x in adstats_pull(*args, **kwargs)])

# Facebook change as of 2015 Feb 9 - they only return daily data now
# we have legacy data left over in the fb_adstats_hourly table, but will only update
# fb_adstats_daily going forward.
ADSTATS_PERIOD = 'day'
def adstats_record_table(db):
    if ADSTATS_PERIOD == 'hour':
        return db.fb_adstats_hourly
    else:
        return db.fb_adstats_daily

def adstats_quantize_time(t, round_up = False):
    if ADSTATS_PERIOD == 'hour':
        if round_up: t += 3600 - 1
        return 3600*(t//3600)
    elif ADSTATS_PERIOD == 'day':
        if round_up: t += 86400 - 1
        offs = utc_pacific_offset(t)
        return 86400*((t+offs)//86400)-offs

def adstats_record_verify_time_range(table, time_range, allow_multi_period = False):
    if ADSTATS_PERIOD == 'hour':
        for r in time_range:
            if r % 3600 != 0: return False
        delta = time_range[1] - time_range[0]
        if allow_multi_period: delta = delta % 3600 + 3600
        if delta != 3600:
            return False
    elif ADSTATS_PERIOD == 'day':
        delta = time_range[1] - time_range[0]
        if allow_multi_period: delta = delta % 86400 + 86400
        if delta not in (86400, 86400-3600, 86400+3600): # allow daylight savings time
            return False
        for r in time_range:
            ts = time.gmtime(pacific_to_utc(r))
            # must be Pacific time midnight
            if ts.tm_hour != 0 or ts.tm_min != 0 or ts.tm_sec != 0:
                return False
    return True

def adstats_record(db, adgroup_list, time_range):
    table = adstats_record_table(db)
    table.create_index([('adgroup_id',pymongo.ASCENDING),('start_time',pymongo.ASCENDING)])
    table.create_index([('start_time',pymongo.ASCENDING)])

    assert adstats_record_verify_time_range(table, time_range, allow_multi_period = False)

    pull_time_range = time_range

    # use uncached version
    stats = _adstats_pull(db, adgroup_list, time_range = pull_time_range)
    totals = {'spent': 0, 'impressions': 0, 'clicks': 0}
    count = 0
    for adgroup, stat in zip(adgroup_list, stats):
        if not stat: continue

        if 'created_time' not in adgroup:
            if not quiet:
                print 'missing created_time on adgroup', adgroup['id']
            adgroup['created_time'] = SpinFacebook.unparse_fb_time(time_now - 7*24*60*60)

        stgt, tgt = decode_adgroup_name(standin_spin_params, adgroup['name'])
        if not stgt:
            print 'unparseable adgroup name, skipping: "%s"' % adgroup['name']
            continue

        obj = {'_id': adstat_memo_key(adgroup['id'], time_range),
               'start_time':time_range[0], 'end_time':time_range[1],
               'adgroup_id': str(adgroup['id']),
               # deliberately denormalize name, dtgt, campaign_id, and created_time into here so we can pull historical stats without relying on the source adgroups still being in the database
               'adgroup_name': adgroup['name'], 'dtgt': stgt_to_dtgt(stgt), 'campaign_id': str(stat['campaign_id']), 'created_time': adgroup['created_time'],
               'adgroup_status': adgroup_decode_status(adgroup), 'bid': adgroup_get_bid(adgroup), 'bid_type': decode_bid_type(adgroup['bid_type']),
               'raw_bid_type': adgroup['bid_type'], 'raw_bid_info': adgroup['bid_info'] # might be unnecessary
               }

        # copy the adstat counters and fields we want to store
        for FIELD in ADSTATS_COUNTERS:
            if FIELD in stat:
                if type(stat[FIELD]) in (str, unicode):
                    obj[FIELD] = float(stat[FIELD]) if '.' in stat[FIELD] else int(stat[FIELD])
                else:
                    assert type(stat[FIELD]) in (int, long, float)
                    obj[FIELD] = stat[FIELD]
            if FIELD in totals:
                totals[FIELD] += obj[FIELD]

        for FIELD in ADSTATS_DATA_FIELDS:
            if FIELD in stat:
                obj[FIELD] = stat[FIELD]

        if obj['spent']+obj['impressions']+obj['clicks'] < 1: continue # don't record empty stats

        if verbose:
            print "STAT", stat
            print "RECORD", obj

        if not dry_run:
            table.replace_one({'_id':obj['_id']}, obj, upsert=True)
        count += 1

    if verbose:
        print "TOTALS", totals

    return count

# get list of adgroups that had some activity during time_range
def adstats_record_get_live_adgroups(db, match_qs, time_range):
    default_created_time = SpinFacebook.unparse_fb_time(time_range[0])
    default_name = 'BAD - unknown'

    if not adstats_record_verify_time_range(adstats_record_table(db), time_range, allow_multi_period = True):
        if not quiet: print 'warning: time range is not aligned to local time:', time_range

    match_qs['start_time'] = {'$lt':time_range[1]}
    match_qs['end_time'] = {'$gt':time_range[0]}

    result = [{'id': str(row['_id']), 'name': row['adgroup_name'] or default_name, 'created_time': row['created_time'] or default_created_time} for row in \
              adstats_record_table(db).aggregate([
        {'$match':match_qs},
        {'$group':{'_id':'$adgroup_id', 'adgroup_name':{'$last':'$adgroup_name'}, 'created_time':{'$max':'$created_time'}}}
        ])]

    if 0:
        # fix old entries that have missing denormalized fields (high # of API calls!)
        to_fix = []
        for entry in result:
            if entry['name'] == default_name:
                to_fix.append(entry)
        if to_fix:
            if not quiet: print 'fixing', len(to_fix), 'old adstats_hourly entries'
            for adgroup in fb_api_batch(SpinFacebook.versioned_graph_endpoint('adgroup', ''),
                                        [{'method':'GET', 'relative_url': fix['id']+'?'+urllib.urlencode({'fields':ADGROUP_FIELDS})} for fix in to_fix]):
                if adgroup:
                    qs = {'adgroup_id': str(adgroup['id'])}
                    stgt, tgt = decode_adgroup_name(standin_spin_params, adgroup['name'])
                    if stgt and (not adgroup_name_is_bad(adgroup['name'])):
                        qs_set = {'$set': {'adgroup_name': adgroup['name'], 'dtgt': stgt_to_dtgt(stgt), 'campaign_id': str(adgroup['campaign_id']), 'created_time': adgroup['created_time']}}
                        if not dry_run:
                            adstats_record_table(db).with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).update_many(qs, qs_set, upsert=False)
                    else:
                        if not quiet: print 'dropping stats for unknown adgroup named "%s"' % adgroup['name']
                        if 1:
                            adstats_record_table(db).with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).delete_many(qs)

    return result

def adstats_record_pull_dict(db, adgroup_list, time_range = None):
    if not adstats_record_verify_time_range(adstats_record_table(db), time_range, allow_multi_period = True):
        raise Exception('error: time range is not aligned to local time: %r' % time_range)

    # initialize with empty stats
    ret = dict([(str(adgroup['id']), {'spent':0,'impressions':0,'clicks':0}) for adgroup in adgroup_list])

    query = [{'$match':{'adgroup_id':{'$in':ret.keys()},
                        'start_time':{'$lt':time_range[1]},
                        'end_time':{'$gt':time_range[0]}}},
             {'$project':{'adgroup_id':1,'spent':1,'clicks':1,'impressions':1,'start_time':1,'end_time':1}},
             {'$group':{'_id':'$adgroup_id',
                        'spent':{'$sum':'$spent'},
                        'impressions':{'$sum':'$impressions'},
                        'clicks':{'$sum':'$clicks'},
                        'samples':{'$sum':1},
                        'min_start':{'$min':'$start_time'},
                        'max_end':{'$max':'$end_time'},
                        }}]
    if verbose: print 'adstat record query:', query

    results = adstats_record_table(db).aggregate(query)
    #if verbose: print "GOT", results
    for row in results:
        ret[row['_id']] = row
    return ret

def _query_analytics2(game_id, query_string):
    env = os.environ.copy()
    env['QUERY_STRING'] = query_string
    proc = subprocess.Popen(['./cgianalytics.py', '-g', game_id], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdoutdata, stderrdata = proc.communicate()
    if proc.returncode != 0:
        raise Exception('%s failed: %s\n' % (env['QUERY_STRING'],stderrdata))
    # skip MIME header
    stdoutdata = stdoutdata.split('\n')[4]
    return stdoutdata

ANALYTICS2_MEMO_LIFETIME = 600
def abbreviate_key(k): return hashlib.md5(k).hexdigest()

def query_analytics2(game_id, spin_params, stgt_filter, group_by, groups, time_sample, campaign_code = None):
    params = {'game_id': game_id, 'output_mode': 'funnel', 'funnel_stages': 'skynet'}
    if campaign_code: params['acquisition_campaign'] = campaign_code
    if stgt_filter: params['acquisition_ad_skynet2'] = stgt_filter
    if group_by:
        params['overlay_mode'] = 'acquisition_ad_skynet'
        params['acquisition_ad_skynet'] = ','.join(sorted([encode_params(spin_params, group['group_tgt']) for group in groups.itervalues()]))
    if 'start' in time_sample:
        params['account_creation_min'] = time_sample['start']
        params['account_creation_max'] = time_sample['end']
    query_string = urllib.urlencode([(k,v) for k,v in sorted(params.items())])

    if verbose:
        print 'analytics2 query:', query_string,
        sys.stdout.flush()

    ret = None

    cached = db.analytics2_memo.find_one({'_id': abbreviate_key(query_string), 'key': query_string})
    if cached:
        if verbose: print '(cached)'
        ret = cached['output']
    else:
        uncached = _query_analytics2(game_id, query_string)
        entry = {'_id': abbreviate_key(query_string), 'key': query_string, 'fetch_time': datetime.datetime.utcnow(), 'output': uncached}
        db.analytics2_memo.create_index('fetch_time', expireAfterSeconds = ANALYTICS2_MEMO_LIFETIME)
        db.analytics2_memo.replace_one({'_id':entry['_id']}, entry, upsert=True)
        ret = uncached
        if verbose: print

    return SpinJSON.loads(ret)

def parse_group_by_params(spin_params, group_by):
    group_params = []
    for data in spin_params.itervalues():
        if data['key'] in group_by.split('_'):
            group_params.append(data)
    assert len(group_params) == len(group_by.split('_'))
    return group_params

# note! assumes that db.fb_adgroups is up to date!
def adstats_analyze(db, min_clicks = 0, stgt_filter = None, group_by = None,
                    use_analytics = None, use_regexp_ltv = False, use_record = None, tactical = None,
                    time_range = None, output_format = None, output_frequency = 'ALL'):
    assert tactical in (None, 'plan', 'execute')
    if tactical: assert output_frequency == 'ALL'

    spin_params = standin_spin_params
    tgt_filter = decode_filter(spin_params, stgt_filter) if stgt_filter else None
    if group_by and group_by != 'ALL':
        group_params = parse_group_by_params(spin_params, group_by)
    else:
        group_params = []

    get_installs_from = 'clicks' # or 'app_installs'

    if use_record and (not tactical):
        # could make this more efficient by incorporating adgroup_query and filtering on dtgt
        adgroup_list = adstats_record_get_live_adgroups(db, adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter)) if stgt_filter else {}, time_range)
    else:
        adgroup_query = {'adgroup_status': {'$ne':'DELETED'}}
        if stgt_filter: # optimize adgroup query to only match tgt_filter
            adgroup_query.update(adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter), dtgt_key = spin_field('dtgt')))
        if verbose: print "ADGROUP QUERY:", adgroup_query
        adgroup_list = list(db.fb_adgroups.find(adgroup_query))

    adgroup_list.sort(key = lambda x: x['name'])

    if verbose: print "POTENTIAL:", len(adgroup_list), "ads"

    # filter out "mistake" ads that were renamed manually
    adgroup_list = filter(lambda x: (not adgroup_name_is_bad(x['name'])) and (decode_adgroup_name(spin_params, x['name'])[1] is not None), adgroup_list)

    #if not quiet: print "NONBAD:", len(adgroup_list), "ads"

    # pre-filter ads that don't match tgt_filter so we don't waste time querying their stats
    if tgt_filter:
        adgroup_list = filter(lambda x: match_params(decode_adgroup_name(spin_params, x['name'])[1], tgt_filter), adgroup_list)

    if len(adgroup_list) < 1:
        print 'no ads to process'
        return

    #if not quiet: print "FILTERED:", len(adgroup_list), "ads"

    if tactical:
        # get all tactical bid shades
        #if not quiet: print 'loading tactical bid shades from database...',
        tactical_query = {}
        if stgt_filter:
            tactical_query.update(adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter), dtgt_key = 'dtgt'))
        tactical_bid_shades_by_adgroup_id = dict((row['_id'], {'bid_shade': math.exp(row['log_bid_shade']), 'mtime':row.get('mtime',-1)}) for row in db.tactical.find(tactical_query, {'log_bid_shade':1, 'mtime':1}))

    # get dictionary of adstats by sample time and adgroup ID
    adstats = {}
    time_samples = []
    adstats_pull_func = adstats_record_pull_dict if use_record else adstats_pull_dict

    if time_range:
        # query for time-range stats
        if output_frequency == 'ALL':
            samp = {'ui_name':'', 'start': time_range[0], 'end': time_range[1]}
            adstats[samp['ui_name']] = adstats_pull_func(db, adgroup_list, time_range = time_range)
            time_samples.append(samp)
        elif output_frequency == 'day':
            for t in xrange(time_range[0], time_range[1], 86400):
                y, m, d = SpinConfig.unix_to_cal(t) # XXX should there be a timezone conversion here?
                samp = {'ui_name':'%d/%d/%d' % (m,d,y),
                        'start': t, 'end': t+86400}
                time_samples.append(samp)
                #print "QUERY", samp
                adstats[samp['ui_name']] = adstats_pull_func(db, adgroup_list, time_range = [samp['start'],samp['end']])

    else: # use cached current stats
        samp = {'ui_name':'NOW'}
        # note - entries may be None if no cached results are found
        adstats[samp['ui_name']] = dict([(adgroup['id'], db.fb_adstats.find_one({'_id':adgroup['id']})) for adgroup in adgroup_list])
        time_samples.append(samp)

    tactical_actions = []

    # print header
    if output_format == 'text':
        if not quiet:
            #if stgt_filter: print "FILTER:", stgt_filter
            if time_range:
                def hrs_ago(x): return (time_now - x)/3600.0
                print "TIME RANGE:", time_range, "("+ (' - '.join(['%.1f' % hrs_ago(x) for x in time_range])) + " hrs ago)", "next", adstats_quantize_time(3*3600+time_range[1], round_up=True),
            print "STATS FOR:", len(adgroup_list), "ads:", [len(adstats[s['ui_name']]) for s in time_samples]

    elif output_format == 'csv':
        # sample command:
        # ./skynet.py --mode adstats-analyze --use-record a --use-analytics tr --filter atr --group-by a_A_q_v_k --time-range 1388534400-1994218800 --min-clicks 1 --output-format csv | tee /tmp/tr.csv

        fields = ['"date"', '"group"', '"spent"', '"clicks"']
        if group_params:
            fields += ['"campaign_start"', '"campaign_end"']
            fields += ['"tgt_%s"' % x['name'] for x in group_params]
        if use_analytics:
            fields += ['"act_installs"', '"act_cpi"', '"ratio"',
                       '"skynet_0"', '"skynet_2h"', '"skynet_1d"', '"skynet_10d"',
                       '"skynet_total_0"', '"skynet_total_2h"', '"skynet_total_1d"', '"skynet_total_10d"',
                       '"receipts_user_d90"', '"receipts_total_d90"', '"receipts_d90_N"', '"receipts_user"', '"receipts_total"']
        print ','.join(fields)

    for time_sample in time_samples:
        groups = {}
        for adgroup in adgroup_list:
            stats = adstats[time_sample['ui_name']].get(adgroup['id'], None) # check key type
            if not stats:
                print >> sys.stderr, "no stats for", adgroup['name'], "at time", time_sample['ui_name']
                continue

            stgt, tgt = decode_adgroup_name(spin_params, adgroup['name'])
            if stgt is None:
                if not quiet: print >> sys.stderr, "unrecognized stgt", adgroup['name']
                continue
            if tgt_filter and (not match_params(tgt, tgt_filter)): continue # filtered out

            if 'game' in tgt:
                game_data = GAMES[tgt['game']]
                vb = game_data.get('viral_benefit', 0)
            else:
                vb = 0

            groupname = stgt_filter+'_' if stgt_filter else ''

            if group_by:
                if group_by == 'ALL':
                    group_tgt = tgt
                    groupname += stgt
                else:
                    group_tgt = {}
                    for p in group_params:
                        if p['name'] in tgt:
                            group_tgt[p['name']] = tgt[p['name']]
                    groupname += encode_params(spin_params, group_tgt)

            else:
                group_tgt = None
                groupname += 'ALL'

            if verbose: print "%-80s spent %8s  impressions %8d  clicks %4d" % (adgroup['name'], pretty_cents(stats['spent']), stats['impressions'], stats['clicks']),
            installs = 0
            ltv_click = 0
            ltv_install = 0
            if stats['impressions'] > 0:
                if verbose: print ' CTR', '%0.3f%%' % (float(100*stats['clicks'])/stats['impressions']),

                coeff, install_rate, ui_info = bid_coeff(spin_params, tgt, use_bid_shade = False, use_install_rate = False)
                ltv_click += 100*coeff*install_rate # convert from dollars to cents here
                ltv_install += 100*coeff

                # get the estimated number of installs
                # note: allow this to be fractional, since rounding down in small campaigns with low click count will grossly underestimate installs
                if (get_installs_from == 'app_installs') and ('actions' in stats) and ('app_install' in stats['actions']):
                    installs = install_rate * stats['actions']['app_install']
                elif stats['clicks'] > 0:
                    installs = install_rate * stats['clicks']

                if installs > 0 and stats['clicks'] > 0:
                    if verbose: print ' EST Installs %4.2f EST CPI %6s EST LTVC %6s LTVI %6s' % (installs, pretty_cents(float(stats['spent'])/installs), pretty_cents(ltv_click), pretty_cents(ltv_install)),

            if verbose:
                if groupname: print 'group', groupname,
                print

            if groupname not in groups:
                groups[groupname] = {'adgroups':[], 'impressions':0, 'clicks':0, 'installs':0, 'spent':0, 'est_total_ltv':0, 'group_tgt': group_tgt if group_tgt else 'ALL', 'bid_types':set(), 'viral_benefit':vb }
            group = groups[groupname]
            group['adgroups'].append(adgroup)
            group['impressions'] += stats['impressions']
            group['clicks'] += stats['clicks']
            group['installs'] += installs
            group['spent'] += stats['spent']
            group['est_total_ltv'] += ltv_install*installs
            if 'bid_type' in tgt: group['bid_types'].add(tgt['bid_type'])
            if vb != group['viral_benefit']:
                raise Exception('viral_benefit varies within one group %s' % groupname)
            if 'min_start' in stats: group['min_start'] = min(group.get('min_start',9999999999), stats['min_start'])
            if 'max_end' in stats: group['max_end'] = max(group.get('max_end',-1), stats['max_end'])

        if use_analytics:
            stdoutdata = query_analytics2(use_analytics, spin_params, stgt_filter, group_by, groups, time_sample)
            for stage in stdoutdata['funnel']:
                variable = variable_key = variable_coeff = None

                if stage['stage'] == 'A00 Account Created':
                    variable = 'actual_installs'
                    variable_key = 'yes'
                    variable_coeff = 1
                elif stage['stage'] == 'A99 Total Receipts':
                    variable = 'actual_receipts'
                    variable_key = 'value'
                    variable_coeff = 100.0
                else:
                    for NAME, VAR in [('A10 Mean 1-Day Receipts/User', 'actual_receipts_d1'),
                                      ('A11 Mean 3-Day Receipts/User', 'actual_receipts_d3'),
                                      ('A12 Mean 7-Day Receipts/User', 'actual_receipts_d7'),
                                      ('A13 Mean 14-Day Receipts/User', 'actual_receipts_d14'),
                                      ('A14 Mean 30-Day Receipts/User', 'actual_receipts_d30'),
                                      ('A16 Mean 60-Day Receipts/User', 'actual_receipts_d60'),
                                      ('A17 Mean 90-Day Receipts/User', 'actual_receipts_d90'),
                                      ('A50 Skynet Demographic Estimated 90-Day Receipts/User', 'actual_skynet_ltv0'),
                                      ('A51 Skynet Demographic+2h Estimated 90-Day Receipts/User', 'actual_skynet_ltv1'),
                                      ('A52 Skynet Demographic+1d Estimated 90-Day Receipts/User', 'actual_skynet_ltv2'),
                                      ('A52B Reg/Exp Test Model Demographic+3h Estimated 90-Day Receipts/User', 'actual_skynet_ltv2_regexp'),
                                      ('A53 Skynet Demographic+10d Estimated 90-Day Receipts/User', 'actual_skynet_ltv3'),
                                      ('A54 Actual 90-Day Total Receipts', 'actual_total_receipts_d90'),
                                      ]:
                        if stage['stage'] == NAME:
                            variable = VAR
                            variable_key = 'value'
                            variable_coeff = 100.0
                            break

                if variable is None: continue

                for groupname, group in groups.iteritems():
                    for cohort in stage['cohorts']:
                        cname = (stgt_filter+'_' if stgt_filter else '')+(cohort['name'] if cohort['name'] != 'Users' else 'ALL')
                        if (groupname == cname):
                            if variable_key == 'yes/N':
                                val = cohort['yes']/float(cohort['N']) if cohort['N'] > 0 else 0
                            else:
                                val = cohort[variable_key]
                            group[variable] = variable_coeff * val
                            group[variable+'_N'] = cohort['N']

        max_groupname_len = max(map(len, groups.iterkeys()))

        for groupname in sorted(groups.keys()):
            group = groups[groupname]
            if group['clicks'] < min_clicks: continue

            ui_groupname = ('%-'+str(max_groupname_len)+'s') % groupname

            ctr = ('%.2f%%' % ((100.0*group['clicks'])/group['impressions'])) if group['impressions'] > 0 else '  -  '

            # print successive a posteriori LTV estimates, stopping when N drops below 25% of cohort size
            def enough_N(group, n):
                return n > max(1, 0.25*group['actual_installs'])

            if 'actual_installs' in group: # has analytics
                best_skynet_ltv = -1
                for period in [0,1,2,3]:
                    key = 'actual_skynet_ltv%d' % period
                    if enough_N(group, group[key+'_N']):
                        best_skynet_ltv = group[key]

                        # if reg/exp projection is available, use the lower of that and the original skynet estimate
                        if use_regexp_ltv and enough_N(group, group.get(key+'_regexp_N',0)):
                            best_skynet_ltv = min(best_skynet_ltv, group[key+'_regexp'])

                group['actual_cpi'] = float(group['spent'])/group['actual_installs'] if group['actual_installs'] > 0 else -1

            if output_format == 'csv':
                fields = [time_sample['ui_name'],
                          '"'+groupname+'"',
                          '%.2f' % (group['spent']/100.0),
                          '%d' % group['clicks']]

                if group_params:
                    for FIELD in ('min_start', 'max_end'):
                        if group.get(FIELD,-1) > 0:
                            y, m, d = SpinConfig.unix_to_cal(group[FIELD]) # XXX should there be a timezone conversion here?
                            ui_name = '%d/%d/%d' % (m,d,y)
                            fields.append(ui_name)
                        else:
                            fields.append('')
                    for param in group_params:
                        if param['name'] in group['group_tgt']:
                            val = encode_one_param(spin_params, param['name'], group['group_tgt'][param['name']])[1:]
                            fields.append('"'+val+'"')
                        else:
                            fields.append('')

                if ('actual_installs' in group):
                    if group['actual_installs'] > 0 and group['actual_cpi'] > 0:
                        bid_perf = '%0.2f' % (best_skynet_ltv / group['actual_cpi'])
                    else:
                        bid_perf = ''
                    fields += ['%d' % group['actual_installs'], '%.2f' % (group['actual_cpi']/100.0), bid_perf]
                    fields += ['%.2f' % (group['actual_skynet_ltv%d' % i]/100.0) for i in (0,1,2,3)]
                    fields += ['%.2f' % (group['actual_installs']*group['actual_skynet_ltv%d' % i]/100.0) for i in (0,1,2,3)]
                    fields += ['%.2f' % (group['actual_receipts_d90']/100.0),
                               '%.2f' % (group['actual_total_receipts_d90']/100.0),
                               '%d' % group['actual_total_receipts_d90_N']]
                    fields +=  [('%.2f' % ((group['actual_receipts']/group['actual_installs'])/100.0)) if group['actual_installs'] > 0 else '', '%.2f' % (group['actual_receipts']/100.0)]
                print ','.join(fields)

            else:
                if ('actual_installs' not in group):
                    # no analytics data
                    cpi = pretty_cents(float(group['spent'])/group['installs']) if group['installs'] > 0 else '-'
                    est_user_ltv = pretty_cents(float(group['est_total_ltv'])/group['installs']) if group['installs'] > 0 else '-'
                    gain = group['est_total_ltv']-group['spent']
                    gain_pct = (100.0*gain)/group['spent'] if group['spent'] > 0 else 0

                    print "%s %s Clicks %6d CTR %s EST Installs %4d EST CPI %6s EST LTV %6s Spent %8s EST Receipts %8s   EST gain %9s (%+4.0f%%)" % \
                          (time_sample['ui_name'], ui_groupname, group['clicks'], ctr, group['installs'], cpi, est_user_ltv, pretty_cents(group['spent']), pretty_cents(group['est_total_ltv']), pretty_cents(gain), gain_pct)
                else:
                    # we have analytics2 data!
                    actual_installs = '%4d' % group['actual_installs']
                    if group['installs'] < 5:
                        pass # no comment when estimated installs are < 5
                    elif group['actual_installs'] > int(math.ceil(1.1*group['installs'])):
                        actual_installs = ANSIColor.green(actual_installs)
                    elif group['actual_installs'] < group['installs']-1:
                        actual_installs = ANSIColor.red(actual_installs)

                    cpi = '%6s' % pretty_cents(group['actual_cpi']) if group['actual_installs'] > 0 else '   -  '

                    target_cpi = '%6s' % pretty_cents(group['actual_cpi']*group['actual_installs']/float(group['installs'])) if (group['actual_installs'] > 0 and group['installs'] > 0) else '   -  '

                    if group['actual_installs'] > 0:
                        cpi = ANSIColor.yellow(cpi)

                    gain = group['actual_receipts']-group['spent']
                    gain_pct = (100.0*gain)/group['spent'] if group['spent'] > 0 else 0
                    roi_pct = (100.0*group['actual_receipts'])/group['spent'] if group['spent']>0 else 0

                    def pretty_ltv(group, key, color = True):
                        if enough_N(group, group[key+'_N']):
                            val = group[key]
                            s = '%6s' % pretty_cents(val)
                            if color:
                                if val >= 1.01*group['actual_cpi']:
                                    s = ANSIColor.green(s)
                                elif val >= 0.925*group['actual_cpi']:
                                    s = ANSIColor.yellow(s)
                                else:
                                    s = ANSIColor.red(s)
                            return s
                        else:
                            return '   -  '
#                        if group[key+'_N'] <= 0:
#                            return '-'
#                        return '%5s N=%4d' % (pretty_cents(group[key]), group[key+'_N'])

                    final_ltvs = ''
                    skynet_ltvs = ' '.join([pretty_ltv(group, 'actual_skynet_ltv%d' % period) for period in [0,1,2,3]])
                    if group.get('max_end',-1) > 0 and (time_now - group['max_end']) > 90*24*60*60:
                        final_ltvs += ' R90 '+pretty_ltv(group, 'actual_receipts_d90')
                    if use_regexp_ltv and group.get('actual_skynet_ltv2_regexp_N',0) > 0:
                        final_ltvs += ' RegExp '+pretty_ltv(group, 'actual_skynet_ltv2_regexp')

                    # bid performance

                    if 0: # len(group['bid_types']) == 1 and ('CPC' in group['bid_types']):
                        # this was the old way of evaluating CPC bids - now we use Ratio for CPC as well as oCPM
                        bid_perf_ratio = -1
                        bid_perf = 'Target %s' % target_cpi
                    elif group['actual_installs'] > 0 and group['actual_cpi'] > 0 and best_skynet_ltv > 0:
                        bid_perf_ratio = (1 + group['viral_benefit']) * (best_skynet_ltv / group['actual_cpi'])
                        bid_perf = 'Ratio%s   %0.2f' % ('*' if group['viral_benefit'] else ' ', bid_perf_ratio)
                    else:
                        bid_perf_ratio = -1
                        bid_perf = '             '

                    # receipts curve
                    #rec = ' '.join([('%d ' % day) + pretty_ltv(group, 'actual_receipts_d%d' % day, color = False) for day in [1,3]]) # ,7,14,30,60,90]])

                    #actual_receipts_per_install = ANSIColor.yellow('%5s' % pretty_cents(group['actual_receipts']/float(group['actual_installs']))) \
                    #                              if group['actual_installs'] > 0 else '  -  '

                    if tactical:
                        shade_range = [-1,-1]
                        creation_time = -1
                        bid_mtime = group.get('min_start', -1)
                        is_harvest = True
                        for adgroup in group['adgroups']:
                            if 'created_time' in adgroup:
                                creation_time = max(creation_time, adgroup['created_time'] if type(adgroup['created_time']) is int else SpinFacebook.parse_fb_time(adgroup['created_time']))
                                bid_mtime = max(bid_mtime, creation_time)

                            # identify non-harvest campaigns
                            stgt, tgt = decode_adgroup_name(spin_params, adgroup['name'])
                            if tgt and \
                               (tgt.get('exclude_player_audience',True) == False or \
                                tgt.get('include_already_connected_to_game',False) == True or \
                                tgt.get('custom_audiences',['none-'])[0].split('-')[0] in GAMES):
                                is_harvest = False

                            shade = tactical_bid_shades_by_adgroup_id.get(str(adgroup['id']), None)
                            if shade is None:
                                print 'no tactical bid shade for', adgroup['name'], '- use control-adgroups with --tactical=freeze to initialize'
                            else:
                                bid_mtime = max(bid_mtime, shade['mtime'])
                                if shade_range[0] < 0:
                                    shade_range = [shade['bid_shade'],shade['bid_shade']]
                                else:
                                    shade_range[0] = min(shade_range[0], shade['bid_shade'])
                                    shade_range[1] = max(shade_range[1], shade['bid_shade'])
                        ui_tactical = '(cur %.2f-%.2f %.1fhrs ago)' % (shade_range[0], shade_range[1], (time_now-bid_mtime)/3600)
                        fraction_of_day = (time_sample['end']-time_sample['start'])/86400.0

                        # minimum delivery thresholds to keep ads
                        if len(group['adgroups']) <= 1:
                            min_spend_per_day = 0
                            min_installs_per_day = 0
                            min_clicks_per_day = 0
                            min_impressions_per_day = 700
                            min_spend_to_adjust = 50
                        else:
                            min_spend_per_day = min(1000, 50*len(group['adgroups'])) # at least $0.50/ad or $10 for a bunch
                            min_installs_per_day = 0
                            min_clicks_per_day = 1
                            min_impressions_per_day = 0
                            min_spend_to_adjust = min(1000, 100*len(group['adgroups'])) # at least $1.00/ad or $10 for a bunch

                        if not is_harvest:
                            ui_tactical += ' NON-HARVEST'
                        elif group['spent']/fraction_of_day < min_spend_per_day or \
                             group['actual_installs']/fraction_of_day < min_installs_per_day or \
                             group['clicks']/fraction_of_day < min_clicks_per_day or \
                             (group['impressions']/fraction_of_day < min_impressions_per_day and group['actual_installs'] < 1):
                            # low spend/installs
                            ui_tactical += ' LOW DELIVERY AGE %.1f hrs' % ((time_now - creation_time)/3600)
                            if creation_time > 0 and (time_now - creation_time) >= 12*3600:
                                ui_tactical += ', PROBABLY DEAD'
                                tactical_actions.append({'action': 'delete', 'stgt_filter': groupname})
                        else:
                            if len(group['bid_types']) == 1 and bid_perf_ratio >= 0: # DO include CPC bids here ... and list(group['bid_types'])[0].startswith('oCPM') :
                                # propose bid shade modification
                                if bid_mtime > 0 and (time_now - bid_mtime < 3*3600):
                                    ui_tactical += ' RECENTLY MODIFIED'
                                elif (bid_perf_ratio < 0.95 or bid_perf_ratio >= 1.1):
                                    if group['spent'] >= min_spend_to_adjust:
                                        # multiply bid shade by bid_perf_ratio, but limit how much we can go up or down
                                        coeff = min(max(bid_perf_ratio, 0.33), 1.5)
                                        ui_tactical += ' MODIFY BY x%.2f' % coeff
                                        tactical_actions.append({'action': 'update', 'stgt_filter': groupname, 'coeff': coeff})
                                    else:
                                        ui_tactical += ' NOT ENOUGH DATA'
                            else:
                                ui_tactical += ' IGNORE'
                    elif group.get('max_end',-1) > 0 and (time_now - group['max_end']) > 90*24*60*60:
                        roi_d90_pct = (100.0*group.get('actual_total_receipts_d90',0))/group['spent'] if group['spent']>0 else 0
                        ui_tactical = 'Receipts_d90 %9s \"ROId90\" %3.0f%%' % (pretty_cents(group.get('actual_total_receipts_d90',0)), roi_d90_pct)
                    else:
                        ui_tactical = ''

                    print "%s%s Ads %3d Imp %7d Clicks %4d CTR %s Installs %s (EST %4d) CPI %s %s (E90 %s%s) Spent %9s Receipts %9s \"ROI\" %3.0f%% %s" % \
                          ((time_sample['ui_name']+' ') if time_sample['ui_name'] else '',
                           ui_groupname, len(group['adgroups']), group['impressions'], group['clicks'], ctr, actual_installs, group['installs'], cpi, bid_perf, skynet_ltvs, final_ltvs, pretty_cents(group['spent']), pretty_cents(group['actual_receipts']), roi_pct, ui_tactical)

    if tactical_actions:
        print 'PLAN:\n' + '\n'.join(map(repr, tactical_actions))
        if tactical == 'execute':
            needs_control_pass = False
            status_updates = []
            for action in tactical_actions:
                print 'EXECUTE', action
                if action['action'] == 'update':
                    if tactical_update(db, stgt_filter = action['stgt_filter'], coeff = action['coeff'], safe = 0) > 0:
                        needs_control_pass = True
                elif action['action'] == 'delete':
                    qs = {'adgroup_status': {'$ne':'DELETED'}}
                    qs.update(adgroup_dtgt_filter_query(stgt_to_dtgt(action['stgt_filter']), dtgt_key = spin_field('dtgt')))
                    my_updates = [adgroup_update_status_batch_element(adgroup, new_status = 'deleted') for adgroup in \
                                  db.fb_adgroups.find(qs)]
                    print 'deleting', len(my_updates), 'ads'
                    status_updates += my_updates
                else:
                    raise Exception('unhandled action')
            if status_updates:
                print 'sending deletions...'
                adgroup_update_status_batch(db, status_updates)
                print 'garbage-collecting empty campaigns...'
                adcampaigns_garbage_collect(db)
            if needs_control_pass:
                print 'running control pass...'
                control_adgroups(db, stgt_filter, tactical = 'use', explain = False)

class ANSIColor:
    BOLD = '\033[1m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    @classmethod
    def bold(self, x): return self.BOLD+x+self.ENDC
    @classmethod
    def red(self, x): return self.RED+x+self.ENDC
    @classmethod
    def green(self, x): return self.GREEN+x+self.ENDC
    @classmethod
    def yellow(self, x): return self.YELLOW+x+self.ENDC

def adimages_pull(db, ad_account_id):
    [update_fields_by_id(db.fb_adimages, mongo_enc(x), primary_key = 'hash') for x in \
     fb_api(SpinFacebook.versioned_graph_endpoint('adimage', 'act_'+ad_account_id+'/adimages'), is_paged = True, dict_paging = True)]

def adcreatives_pull(db, ad_account_id):
    [update_fields_by_id(db.fb_adcreatives, mongo_enc(x)) for x in \
     fb_api(SpinFacebook.versioned_graph_endpoint('adcreative', 'act_'+ad_account_id+'/adcreatives'), is_paged = True)]

def _adimage_upload(db, ad_account_id, filename):
    base = os.path.basename(filename)
    result = fb_api(SpinFacebook.versioned_graph_endpoint('adimage', 'act_'+ad_account_id+'/adimages'), upload_files = { base: open(filename, 'rb') })
    if not result: return False
    assert len(result['images']) == 1
    entry = result['images'].values()[0]
    # remember basename so we can look it up later
    entry[spin_field('basename')] = base
    update_fields_by_id(db.fb_adimages, mongo_enc(entry), primary_key = 'hash')
    return entry['hash']

def adimage_get_hash(db, ad_account_id, filename):
    assert os.path.exists(filename)
    base = os.path.basename(filename)
    entry = db.fb_adimages.find_one({spin_field('basename'):base}) # does ad_account_id need to match?
    if entry and 'hash' in entry: return entry['hash']
    return _adimage_upload(db, ad_account_id, filename)

def adimage_get_s3_url(db, image):
    entry = db.s3_adimages.find_one({'_id':image})
    if not entry:
        filename = os.path.join(asset_path, 'image_'+image+'.jpg')
        print 'uploading image to S3:', image, '('+filename+') ...',
        con = SpinS3.S3(os.getenv('HOME')+'/.ssh/'+socket.gethostname().split('.')[0]+'-awssecret')
        basename = os.path.basename(filename)
        assert con.put_file(s3_image_bucket, s3_image_path+basename, filename, acl='public-read')
        entry = {'_id':image, 'url': 'https://s3.amazonaws.com/'+s3_image_bucket+'/'+s3_image_path+basename}
        db.s3_adimages.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).replace_one({'_id':entry['_id']}, entry, upsert=True)
        print 'done'
    return entry['url']

def _page_feed_post_make(db, page_id, page_token, link, caption, title, body, image, call_to_action):
    params = {'access_token': page_token,
              'call_to_action': SpinJSON.dumps({'type': call_to_action,
                                                'value': {'link':link,
                                                          'link_title':title}}),
              'message': body,
              'picture': adimage_get_s3_url(db, image),
              'published': 'false'
              }
    if caption: params['caption'] = caption
    entry = fb_api(SpinFacebook.versioned_graph_endpoint('page/feed', page_id+'/feed'), post_params = params)
    return entry

def page_feed_post_make(db, page_id, page_token, link, caption, title, body, image, call_to_action):
    if dry_run: return '0'
    page_post_key = {'page_id': page_id,
                     'link': link,
                     'caption': caption,
                     'title': title,
                     'body': body,
                     'image': image,
                     'call_to_action': call_to_action}
    page_post_key_hash = abbreviate_key(urllib.urlencode([(k,v) for k,v in sorted(page_post_key.items())]))
    cached = db.fb_page_feed.find_one({'_id': page_post_key_hash, spin_field('key'): page_post_key})
    if cached:
        return cached['id']
    else:
        entry = _page_feed_post_make(db, page_id, page_token, link, caption, title, body, image, call_to_action)
        assert entry and entry['id']
        entry['_id'] = page_post_key_hash
        entry[spin_field('key')] = page_post_key
        db.fb_page_feed.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).replace_one({'_id':entry['_id']}, entry, upsert=True)
        return entry['id']

def adcreative_make_batch_element(db, ad_account_id, fb_campaign_name, campaign_name, tgt, spin_atgt):
    # this just got REALLY complicated for app ads:
    # https://developers.facebook.com/docs/reference/ads-api/mobile-app-ads/
    # instead of just making an adcreative, you have to make a (hidden) feed post to the app fan page,
    # then link that into the creative

    # add tgt_param to this and uniquify
    creative = {#'type': str(tgt['ad_type']), # this field is obsolete
                'name': 'Skc '+spin_atgt } # Skc = Skynet Creative

    if tgt.get('include_already_connected_to_game',False):
        tgt_key = 'spin_rtgt' # retargetings go to a different parameter
        assert campaign_name[0:4] != '7120' # make sure we don't overlap non-retargeting campaigns
    else:
        tgt_key = 'spin_atgt'

    game_id = tgt.get('game', 'tr')
    game_data = GAMES[game_id]
    assert game_data['ad_account_id'] == ad_account_id

    ad_type = tgt['ad_type']

    link_qs = 'spin_campaign=%s&%s=%s' % (campaign_name, tgt_key, spin_atgt)
    link_destination = tgt.get('destination','app')
    caption_text = None

    if link_destination == 'app':
        base_link_url = 'https://apps.facebook.com/'+game_data['namespace']+'/'
        link_url = base_link_url + '?' + link_qs
        creative['call_to_action_type'] = 'PLAY_GAME'
    elif link_destination == 'appcenter':
        # use cookie reflection to ensure query params survive the bounce
        base_link_url = 'http://'+game_data['host']+'/'
        link_url = base_link_url + '?' + link_qs+'&spin_rfl='+urllib.quote('http://facebook.com/appcenter/'+game_data['namespace']+'?fb_source=ad&oauthstate='+fb_campaign_name)
    elif link_destination == 'app_page':
        base_link_url = 'https://www.facebook.com/'+game_data['page_id']+'/'
        link_url = base_link_url + '?' + link_qs
        creative['call_to_action_type'] = 'OPEN_LINK' # 'PLAY_GAME'
        caption_text = game_data['app_name']
    else:
        raise Exception('unknown link destination type '+link_destination)

#    if link_destination != 'app': assert ad_type not in (4,32,432) # non-Type 1 ads must go to the app

    assert len(link_url) < 1024

    if ad_type in (1,4,32,432):
        title_text = open(os.path.join(asset_path, 'title_'+tgt['title']+'.txt')).read().strip()
        body_text = open(os.path.join(asset_path, 'body_'+tgt['body']+'.txt')).read().strip()
        image_file = os.path.join(asset_path, 'image_'+tgt['image']+'.jpg')
        if ad_type == 1:
            image_hash = adimage_get_hash(db, ad_account_id, image_file)

        if ad_type in (4,32,432):
            link_url_template = base_link_url

            if 0:
                # (old) BUG: https://developers.facebook.com/bugs/520919191353148/
                # Facebook docs SAY that the adcreative's url_tags will be appended to the link,
                # but in practice it does not seem to work!
                # UPDATE: This seems to have been fixed as of 20140707
                link_url_template = link_url # use the entire link here so that the destination URL will be correct even without url_tags


            page_post_id = page_feed_post_make(db, game_data['page_id'], game_data['page_token'],
                                               link_url_template, caption_text, title_text, body_text, tgt['image'],
                                               creative.get('call_to_action_type','OPEN_LINK'))

    # March 2014 migration note - FB is deprecating Type 4 (right-hand-side) app install ads.
    # I think we can replace these with either Type 1 domain ads OR Type 32 app install ads,
    # where the Type 32 has 'page_types':['rightcolumn'] to ensure the correct image and placement.

    if ad_type in (1,4,32,432):
        # create Type 1/Type 4 right-hand-side ad or Type 32 "Play Now" News Feed ad (or Type 432 combined RHS/News Feed ad)
        creative[spin_field('image_basename')] = os.path.basename(image_file)

        if ad_type == 1:
            creative['image_hash'] = image_hash
            creative['body'] = body_text
            creative['title'] = title_text
            creative['link_url'] = link_url
            creative['page_types'] = SpinJSON.dumps(['rightcolumn'])
        elif ad_type in (4,32,432):
            creative['actor_name'] = title_text # but this gets ignored
            creative['object_story_id'] = page_post_id
            creative['url_tags'] = link_qs
            #creative['link_url'] = link_url
            #creative['mobile_store'] = 'fb_canvas'
            if 'app_icon' in game_data:
                creative['actor_image_hash'] = adimage_get_hash(db, ad_account_id, os.path.join(asset_path, game_data['app_icon'])) # this gets ignored too

        if ad_type == 1 and link_destination == 'app':
            # assert image is 871x627
            creative['related_fan_page'] = game_data['app_id'] # optional - this is the App ID for the App
        elif ad_type in (4,32,432):
            # assert image is 871x627 (Type 1/4) or 1200x627 (Type 32)
#            creative['actor_id'] = game_data['page_id']
#            creative['object_id'] = game_data['app_id'] # App ID
            if 'actor_name' not in creative:
                creative['actor_name'] = game_data['app_name']

    elif ad_type in (25,27):
        creative['url_tags'] = link_qs
        if ad_type == 25:
            # create Sponsored Story ad - these don't have link URLs!
            assert link_destination == 'app'
            creative['action_spec'] = SpinJSON.dumps(tgt['creative_action_spec'])
        elif ad_type == 27:
            # create Page Story Ad
            creative['link_url'] = link_url
            creative['object_id'] = tgt['creative_object_id']
            creative['story_id'] = tgt['creative_story_id']

    else:
        raise Exception('unhandled ad_type')

    entry = db.fb_adcreatives.find_one(creative)
    if entry and 'id' in entry: return entry, None # use cached copy

    creative[spin_field('creative_id')] = str(uuid.uuid1())
    params = dict([k_v for k_v in creative.iteritems() if (not is_spin_field(k_v[0]))])
    return creative, params

def adcreative_make(db, ad_account_id, *args):
    creative, params = adcreative_make_batch_element(db, ad_account_id, *args)
    if params is None: return creative

    result = fb_api(SpinFacebook.versioned_graph_endpoint('adcreative', 'act_'+ad_account_id+'/adcreatives'), post_params = params)
    if not result:
        if dry_run:
            return {'id': 'DRY_RUN'} # dummy creative for dry runs
        else:
            return False
    creative['id'] = result['id']
    update_fields_by_id(db.fb_adcreatives, mongo_enc(creative))
    return creative

def adcreative_make_batch(db, ad_account_id, arglist):
    ret = []
    batch = []

    for args in arglist:
        creative, params = adcreative_make_batch_element(db, ad_account_id, *args)
        if params is None:
            ret.append(creative) # use cached copy
        else:
            batch.append((creative, params, len(ret)))
            ret.append(None)

    if batch:
        for batch_item, result in zip(batch,
                                      fb_api_batch(SpinFacebook.versioned_graph_endpoint('adcreative', ''),
                                                   [{'method':'POST', 'relative_url': 'act_'+ad_account_id+'/adcreatives',
                                                     'body': urllib.urlencode(params2)} for creative2, params2, ind in batch])):
            creative, params, ind = batch_item
            if result:
                creative['id'] = result['id']
                update_fields_by_id(db.fb_adcreatives, mongo_enc(creative))
                r = creative
            else:
                if dry_run:
                    r = {'id': 'DRY_RUN'}
                else:
                    raise Exception("failed to create adcreative: "+repr(params))
                    r = False
            ret[ind] = r

    return ret


# translate our own targeting parameters to the Facebook Ad API
custom_audience_cache = None

def adgroup_targeting(db, tgt):
    ret = {}

    game_id = tgt.get('game', 'tr')
    game_data = GAMES[game_id]

    if 'country' in tgt:
        assert 'country_group' not in tgt
        ret['geo_locations'] = {}
        if ',' in tgt['country']:
            # note: as a special-case hack, we allow comma-separated country lists
            # this conflicts with the original idea of having a separate "country_group" targeting parameter,
            # but it makes it easier to run campaigns with mixed single-country and multi-country targets
            ret['geo_locations']['countries'] = [c.upper() for c in tgt['country'].split(',')]
        else:
            ret['geo_locations']['countries'] = [tgt['country'].upper(),]  # note: must be uppercase!
    elif 'country_group' in tgt:
        assert 'country' not in tgt
        ret['countries'] = map(lambda x: x.upper(), tgt['country_group'].split(','))
    else:
        raise Exception('target must include either country or country_group')

    if 'gender' in tgt:
        ret['genders'] = [2 if tgt['gender'] == 'f' else 1] # # 1=male, 2=female
    if 'age_range' in tgt:
        ret['age_min'] = tgt['age_range'][0]
        ret['age_max'] = tgt['age_range'][1]

    if 'keyword' in tgt:
        for elem in tgt['keyword']:
            assert type(elem) is dict
            kind = elem.get('kind', 'broad')
            if kind == 'broad':
                raise Exception('"broad" targeting is obsolete, replace with partner category')
                # broad category/partner category targeting
                if 'AND' in elem:
                    ret_key = 'conjunctive_user_adclusters'
                    ret_val = elem['AND']
                else:
                    ret_key = 'user_adclusters'
                    ret_val = elem
                if ret_key not in ret:
                    ret[ret_key] = []
                ret[ret_key].append({'id': ret_val['id'], 'name': ret_val['name']})

            elif kind == 'action_spec':
                # action spec targeting
                assert 'action.type' in elem
                if 'action_spec' not in ret: ret['action_spec'] = []
                ret['action_spec'].append(dict([(x,y) for x,y in elem.iteritems() if x != 'kind']))
            elif kind in ('interest', 'behavior'):
                if kind+'s' not in ret: ret[kind+'s'] = []
                ret[kind+'s'].append({'name': elem['name'], 'id': elem['id']})


    def format_custom_audience(db, account_id, audname):
        global custom_audience_cache
        if custom_audience_cache is None:
            custom_audience_cache = dict(((x['name'], str(x['account_id'])), x['id']) \
                                         for x in db.fb_custom_audiences.find({}, {'name':1,'account_id':1,'id':1}))
        return {'id':custom_audience_cache[(audname, account_id)], 'name':audname}

    if 'custom_audiences' in tgt:
        ret['custom_audiences'] = [format_custom_audience(db, game_data['ad_account_id'], audname) for audname in tgt['custom_audiences']]

    if 'relationship_status' in tgt and tgt['relationship_status'] != 'any':
        ret['relationship_statuses'] = {'single':[1],
                                        'not-single':[2,3,4]}[tgt['relationship_status']]

    if 'friends' in tgt and tgt['friends']:
        ret['friends_of_connections'] = [{'id':game_data['app_id']}]

    # do not show on mobile devices
    if tgt['ad_type'] == 32:
        ret['page_types'] = ['desktopfeed']
    elif tgt['ad_type'] == 4:
        ret['page_types'] = ['rightcolumn']
    else:
        ret['page_types'] = ['desktop']

    if tgt.get('include_already_connected_to_game',False):
        pass
    else:
        # exclude people connected to the game already
        ret['excluded_connections'] = [{'id':game_data['app_id']}]

        # optionally also exclude a custom audience containing the entire player base
        if tgt.get('exclude_player_audience',True) and game_data.get('exclude_player_audience',None):
            if 'excluded_custom_audiences' not in ret: ret['excluded_custom_audiences'] = []
            ret['excluded_custom_audiences'].append(format_custom_audience(db, game_data['ad_account_id'], game_data['exclude_player_audience']))

    for aud in tgt.get('exclude_custom_audiences',[]):
        if aud is None: continue
        if 'excluded_custom_audiences' not in ret: ret['excluded_custom_audiences'] = []
        ret['excluded_custom_audiences'].append(format_custom_audience(db, game_data['ad_account_id'], aud))

    return ret

def reachestimate_tgt(tgt):
    # strip out the parts of tgt that don't apply to the reach estimate
    reach_tgt = tgt.copy()
    for FIELD in ('body','title','image','creative_object_id','creative_story_id','creative_action_spec','destination','version'):
        if FIELD in reach_tgt: del reach_tgt[FIELD]
    return reach_tgt

def reachestimate_decode(data):
    if not data: return False
    return {'N': data['users'],
            'cpc_min': data['bid_estimations'][0]['cpc_min'],
            'cpc_median': data['bid_estimations'][0]['cpc_median'],
            'cpc_max': data['bid_estimations'][0]['cpc_max'],
            'cpm_min': data['bid_estimations'][0]['cpm_min'],
            'cpm_median': data['bid_estimations'][0]['cpm_median'],
            'cpm_max': data['bid_estimations'][0]['cpm_max'],
            }

def reachestimate_get(ad_account_id, targeting):
    # main thing we want is data.users, data.bid_estimations.cpc_min/median/max
    return reachestimate_decode(fb_api(SpinFacebook.versioned_graph_endpoint('reachestimate', 'act_'+ad_account_id+'/reachestimate'),
                                       url_params = {'currency': 'USD', 'targeting_spec': SpinJSON.dumps(targeting)}))

def reachestimate_store(db, stgt, targeting, data):
    assert 'cpc_min' in data # make sure it's the right format
    data['time'] = time_now
    data['targeting_spec'] = mongo_enc(copy.deepcopy(targeting)) # since action specs have "." in them
    data['stgt'] = stgt
    data['_id'] = stgt
    db.fb_reachestimates.replace_one({'_id':stgt}, data, upsert=True)

# retrieve reachestimate and then store it both as a current value per targeting, and a historical time series
def reachestimate_get_and_store(db, ad_account_id, reach_tgt):
    targeting = adgroup_targeting(db, reach_tgt)
    reach_stgt = encode_params(spin_targets, reach_tgt)

    entry = db.fb_reachestimates.find_one({'_id':reach_stgt, 'time': { '$gt': time_now-MAX_CACHE_AGE } })
    if entry:
        #print "CACHE HIT", stgt
        return entry

    data = reachestimate_get(ad_account_id, targeting)
    if data:
        reachestimate_store(db, reach_stgt, targeting, data)
    return data

def reachestimate_ensure_cached(db, ad_account_id, tgt_list):
    query_list = []
    for tgt in tgt_list:
        stgt = encode_params(spin_targets, tgt)
        if db.fb_reachestimates.find_one({'_id':stgt, 'time': { '$gt': time_now-MAX_CACHE_AGE } }): continue # cached
        targeting = adgroup_targeting(db, tgt)
        query_list.append([stgt, targeting,
                           {'method':'GET',
                            'relative_url': 'act_'+ad_account_id+'/reachestimate?' + \
                            urllib.urlencode({'currency':'USD', 'targeting_spec':SpinJSON.dumps(targeting)})}])
    if not query_list: return

    i = 0
    for result in fb_api_batch(SpinFacebook.versioned_graph_endpoint('reachestimate', ''),
                               [x[2] for x in query_list], limit = 10, read_only = True): # , ignore_errors = True):
        stgt, targeting, query = query_list[i]
        if result:
            reachestimate_store(db, stgt, targeting, reachestimate_decode(result))
        else:
            raise Exception('bad reachestimate result for: '+stgt)
        i += 1

def adgroup_create_batch_element(db, campaign_id, campaign_name, creative_id, tgt, name):
    game_id = tgt.get('game', 'tr')
    game_data = GAMES[game_id]
    conversion_pixels = game_data['conversion_pixels']

    if ('version' in tgt) and (tgt['version']+'_') not in campaign_name and (not campaign_name.endswith(tgt['version'])):
        raise Exception('probable typo - ad version %s not present in campaign name %s' % (tgt['version'], campaign_name))

    adgroup = {'name': name,
               'campaign_id': campaign_id,
               'creative': SpinJSON.dumps({'creative_id':creative_id}),
               'tracking_specs': SpinJSON.dumps([{'action.type':'offsite_conversion','offsite_pixel':int(pixel['id'])} for pixel in conversion_pixels.itervalues()]),
               #'objective': 'PAGE_LIKES' if tgt.get('destination',None)=='app_page' else ('CANVAS_APP_ENGAGEMENT' if tgt.get('include_already_connected_to_game',False) else 'CANVAS_APP_INSTALLS'),
               'redownload':1,
               'fields': ADGROUP_FIELDS
               }
    #adgroup.update(adgroup_encode_bid(tgt['bid_type'], bid, game_data['app_id'], conversion_pixels))

    return adgroup

def adgroup_create_batch(db, ad_account_id, arglist):
    ret = []
    result_list = fb_api_batch(SpinFacebook.versioned_graph_endpoint('adgroup', ''),
                               [{'method':'POST', 'relative_url': 'act_'+ad_account_id+'/adgroups',
                                 'body': urllib.urlencode(adgroup_create_batch_element(db, *args)) } for args in arglist])
    for result in result_list:
        if result:
            assert 'data' in result and 'adgroups' in result['data'] and len(result['data']['adgroups']) == 1
            adgroup = result['data']['adgroups'][result['data']['adgroups'].keys()[0]]
            update_fields_by_id(db.fb_adgroups, mongo_enc(adgroup_add_skynet_fields(adgroup)))
            r = adgroup
        else:
            r = False
        ret.append(r)
    return ret

def adcampaign_groups_pull(db, ad_account_id):
    [update_fields_by_id(db.fb_adcampaign_groups, mongo_enc(x)) for x in \
     fb_api(SpinFacebook.versioned_graph_endpoint('adcampaign_group', 'act_'+ad_account_id+'/adcampaign_groups'),
            url_params = {'fields':'id,account_id,objective,name,campaign_group_status,buying_type',
                          'campaign_group_status':SpinJSON.dumps(['ACTIVE','ARCHIVED','PAUSED'])},
            is_paged = True)]
def adcampaign_groups_modify(db, campaign_group_name, pprops):
    props = pprops.copy(); props['redownload'] = 1
    if campaign_group_name == '*ARCHIVED*':
        query = {'campaign_status':'ARCHIVED'} # operate on all archived campaigns
    else:
        query = {'name':{'$regex':campaign_group_name}}
    campaign_groups = list(db.fb_adcampaign_groups.find(query))
    results = fb_api_batch(SpinFacebook.versioned_graph_endpoint('adcampaign_groups', ''),
                           [{'method':'POST', 'relative_url': grp['id'],
                             'body': urllib.urlencode(props) } \
                            for grp in campaign_groups])
    count = 0
    for grp, result in zip(campaign_groups, results):
        if result:
            if pprops.get('campaign_group_status',None) == 'DELETED':
                if result['success']:
                    db.fb_adcampaign_groups.delete_one({'_id':grp['_id']})
            else:
                update_fields_by_id(db.fb_adcampaign_groups, mongo_enc(result['data']['campaign_groups'][result['data']['campaign_groups'].keys()[0]]))
        count += 1
    return count

def adcampaigns_pull(db, ad_account_id):
    # You will no longer be able to view deleted ad sets by making an HTTP GET call to
    # /act_{ad_account_id}/adcampaigns
    # with the flag include_deleted. Instead, you must make an HTTP GET call and specify the field campaign_status=['DELETED']
    [update_fields_by_id(db.fb_adcampaigns, mongo_enc(x)) for x in \
     fb_api(SpinFacebook.versioned_graph_endpoint('adcampaign', 'act_'+ad_account_id+'/adcampaigns'),
            url_params = {'fields':'id,name,account_id,campaign_group_id,campaign_status,daily_budget,lifetime_budget,targeting,bid_type,bid_info',
                          'campaign_status':SpinJSON.dumps(['ACTIVE','ARCHIVED','PAUSED'])},
            is_paged = True)]

CAMPAIGN_STATUS_CODES = {'active':'ACTIVE', 'paused':'PAUSED', 'archived': 'ARCHIVED', 'deleted':'DELETED'}

def adcampaign_make(db, name, ad_account_id, campaign_group_id, app_id, app_namespace, conversion_pixels, tgt, bid):
    params = {'name':name, 'daily_budget':NEW_CAMPAIGN_BUDGET, 'campaign_status':CAMPAIGN_STATUS_CODES['active'],
              'bid_type': encode_bid_type(tgt['bid_type']),
              'promoted_object': SpinJSON.dumps({'application_id': app_id, 'object_store_url':'https://www.facebook.com/games/'+app_namespace}),
              'targeting': SpinJSON.dumps(adgroup_targeting(db, tgt)),
              'campaign_group_id': campaign_group_id, 'redownload':1}
    params.update(adgroup_encode_bid(tgt['bid_type'], bid, app_id, conversion_pixels))

    result = fb_api(SpinFacebook.versioned_graph_endpoint('adcampaign', 'act_'+ad_account_id+'/adcampaigns'),
                    post_params = params)
    if not result or ('id' not in result): return False
    campaign = result['data']['campaigns'][result['id']]
    if 'account_id' in campaign: campaign['account_id'] = str(campaign['account_id']) # FB sometimes returns these as numbers :P
    update_fields_by_id(db.fb_adcampaigns, mongo_enc(campaign))
    return campaign

def adcampaigns_modify(db, campaign_name, pprops):
    props = pprops.copy(); props['redownload'] = 1
    if campaign_name == '*ARCHIVED*':
        query = {'campaign_status':'ARCHIVED'} # operate on all archived campaigns
    else:
        query = {'name':{'$regex':campaign_name}}
    campaigns = list(db.fb_adcampaigns.find(query))
    results = fb_api_batch(SpinFacebook.versioned_graph_endpoint('adcampaign', ''),
                           [{'method':'POST', 'relative_url': camp['id'],
                             'body': urllib.urlencode(props) } \
                            for camp in campaigns])
    count = 0
    for camp, result in zip(campaigns, results):
        if result:
            if pprops.get('campaign_group_status',None) == 'DELETED':
                if result['success']:
                    db.fb_adcampaigns.delete_one({'_id':camp['_id']})
            else:
                update_fields_by_id(db.fb_adcampaigns, mongo_enc(result['data']['campaigns'][result['data']['campaigns'].keys()[0]]))
        count += 1
    return count

def adcampaigns_set_daily_budget(db, campaign_name, new_daily_budget):
    return adcampaigns_modify(db, campaign_name, {'daily_budget': new_daily_budget})

def adcampaigns_garbage_collect(db):
    campaign_ids = set(str(x['id']) for x in db.fb_adcampaigns.find({'campaign_status':{'$ne':CAMPAIGN_STATUS_CODES['deleted']}}))
    used_campaign_ids = set(str(x['_id']) for x in db.fb_adgroups.aggregate([{'$match':{'adgroup_status':{'$ne':'DELETED'}}},
                                                                             {'$group':{'_id':'$campaign_id'}}]))
    unused_campaign_ids = list(campaign_ids.difference(used_campaign_ids))
    print len(campaign_ids), 'campaigns', len(used_campaign_ids), 'used', len(unused_campaign_ids), 'unused'
    if unused_campaign_ids:
        for campaign_id, result in zip(unused_campaign_ids,
                                       fb_api_batch(SpinFacebook.versioned_graph_endpoint('adcampaign', ''),
                                                    [{'method':'POST', 'relative_url': campaign_id,
                                                      'body': urllib.urlencode({'campaign_status':CAMPAIGN_STATUS_CODES['deleted']})} for \
                                                     campaign_id in unused_campaign_ids])):
            if result:
                db.fb_adcampaigns.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).delete_one({'_id':campaign_id})

def compute_bid(db, spin_params, tgt, base_bid, ad_account_id = None, use_reachestimate = True, explain = True):
    if use_reachestimate: assert ad_account_id
    if quiet: explain = False
    bid_type = tgt.get('bid_type', 'CPC')

    use_install_rate = True

    # do not apply install rate factor to bid types that refer to events that happen post-install
    if bid_type.startswith('oCPM_') and bid_type not in ('oCPM_CLICK',):
        use_install_rate = False
    if tgt.get('include_already_connected_to_game',False):
        use_install_rate = False

    coeff, install_rate, ui_info = bid_coeff(spin_params, tgt, use_bid_shade = True, use_install_rate = use_install_rate)

    bid = int(base_bid * coeff)

    if explain:
        print '    LTV-based bid =', bid, '(base %d * %s)' % (base_bid, ui_info)
        print '    expected install rate', install_rate

    if use_reachestimate:
        reachestimate = reachestimate_get_and_store(db, ad_account_id, reachestimate_tgt(tgt))
        assert reachestimate
        if tgt.get('bid_type','CPC') in ('CPM',): # ,'oCPM'):
            cp = 'cpm'; CP = 'CPM'
        else:
            cp = 'cpc'; CP = 'CPC'

        if reachestimate:
            if explain: print '    reachestimate: %s %3d ... %3d ... %3d   N %10d' % (CP, reachestimate[cp+'_min'], reachestimate[cp+'_median'], reachestimate[cp+'_max'], reachestimate['N'])
            if reachestimate['N'] < 200 and ('custom_audiences' not in tgt):
                if explain: print 'audience too small!'
                return 1


            # cap on bids, relative to median or max reported by the reachestimate
            CAP_BID_AT = { 'oCPM_CLICK': 999.0,
                           'oCPM_INSTALL': 999.0,
                           'oCPM_acquisition_event': 999.0,
                           'CPC': 999.0,
                           'default': 999.0 }

            CAP_BID_RELATIVE_TO = { 'CPM': 'max', # let CPM bids to go the reported max
                                    'default': 'median' }

            cap_level = CAP_BID_RELATIVE_TO.get(bid_type, CAP_BID_RELATIVE_TO['default'])
            cap_coeff = CAP_BID_AT.get(bid_type, CAP_BID_AT['default'])

            if bid_type.startswith('oCPM'):
                # for oCPM bids, we have to translate the CPC data into the same units as we are bidding in

                if bid_type == 'oCPM_CLICK':
                    factor = 1.0 # 1 click per click, equivalent to CPC
                    ui_factor = ''
                elif bid_type == 'oCPM_INSTALL':
                    # not equivalent to CPC - translate to bid per "fake" Facebook app_install action
                    factor = (1.0/(TRUE_INSTALLS_PER_CLICK/TRUE_INSTALLS_PER_REPORTED_APP_INSTALL))
                    ui_factor = '*CLICKS_PER_FB_INSTALL(%.2f)' % factor
                elif bid_type.endswith('_acquisition_event'):
                    factor = (1.0/TRUE_INSTALLS_PER_CLICK)
                    ui_factor = '*1/TRUE_INSTALLS_PER_CLICK(%.2f)' % factor
                elif bid_type.endswith('cc2_by_day_1'):
                    factor = spin_params['townhall2_within_1day']['values'][1]['coeff']/TRUE_INSTALLS_PER_CLICK
                    ui_factor = '*installs_per_cc2/TRUE_INSTALLS_PER_CLICK(%.2f)' % factor
                elif bid_type.endswith('ftd'):
                    factor = 1 # this is folded into 'coeff'
                    ui_factor = ''
                else:
                    raise Exception('unhandled oCPM bid type '+bid_type)

                # not sure if we should incorporate bid shade into caps?
                cap_at = max(1, int(cap_coeff * factor * reachestimate[cp+'_'+cap_level]))
                cap_ui = 'BID_CAP(%.2f)%s*%s_%s' % (cap_coeff,ui_factor,cp,cap_level)
#              cap_at = max(1, int(factor * reachestimate[cp+'_'+cap_level]))
#              cap_ui = '%s*%s_%s' % (ui_factor,cp,cap_level)

            else:
                # for regular CPM and CPC bids, just reference against the median
                cap_at = max(1, int(cap_coeff * reachestimate[cp+'_'+cap_level]))
                cap_ui = ('%.2f*' % cap_coeff) + cp+'_'+cap_level

            if bid > cap_at and ('custom_audiences' not in tgt):
                bid = cap_at
                if explain: print '    capping at %s =' % cap_ui, bid

    if explain: print '    final bid =', bid
    return bid

def get_campaign_data(spin_campaigns, template):
    if 'inherit_from' not in template:
        return template
    else:
        parent = get_campaign_data(spin_campaigns, spin_campaigns[template['inherit_from']])
        ret = {'spin_campaign': template.get('spin_campaign', parent.get('spin_campaign',None)),
               'active': template.get('active', parent.get('active', 0)),
               'enable_ad_creation': template.get('enable_ad_creation', parent.get('enable_ad_creation', 1)),
               'bid_shade': template.get('bid_shade', parent.get('bid_shade', 1)),
               'matrices': template.get('matrices', parent.get('matrices', []))}
        if 'mutate' in template:
            ret['matrices'] = copy.deepcopy(ret['matrices'])
            for k, v in template['mutate'].iteritems():
                for m in ret['matrices']:
                    m[k] = v
        return ret

def control_ads(db, spin_campaigns, campaign_name, group_by = None, do_reachestimates = True, stgt_filter = None, enable_campaign_creation = False, enable_ad_creation = True, enable_bid_updates = True):
    spin_params = dict(get_creatives(asset_path).items()+spin_targets.items())
    if campaign_name:
        if '*' in campaign_name:
            name_list = sorted([k for k,v in spin_campaigns.iteritems() if (campaign_name.replace('*','') in k)])
        else:
            name_list = [campaign_name,]
    else:
        name_list = sorted([k for k,v in spin_campaigns.iteritems()])

    for name in name_list:
        campaign_data = get_campaign_data(spin_campaigns, spin_campaigns[name])
        if not campaign_data.get('active',1): continue
        if group_by is None and ('group_by' in campaign_data):
            group_by = campaign_data['group_by']

        if group_by:
            # expand all stgt permutations, then re-group into separate campaigns
            group_params = parse_group_by_params(spin_params, group_by)
            groups = {}
            stgt_list = sum([get_ad_stgt_list(matrix, spin_params) for matrix in campaign_data['matrices']], [])
            for stgt in stgt_list:
                tgt = decode_params(spin_params, stgt)
                group_tgt = {}
                for p in group_params:
                    if p['name'] in tgt:
                        group_tgt[p['name']] = tgt[p['name']]
                group_name = name+'_'+encode_params(spin_params, group_tgt)
                if group_name not in groups:
                    # clone the campaign
                    groups[group_name] = {'spin_campaign': campaign_data['spin_campaign'],
                                          'bid_shade': campaign_data.get('bid_shade',1),
                                          'matrices':[]}
                    if 'campaign_group_name' in campaign_data:
                        groups[group_name]['campaign_group_name'] = campaign_data['campaign_group_name']
                groups[group_name]['matrices'].append(dict((k, [group_tgt.get(k, tgt[k])]) for k, v in tgt.iteritems()))
            #print "HERE", '\n'.join(map(repr,groups.iteritems()))
        else:
            groups = {name: campaign_data}

        for n, data in sorted(groups.items()):
            control_ad_campaign(db, spin_params, n, data, do_reachestimates = do_reachestimates,
                                stgt_filter = stgt_filter, enable_campaign_creation = enable_campaign_creation, enable_ad_creation = enable_ad_creation, enable_bid_updates = enable_bid_updates)

def control_ad_campaign(db, spin_params, campaign_name, campaign_data, do_reachestimates = True,
                        stgt_filter = None, enable_campaign_creation = False, enable_ad_creation = True, enable_bid_updates = True):
    game_id = campaign_data['matrices'][0]['game'][0]
    game_data = GAMES[game_id]
    campaign_group_id = game_data['campaign_group_ids'][campaign_data.get('campaign_group_name','default')]
    print "Campaign", campaign_name, 'for', game_id, 'in account', game_data['ad_account_id'], 'campaign_group', campaign_group_id

    if not campaign_data.get('enable_ad_creation', True): enable_ad_creation = False

    ad_stgt_list = sorted(sum([get_ad_stgt_list(matrix, spin_params) for matrix in campaign_data['matrices']], []))
    if not ad_stgt_list: return

    # as of 2015, Facebook now requires all adgroups within a single adcampaign to share the same targeting
    campaign_tgt = None
    for ad_stgt in ad_stgt_list:
        ad_tgt = reachestimate_tgt(decode_params(spin_params, ad_stgt))
        if campaign_tgt is None:
            campaign_tgt = ad_tgt
        else:
            if campaign_tgt != ad_tgt:
                raise Exception('adgroup targeting mismatch within adcampaign: campaign:\n%r\nad:\n%r' % (campaign_tgt, ad_tgt))

    tgt_filter = decode_filter(spin_params, stgt_filter) if stgt_filter else None

    if tgt_filter:
        ad_stgt_list = filter(lambda x: match_params(decode_params(spin_params, x), tgt_filter), ad_stgt_list)

    #if dry_run: print "(dry run), ad list:", ad_stgt_list

    fb_campaign_list = list(db.fb_adcampaigns.find({'name':campaign_name, 'account_id': game_data['ad_account_id']}))
    if len(fb_campaign_list) > 1:
        print "ERROR! More than one campaign for name", campaign_name, "- fix this manually!"
        return
    else:
        campaign_bid = compute_bid(db, spin_params, campaign_tgt, 100 * campaign_data.get('bid_shade',1), # convert dollars to cents
                                   ad_account_id = game_data['ad_account_id'],
                                   use_reachestimate = do_reachestimates and (('custom_audiences' not in campaign_tgt) or campaign_tgt['custom_audiences'][0].startswith('like-')))
        if len(fb_campaign_list) == 1:
            fb_campaign = fb_campaign_list[0]

            # check bid on existing campaign
            if enable_bid_updates and ('bid_info' in fb_campaign):
                cur_bid = adgroup_get_bid(fb_campaign)
                if campaign_bid >= 0 and cur_bid != campaign_bid and (abs(cur_bid-campaign_bid)/float(cur_bid) > 0.04): # ignore very small deltas
                    print "    changing campaign bid from", cur_bid, "to", campaign_bid
                    adcampaign_update_bid(db, fb_campaign, campaign_bid)

        elif enable_campaign_creation:
            print "making campaign...",
            fb_campaign = adcampaign_make(db, campaign_name, game_data['ad_account_id'], campaign_group_id, game_data['app_id'], game_data['namespace'],
                                          game_data['conversion_pixels'], campaign_tgt, campaign_bid)
            if not fb_campaign:
                print "skipping",
                return
            else:
                print "ok"
            # make sure we can find it again
            print "MADE THIS", fb_campaign
            print "IN DB", list(db.fb_adcampaigns.find({'name':campaign_name, 'account_id': game_data['ad_account_id']}))
            assert fb_campaign['id'] == db.fb_adcampaigns.find_one({'name':campaign_name, 'account_id': game_data['ad_account_id']})['id']
            return # do not control any ads on first pass
        else:
            print "NOT making missing campaign", campaign_name, "- use --enable-campaign-creation flag to create it."
            return

    assert fb_campaign
    print "ID", fb_campaign['id'], 'CAMPAIGN BID', campaign_bid

    seen_ads = {}
    estimates_needed = []
    status_updates = []

    # Scan current ad groups
    # note! FB API can return adgroup campaign_id inconsistently as integer or string!
    cur_adgroup_list = sorted(list(db.fb_adgroups.find({'campaign_id':{'$in':[int(fb_campaign['id']),
                                                                              str(fb_campaign['id'])]}})), key = lambda x: x['name'])

    for adgroup in cur_adgroup_list:
        if adgroup_name_is_bad(adgroup['name']): continue # skip bad ads

        status = adgroup_decode_status(adgroup)
        known = False
        stgt, tgt = decode_adgroup_name(spin_params, adgroup['name'])
        if tgt_filter and ((not tgt) or (not match_params(tgt, tgt_filter))): continue

        if stgt is not None: known = True
        if not quiet: print '%-8s AD %s: "%-80s" BID %3d STATUS "%s"' % (('KNOWN' if known else 'UNKNOWN'), adgroup['id'], adgroup['name'], adgroup_get_bid(adgroup), status)

        if (not known):
            if 1 and (status == 'active'):
                print 'PAUSING UNKNOWN AD'
                status_updates.append(adgroup_update_status_batch_element(adgroup, new_status = 'paused'))
        else:
            # known ad
            if stgt in seen_ads:
                print 'DUPLICATE ad on stgt', stgt, 'seen ID', seen_ads[stgt], 'new ID', adgroup['id'], 'new status', status, 'new name', adgroup['name']
                if 1:
                    print 'fixing...'
                    new_name = None
                    if (not adgroup['name'].startswith('BAD')):
                        new_name = 'BAD '+adgroup['name']
                    status_updates.append(adgroup_update_status_batch_element(adgroup, new_name = new_name, new_status = 'deleted'))
                continue

            assert stgt not in seen_ads
            seen_ads[stgt] = adgroup['id']
            if status in ('active','pending_review','campaign_paused','campaign_group_paused'):
                if enable_bid_updates:
                    estimates_needed.append(stgt)
            else:
                if (not quiet):
                    print 'Warning: known ad %s status is not active ("%s")' % (stgt, status)

    if status_updates:
        print 'updating status on', len(status_updates), 'ads'
        adgroup_update_status_batch(db, status_updates)

    # Check for new ads that need to be created
    new_ads = sorted([stgt2 for stgt2 in ad_stgt_list if (stgt2 not in seen_ads)]) if enable_ad_creation else []

    if do_reachestimates and (estimates_needed or new_ads):
        # Get reachestimates for new and existing ads
        # Build set of unique stgts for reach estimate fetching
        reach_estimate_stgts = sorted(list(set(map(lambda x: encode_params(spin_params, reachestimate_tgt(x)),
                                                   # do not pull reach estimates for retention/xptarget ads, but do pull for lookalikes
                                                   filter(lambda x: ('custom_audiences' not in x) or x['custom_audiences'][0].startswith('like-'),
                                                          map(lambda x: decode_params(spin_params, x), estimates_needed + new_ads))))))
        if not quiet: print "getting reach estimates for:", reach_estimate_stgts
        reachestimate_ensure_cached(db, game_data['ad_account_id'], map(lambda x: decode_params(spin_params, x), reach_estimate_stgts))

    if enable_ad_creation:
        # Create new ads
        new_adcreative_arglist = [] # parallel to new_ads
        new_ad_params = [] # parallel to new_ads
        for stgt in new_ads:
            tgt = decode_params(spin_params, stgt)
            if 'version' not in tgt:
                raise Exception('refusing to create new ad without a "version" field: '+stgt)

            adgroup_name = 'Sky '+stgt

#            if not do_reachestimates:
#                print 'NOT creating new ad "%-80s" since we skipped reachestimates (and therefore cannot skip tiny audiences)' % (adgroup_name)
#                continue

            new_bid = compute_bid(db, spin_params, tgt, 100 * campaign_data.get('bid_shade',1), # convert dollars to cents
                                  ad_account_id = game_data['ad_account_id'],
                                  use_reachestimate = do_reachestimates and (('custom_audiences' not in tgt) or tgt['custom_audiences'][0].startswith('like-')))
            if new_bid <= 1:
                if not quiet: print 'bid would be <=1 for "%s", skipping' % adgroup_name
                continue

            if enable_ad_creation or (not quiet):
                if not enable_ad_creation: print 'NOT',
                print 'creating new ad "%-80s"' % (adgroup_name,)

            new_adcreative_arglist.append([campaign_name, campaign_data.get('spin_campaign', campaign_name), tgt, stgt])
            new_ad_params.append({'stgt':stgt, 'new_bid':new_bid, 'tactical_bid_shade': campaign_data.get('bid_shade',1), 'tgt':tgt, 'stgt':stgt, 'adgroup_name':adgroup_name})

        if new_adcreative_arglist:
            new_adcreatives = adcreative_make_batch(db, game_data['ad_account_id'], new_adcreative_arglist)
            new_adgroup_arglist = []
            for i in xrange(len(new_ad_params)):
                params = new_ad_params[i]
                creative = new_adcreatives[i]
                assert creative
                new_adgroup_arglist.append([fb_campaign['id'], fb_campaign['name'], creative['id'], # params['new_bid'],
                                            params['tgt'], params['adgroup_name']])

            new_adgroups = adgroup_create_batch(db, game_data['ad_account_id'], new_adgroup_arglist)

            if not dry_run: # save tactical bid shade
                for params, adgroup in zip(new_ad_params, new_adgroups):
                    db.tactical.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).replace_one({'_id': str(adgroup['id'])},
                                                                                                                  {'_id': str(adgroup['id']),
                                                                                                                   'name': adgroup['name'],
                                                                                                                   'stgt': params['stgt'],
                                                                                                                   'dtgt': stgt_to_dtgt(params['stgt']),
                                                                                                                   'log_bid_shade': math.log(params['tactical_bid_shade']),
                                                                                                                   }, upsert=True)

    if enable_bid_updates:
        # Update bids on existing ads
        bid_updates = []

        for stgt, adgroup_id in sorted(seen_ads.iteritems(), key = lambda k_v: k_v[0]):
            adgroup = db.fb_adgroups.find_one({'_id':adgroup_id}); assert adgroup
            if adgroup_decode_status(adgroup) not in ('active','pending review','pending_review','campaign_paused','campaign_group_paused'): continue

            tgt = decode_params(spin_params, stgt)
            cur_bid = adgroup_get_bid(adgroup)

            if not quiet: print "Checking", tgt['bid_type'], "bid on", adgroup['name'], "(currently %d)" % cur_bid

            new_bid = compute_bid(db, spin_params, tgt, 100 * campaign_data.get('bid_shade',1), # convert dollars to cents
                                  ad_account_id = game_data['ad_account_id'],
                                  use_reachestimate = do_reachestimates and (('custom_audiences' not in tgt) or tgt['custom_audiences'][0].startswith('like-')))
            new_bid = max(new_bid, 1)

            if new_bid >= 0 and cur_bid != new_bid and (abs(cur_bid-new_bid)/float(cur_bid) > 0.04): # ignore very small deltas
                if not quiet: print "    changing bid from", cur_bid, "to", new_bid
                bid_updates.append([adgroup, new_bid])

        if bid_updates:
            adgroup_update_bid_batch(db, bid_updates)

def control_adgroups(db, spin_campaigns, stgt_filter = None, tactical = 'legacy', explain = True):
    if quiet: explain = False

    params = standin_spin_params # dict(get_creatives(asset_path).items()+spin_targets.items())

    adgroup_query = {}
    if stgt_filter:
        adgroup_query.update(adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter), dtgt_key = spin_field('dtgt')))
    print "QUERY", adgroup_query

    assert tactical in ('legacy', 'none', 'freeze', 'use')

    if tactical == 'legacy':
        # get manual campaign bid shades
        tactical_bid_shades_by_campaign_id = {}
        for name, template in spin_campaigns.iteritems():
            campaign_data = get_campaign_data(spin_campaigns, template)
            if not campaign_data.get('active',1): continue
            camp = db.fb_adcampaigns.find_one({'name':name})
            if not camp:
                print 'no live ID found for campaign', name
                continue
            tactical_bid_shades_by_campaign_id[str(camp['id'])] = campaign_data.get('bid_shade',1)

    elif tactical == 'use':
        # get all tactical bid shades
        if not quiet: print 'loading tactical bid shades from database...',
        tactical_query = {}
        if stgt_filter:
            tactical_query.update(adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter), dtgt_key = 'dtgt'))
        tactical_bid_shades_by_adgroup_id = dict((row['_id'], math.exp(row['log_bid_shade'])) for row in db.tactical.find(tactical_query, {'log_bid_shade':1}))
        if not quiet: print


    adgroup_list = list(db.fb_adgroups.find(adgroup_query).sort('name'))

    status_updates = []
    bid_updates = []

    for adgroup in adgroup_list:
        status = adgroup_decode_status(adgroup)

        # check name validity
        if adgroup_name_is_bad(adgroup['name']):
            if status != 'deleted':
                print 'deleting bad ad', adgroup['name']
                status_updates.append(adgroup_update_status_batch_element(adgroup, new_status = 'deleted'))
            continue

        # check tgt validity
        stgt, tgt = decode_adgroup_name(params, adgroup['name'])
        if verbose: print '%-8s AD %s: "%-80s" BID %3d STATUS "%s"' % (('KNOWN' if stgt else 'UNKNOWN'), adgroup['id'], adgroup['name'], adgroup_get_bid(adgroup), status)
        if stgt is None:
            # unknown ad
            if status != 'deleted':
                print 'deleting unknown ad', adgroup['name']
                status_updates.append(adgroup_update_status_batch_element(adgroup, new_status = 'deleted'))
            continue

        # check if we should be updating the bid
        if status not in ('active','pending review','pending_review','campaign_paused','campaign_group_paused'): continue # skip paused or deleted ads

        cur_bid = adgroup_get_bid(adgroup)
        new_bid = -1

        if tactical == 'legacy':
            campaign_id = str(adgroup['campaign_id'])
            if campaign_id not in tactical_bid_shades_by_campaign_id:
                if not quiet:
                    print 'no tactical bid, not updating', adgroup['name']
                continue
            tactical_bid_shade = tactical_bid_shades_by_campaign_id[campaign_id]

            if verbose: print 'Checking', tgt['bid_type'], 'bid on', adgroup['name'], '(currently %d)' % cur_bid
            new_bid = max(1, compute_bid(db, params, tgt, 100 * tactical_bid_shade, # convert dollars to cents
                                         use_reachestimate = False, explain = explain))

        elif tactical == 'freeze':
            # read current bids and set tactical_bid_shade to whatever value would cause us to produce it
            would_bid = max(1, compute_bid(db, params, tgt, 100, # convert dollars to cents
                                           use_reachestimate = False, explain = explain))
            if would_bid > 1:
                tactical_bid_shade = float(cur_bid) / would_bid
                print 'Putting', adgroup['name'], 'tactical_bid_shade', tactical_bid_shade
                if not dry_run:
                    db.tactical.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0)).save({'_id': str(adgroup['id']),
                                                                                                            'name': adgroup['name'],
                                                                                                            'stgt': stgt,
                                                                                                            'dtgt': stgt_to_dtgt(stgt),
                                                                                                            'log_bid_shade': math.log(tactical_bid_shade),
                                                                                                            #'state':'ok',
                                                                                                            }, manipulate=False)
        elif tactical == 'use':
            tactical_bid_shade = tactical_bid_shades_by_adgroup_id.get(str(adgroup['id']), None)
            if tactical_bid_shade is None:
                print 'no tactical bid_shade, not updating', adgroup['name']
                continue
            new_bid = max(1, compute_bid(db, params, tgt, 100 * tactical_bid_shade, # convert dollars to cents
                                         use_reachestimate = False, explain = explain))

        if new_bid >= 0 and cur_bid != new_bid and (abs(cur_bid-new_bid)/float(cur_bid) > 0.046): # ignore very small deltas
            if explain: print "    changing bid from", cur_bid, "to", new_bid
            bid_updates.append([adgroup, new_bid])

    if status_updates:
        adgroup_update_status_batch(db, status_updates)

    if bid_updates:
        adgroup_update_bid_batch(db, bid_updates)

    if status_updates:
        print '(dry run)' if dry_run else '', 'updated status on', len(status_updates), 'ads'
    if bid_updates:
        print '(dry run)' if dry_run else '', 'updated bid on', len(bid_updates), 'ads'


def tactical_update(db, stgt_filter = None, coeff = 1, safe = 1):
    assert stgt_filter
    adgroup_query = adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter))
    #print "QUERY", adgroup_query, 'modify by *', coeff
    log_coeff = math.log(coeff)
    if not dry_run:
        tbl = db.tactical
        if not safe:
            tbl = tbl.with_options(write_concern = pymongo.write_concern.WriteConcern(w=0))
        result = db.tactical.update_many(adgroup_query, {'$inc': {'log_bid_shade': log_coeff}, '$set': {'mtime': time_now}})
        if safe:
            print 'updated', result.modified_count, 'adgroup bids'
            count = result.modified_count
        else:
            count = 1 # no way to know how many were modified
    else:
        count = db.tactical.find(adgroup_query).count()
        print '(dry run) would update', count, 'adgroup bids'
    return count

def dump_table(table, query = {}):
    map(lambda x: SpinJSON.dump(x, sys.stdout, pretty=True, newline=True), table.find(query))

def utc_pacific_offset(reftime):
    utc_delta = Timezones.USPacific.utcoffset(datetime.datetime.fromtimestamp(reftime, tz=Timezones.USPacific))
    return (utc_delta.seconds + utc_delta.days * 24 * 3600)

def utc_to_pacific(utc_unix):
    return utc_unix - utc_pacific_offset(utc_unix)
def pacific_to_utc(pacific_unix):
    return pacific_unix + utc_pacific_offset(pacific_unix)

if __name__ == '__main__':
    dbname = 'skynet'
    mode = None
    tactical = None
    adgroup_name = None
    campaign_name = None
    campaign_group_name = None
    cmd_game_id = None
    do_reachestimates = True
    enable_campaign_creation = False
    enable_ad_creation = True
    enable_bid_updates = True
    stgt_filter = None
    group_by = None
    custom_audience = None
    custom_audience_game_id = None
    origin_audience = None
    country = None
    bid = None
    coeff = None
    stgt = None
    image_file = None
    use_analytics = None
    use_regexp_ltv = False
    use_record = None
    min_clicks = 0
    min_age = 0
    min_impressions = 0
    max_frequency = 0
    time_range = None
    output_format = 'text'
    output_frequency = 'ALL'
    lookalike_type = 'similarity'
    lookalike_ratio = None

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'g:', ['db=', 'game-id=', 'mode=', 'tactical=', 'image-file=', 'dry-run', 'min-clicks=', 'min-impressions=', 'max-frequency=', 'min-age=',
                                                      'bid=', 'coeff=', 'adgroup-name=', 'campaign-name=', 'campaign-group-name=', 'stgt=', 'filter=', 'group-by=',
                                                      'use-analytics=', 'use-regexp-ltv', 'use-record=', 'date-range=', 'time-range=', 'output-format=', 'output-frequency=',
                                                      'skip-reachestimates', 'enable-campaign-creation', 'disable-ad-creation', 'disable-bid-updates', 'custom-audience=', 'custom-audience-game-id=', 'origin-audience=', 'country=', 'lookalike-type=', 'lookalike-ratio=',
                                                      'verbose', 'quiet'])

    for key, val in opts:
        if key == '--mode': mode = val
        elif key == '--db': dbname = val
        elif key == '--game-id' or key == '-g': cmd_game_id = val
        elif key == '--tactical': tactical = val
        elif key == '--image-file': image_file = val
        elif key == '--ad-type': ad_type = int(val)
        elif key == '--dry-run': dry_run = True
        elif key == '--min-clicks': min_clicks = int(val)
        elif key == '--min-age': min_age = int(val)
        elif key == '--min-impressions': min_impressions = int(val)
        elif key == '--max-frequency': max_frequency = float(val)
        elif key == '--bid': bid = int(val)
        elif key == '--coeff': coeff = float(val)
        elif key == '--stgt': stgt = val
        elif key == '--filter': stgt_filter = val
        elif key == '--group-by': group_by = val
        elif key == '--adgroup-name': adgroup_name = val
        elif key == '--campaign-name': campaign_name = val
        elif key == '--campaign-group-name': campaign_group_name = val
        elif key == '--custom-audience': custom_audience = val
        elif key == '--custom-audience-game-id': custom_audience_game_id = val
        elif key == '--origin-audience': origin_audience = val
        elif key == '--country': country = val
        elif key == '--use-analytics': use_analytics = val if val else 'tr'
        elif key == '--use-regexp-ltv': use_regexp_ltv = True
        elif key == '--use-record': use_record = val
        elif key == '--date-range':
            # awkwardly convert to Pacific time, since Facebook only stores metrics on LOCAL midnight boundaries
            date_range = map(lambda x: map(int, x.split('/')), val.split('-'))
            time_range = [-1,-1]
            for i in xrange(2):
                m,d,y = date_range[i]
                utc_unix = SpinConfig.cal_to_unix((y,m,d))
                pacific_unix = utc_to_pacific(utc_unix)
                time_range[i] = pacific_unix
        elif key == '--time-range':
            time_range = [int(x) for x in val.split('-')]
            assert len(time_range) == 2

        elif key == '--output-frequency': output_frequency = val
        elif key == '--skip-reachestimates': do_reachestimates = False
        elif key == '--enable-campaign-creation': enable_campaign_creation = True
        elif key == '--disable-ad-creation': enable_ad_creation = False
        elif key == '--disable-bid-updates': enable_bid_updates = False
        elif key == '--verbose': verbose = True
        elif key == '--quiet': quiet = True
        elif key == '--output-format': output_format = val
        elif key == '--lookalike-type': lookalike_type = val
        elif key == '--lookalike-ratio': lookalike_ratio = float(val)

    config = SpinConfig.get_mongodb_config(dbname)
    client = pymongo.MongoClient(*config['connect_args'], **config['connect_kwargs'])
    db = client[config['dbname']]
    if config['table_prefix']:
        raise Exception('table_prefix not supported')

    if mode in ('control-ads', 'control-adgroups'):
        # need to load campaign data from private dir
        import SkynetCampaigns

        if mode == 'control-ads':
            control_ads(db, SkynetCampaigns.spin_campaigns, campaign_name, group_by = group_by, do_reachestimates = do_reachestimates,
                        stgt_filter = stgt_filter, enable_campaign_creation = enable_campaign_creation, enable_ad_creation = enable_ad_creation, enable_bid_updates = enable_bid_updates)
        elif mode == 'control-adgroups':
            control_adgroups(db, SkynetCampaigns.spin_campaigns, stgt_filter = stgt_filter, tactical = tactical)

    elif mode == 'tactical-update':
        tactical_update(db, stgt_filter = stgt_filter, coeff = coeff)

    elif mode == 'adcampaign-groups-pull':
        db.fb_adcampaign_groups.drop()
        for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
            adcampaign_groups_pull(db, ad_account_id)
        dump_table(db.fb_adcampaign_groups)
    elif mode == 'adcampaign-groups-delete':
        print adcampaign_groups_modify(db, campaign_group_name, {'campaign_group_status': CAMPAIGN_STATUS_CODES[{'delete':'deleted','pause':'paused','archive':'archived','activate':'active'}[mode.split('-')[2]]]}), 'campaign_groups modified'

    elif mode == 'adcampaigns-pull':
        db.fb_adcampaigns.drop()
        for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
            adcampaigns_pull(db, ad_account_id)
        dump_table(db.fb_adcampaigns)
    elif mode == 'adcampaigns-list':
        dump_table(db.fb_adcampaigns)
    elif mode in ('adcampaigns-garbage-collect', 'adcampaigns-collect-garbage'):
        adcampaigns_garbage_collect(db)
    elif mode == 'adcampaigns-set-daily-budget':
        assert campaign_name and (bid > 0)
        print adcampaigns_set_daily_budget(db, campaign_name, bid), 'campaigns updated with daily budget', bid
    elif mode in ('adcampaigns-pause', 'adcampaigns-delete', 'adcampaigns-archive', 'adcampaigns-activate'):
        assert campaign_name
        print adcampaigns_modify(db, campaign_name, {'campaign_status': CAMPAIGN_STATUS_CODES[{'delete':'deleted','pause':'paused','archive':'archived','activate':'active'}[mode.split('-')[1]]]}), 'campaigns modified'

    elif mode == 'adgroups-pull':
        db.fb_adgroups.drop()
        for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
            adgroups_pull(db, ad_account_id = ad_account_id,
                          match_status = ['pending_review','active','paused','archived','adgroup_paused','campaign_paused','campaign_group_paused']) # pull non-deleted ads on all campaigns
        if verbose:
            print 'found', db.fb_adgroups.find().count(), 'adgroups'

    elif mode == 'adgroups-drop':
        db.fb_adgroups.drop()

    elif mode == 'adgroups-list':
        dump_table(db.fb_adgroups)

    elif mode == 'adstats-analyze':
        safe_limit = time_now-7200
        if time_range:
            if time_range[1] > safe_limit:
                if not quiet: print 'limiting end_time to', safe_limit, '(2+ hours ago) to ensure reliable results'
                time_range[1] = safe_limit
        else:
            time_range = [0, safe_limit]

        if use_record:
            time_range[0] = adstats_quantize_time(time_range[0])
            time_range[1] = adstats_quantize_time(time_range[1], round_up = True)

        if time_range[0] >= time_range[1]:
            print 'time_range is empty:', time_range
        else:
            adstats_analyze(db, min_clicks = min_clicks, stgt_filter = stgt_filter, group_by = group_by, time_range = time_range, use_analytics = use_analytics,
                            use_regexp_ltv = use_regexp_ltv, use_record = use_record, output_format = output_format, output_frequency = output_frequency, tactical = tactical)

    elif mode == 'adstats-record':
        if not time_range:
            if ADSTATS_PERIOD == 'hour':
                # find UNIX time interval covering one whole hour, two hours ago
                # (if you query data too close to the present time, you'll get incomplete results)
                time_range = [time_now-7200, time_now-3600]
            elif ADSTATS_PERIOD == 'day':
                # query yesterday's data, and what we can of today's
                time_range = [time_now - 2*86400, time_now + 86400]
            else:
                raise Exception('unknown table')

        # quantize time_range
        print 'ORIGINAL', time_range
        for i in xrange(len(time_range)):
            time_range[i] = adstats_quantize_time(time_range[i])

        # note: this works on adgroups only, totally disregarding campaign distinctions
        if adgroup_name:
            adgroup_list = [db.fb_adgroups.find_one({'name': adgroup_name})]
            if not quiet: print "single ad:", adgroup_list[0]
        else:
            if not quiet: print "Pulling all adgroups..."
            MATCH_STATUS = ['pending_review', 'active', 'paused', 'adgroup_paused', 'campaign_paused', 'campaign_group_paused']
            # pull all active ads regardless of campaign
            adgroup_list = []
            for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
                adgroup_list += adgroups_pull(db, ad_account_id = ad_account_id, match_status=MATCH_STATUS)
            # adgroup_list = db.fb_adgroups.find() # optional

            adgroup_list = filter(lambda x: (adgroup_decode_status(x) in MATCH_STATUS) and (not adgroup_name_is_bad(x['name'])), adgroup_list)
            if not quiet: print "Got", len(adgroup_list), "adgroups from API"

            # note: if we only query non-deleted, there is a race
            # condition where an ad gets deleted after its last hour
            # of operation but before the query, so we'd lose its last
            # few stats.

            # to close race condition, maintain a set of "recently seen" adgroups and add those to the query
            db.recent_adgroups.create_index('expire_time', expireAfterSeconds=0)
            expire_time = datetime.datetime.utcnow() + datetime.timedelta(seconds=60*3600) # live for 60 hours to ensure all stats get recorded
            for adgroup in adgroup_list:
                # remember adgroup
                update = adgroup.copy()
                update['_id'] = update['id']
                update['expire_time'] = expire_time
                db.recent_adgroups.find_one_and_update({'_id':update['_id']}, update, upsert=True)

            # add any remembered adgroups that we don't already have in the list
            previous = list(db.recent_adgroups.find({'_id':{'$nin':[x['id'] for x in adgroup_list]}}))
            if not quiet: print "Got", len(previous), "additional recent adgroups"
            adgroup_list += previous

        interval_start = time_range[0]
        count = 0
        while interval_start < time_range[1]:
            if ADSTATS_PERIOD == 'hour':
                interval_end = interval_start + 3600
            elif ADSTATS_PERIOD == 'day':
                # advance to next day, including daylight savings time
                interval_end = adstats_quantize_time(interval_start + 86400 + 2*3600)

            if not quiet: print "Recording stats on %d non-deleted adgroups between %d-%d..." % (len(adgroup_list), interval_start, interval_end)
            this_count = adstats_record(db, adgroup_list, [interval_start, interval_end])
            if this_count >= 0:
                count += this_count
            interval_start = interval_end

        if len(adgroup_list) < 1:
            sys.stderr.write('WARNING: did not find any current adgroups to record!\n')
        if count == 0:
            sys.stderr.write('WARNING: did not record any ads with clicks, impressions, or spend!\n')

    elif mode == 'adcreatives-pull':
        db.fb_adcreatives.drop()
        for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
            adcreatives_pull(db, ad_account_id)
        dump_table(db.fb_adcreatives)
    elif mode == 'adcreatives-list':
        dump_table(db.fb_adcreatives)

    elif mode == 'adimages-pull':
        db.fb_adimages.drop()
        for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
            adimages_pull(db, ad_account_id)
        dump_table(db.fb_adimages)
    elif mode == 'adimage-get-hash':
        print adimage_get_hash(db, GAMES[cmd_game_id]['ad_account_id'], image_file)

    elif mode == 'reachestimate-pull':
        tgt = decode_params(standin_spin_params, stgt)
        reach_tgt = reachestimate_tgt(tgt)
        print tgt, 'reachestimate:'
        print reachestimate_get_and_store(db, GAMES[cmd_game_id]['ad_account_id'], reach_tgt)
        compute_bid(db, standin_spin_params, tgt, 100, ad_account_id = GAMES[cmd_game_id]['ad_account_id']) # dollars to cents

    elif mode == 'manual-bid':
        assert bid > 0 and adgroup_name
        adgroup = db.fb_adgroups.find_one({'name': adgroup_name})
        print adgroup_name, "current bid", adgroup_get_bid(adgroup)
        if adgroup_update_bid(db, adgroup, bid):
            print "updated to", bid

    elif mode in ('adgroups-delete', 'adgroups-pause', 'adgroups-archive'):
        if (not stgt_filter) and (min_clicks <= 0) and (min_impressions < 0) and (max_frequency <= 0):
            print 'please specify at least one of: --filter, --min-clicks, --min-impressions, --max-frequency'
            sys.exit(1)

        if mode.endswith('delete'):
            ignore_status = ['DELETED']
        elif mode.endswith('archive'):
            ignore_status = ['DELETED','ARCHIVED']
        elif mode.endswith('pause'):
            ignore_status = ['DELETED','ARCHIVED','ADGROUP_PAUSED','PAUSED']

        qs = {'adgroup_status': {'$nin':ignore_status}}

        if stgt_filter:
            qs.update(adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter), dtgt_key = spin_field('dtgt')))

        print 'filter', qs
        adgroup_list = list(db.fb_adgroups.find(qs))
        print len(adgroup_list), 'ads meet filter'

        if min_clicks > 0 or max_frequency > 0 or min_impressions > 0:
            print 'getting stats...'
            # query adstats
            time_range = None
            if max_frequency > 0: # must snap to 1/7/28-day boundary to get valid unique_impressions data
                # snap to next UTC day end, in Pacific time
                # seems weird, but this is what the Facebook API wants...
                local_ts = 86400*(time_now//86400) + 86400
                local_ts = utc_to_pacific(local_ts)
                # grab one-week window
                time_range = [local_ts - 7*86400, local_ts]
            save_dry_run = dry_run; dry_run = False
            stats = adstats_pull_dict(db, adgroup_list, time_range = time_range)
            dry_run = save_dry_run

            #print stats
            if max_frequency > 0:
                for adgroup in adgroup_list:
                    stat = stats[adgroup['id']]
                    if stat and (stat['impressions'] > 150) and (stat['unique_impressions'] <= 0):
                        raise Exception('did not get valid unique_ adstats for ad %s - time range boundaries are wrong:\n%s' % (adgroup['name'], stat))


            if min_clicks > 0:
                adgroup_list = filter(lambda adgroup: stats[adgroup['id']] and stats[adgroup['id']]['clicks'] < min_clicks, adgroup_list)
            if min_impressions > 0:
                adgroup_list = filter(lambda adgroup: stats[adgroup['id']] and stats[adgroup['id']]['impressions'] < min_impressions, adgroup_list)
            if max_frequency > 0:
                print 'frequency:\n' + '\n'.join(['%-100s %.1f' % (adgroup['name'], stats[adgroup['id']]['impressions'] / float(stats[adgroup['id']]['unique_impressions']) if stats[adgroup['id']]['unique_impressions'] > 0 else 0) \
                                                  for adgroup in adgroup_list if stats[adgroup['id']]])
                adgroup_list = filter(lambda adgroup: stats[adgroup['id']] and stats[adgroup['id']]['unique_impressions'] > 0 and \
                                      (stats[adgroup['id']]['impressions'] / float(stats[adgroup['id']]['unique_impressions'])) >= max_frequency, adgroup_list)
            if min_age > 0:
                adgroup_list = filter(lambda adgroup: 'created_time' in adgroup and time_now - SpinFacebook.parse_fb_time(adgroup['created_time']) >= min_age, adgroup_list)

        status_updates = []
        for adgroup in adgroup_list:
            new_status = {'adgroups-delete': 'deleted', 'adgroups-pause': 'paused', 'adgroups-archive': 'archived'}[mode]
            status_updates.append(adgroup_update_status_batch_element(adgroup, new_status = new_status))
        print mode, len(status_updates), 'ads'
        if verbose:
            print status_updates
        adgroup_update_status_batch(db, status_updates)

    elif mode == 'adgroup-count':
        qs = {'adgroup_status': {'$ne':'DELETED'}}
        if stgt_filter:
            qs.update(adgroup_dtgt_filter_query(stgt_to_dtgt(stgt_filter), dtgt_key = spin_field('dtgt')))
        print 'filter', qs
        print db.fb_adgroups.find(qs).count(), 'ads meet filter'

    elif mode == 'custom-audiences-pull':
        db.fb_custom_audiences.drop()
        for ad_account_id in set(x['ad_account_id'] for x in GAMES.itervalues() if x['ad_account_id']):
            custom_audiences_pull(db, ad_account_id)
        dump_table(db.fb_custom_audiences)

    elif mode == 'lookalike-audience-create':
        assert custom_audience and country and origin_audience
        row = db.fb_custom_audiences.find_one({'name': custom_audience, 'account_id': GAMES[cmd_game_id]['ad_account_id']})
        if row:
            print 'lookalike audience', custom_audience, 'already exists', "'id':", "'"+row['id']+"',"
        else:
            audience_id = lookalike_audience_create(db, GAMES[cmd_game_id]['ad_account_id'], custom_audience, origin_audience, country, lookalike_type = lookalike_type, lookalike_ratio = lookalike_ratio)
            print 'CREATED lookalike audience in account_id', GAMES[cmd_game_id]['ad_account_id'], 'from', origin_audience, 'in', country, custom_audience, "'id':", "'"+audience_id+"',"

    elif mode == 'custom-audience-add':
        if not custom_audience_game_id:
            raise Exception('need to specify a --custom-audience-game-id for the incoming FBID list')
        if not custom_audience and len(args) == 1 and args[0].startswith('audience-') and args[0].endswith('.txt.gz'):
            custom_audience = args[0].replace('audience-','').replace('.txt.gz', '')
        assert custom_audience
        row = db.fb_custom_audiences.find_one({'name': custom_audience, 'account_id': GAMES[cmd_game_id]['ad_account_id']})
        if row:
            audience_id = row['id']
            print 'using existing audience', custom_audience, "'id':", "'"+audience_id+"',"
        else:
            audience_id = custom_audience_create(db, GAMES[cmd_game_id]['ad_account_id'], custom_audience)
            if audience_id: print 'CREATED audience in account_id', GAMES[cmd_game_id]['ad_account_id'], ':', custom_audience, "'id':", "'"+audience_id+"',"
        if audience_id:
            print custom_audience, 'id', audience_id, '...', ; sys.stdout.flush()
            if len(args)>=1:
                filenames = args
            else:
                filenames = [os.path.join(asset_path, 'audiences', 'audience-%s.txt.gz' % custom_audience),]

            def stream_ids(filenames):
                for filename in filenames:
                    if filename.endswith('.gz'):
                        fd = FastGzipFile.Reader(filename)
                    else:
                        fd = open(filename)
                    for line in fd.xreadlines():
                        yield line.strip()

            n_added = custom_audience_add(audience_id, ((GAMES[custom_audience_game_id]['app_id'], fb_id) for fb_id in stream_ids(filenames)))
            print 'added', n_added, 'users'

    else:
        print >>sys.stderr, "unknown mode", mode
        sys.exit(1)
