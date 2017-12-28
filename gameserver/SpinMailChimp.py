#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# library to interact with MailChimp's REST API
# synchronous, uses requests

import SpinConfig
import SpinJSON
import hashlib
import urllib
import calendar
import time

# some list member methods require this at the end of the URL
def subscriber_hash(email):
    return hashlib.md5(email.lower()).hexdigest()

def mailchimp_api(requests_session, method, path, params = None, data = None, version = '3.0'):
    api_key = SpinConfig.config['mailchimp_api_key']
    datacenter = api_key.split('-')[1]
    url = 'https://%s.api.mailchimp.com/%s/%s' % (datacenter, version, path)
    if params:
        url += '?' + urllib.urlencode(params)
    headers = {'Authorization': 'Bearer '+api_key,
               'Accept': '*/*',
               'Content-Type': 'application/x-www-form-urlencoded'}
    postdata = SpinJSON.dumps(data) if data else None
    ret = SpinJSON.loads(requests_session.request(method, url, headers = headers, data = postdata).content)
    return ret

def mailchimp_api_batch(requests_session, batch, version = '3.0'):
    return mailchimp_api(requests_session, 'POST', 'batches', data = {'operations': batch}, version = version)

def parse_mailchimp_time(s):
    """ Parse a MailChimp time string value in UTC, eample:
    2017-06-06T07:00:00+00:00
    into a UTC UNIX timestamp. """
    assert s[10] == 'T'
    t = calendar.timegm(time.strptime(s[:19], '%Y-%m-%dT%H:%M:%S'))
    return t
