#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinConfig # for API version settings
import SpinJSON
import base64, hmac, hashlib, time, calendar

#
# FACEBOOK API tools
#

# parse a Facebook time value that might NOT be in UTC (Ads API)
def parse_fb_time(s):
    assert len(s) == 24 and s[10] == 'T'
    t = calendar.timegm(time.strptime(s[:19], '%Y-%m-%dT%H:%M:%S'))
    off_sign = -1 if s[19] == '-' else 1
    off_hrs = int(s[20:22], 10)
    off_min = int(s[22:24], 10)
    t -= off_sign * (3600 * off_hrs + 60 * off_min)
    return t

def unparse_fb_time(t):
    return time.strftime('%Y-%m-%dT%H:%M:%S+0000', time.gmtime(t))

# Facebook signed request verification code from
# http://sunilarora.org/parsing-signedrequest-parameter-in-python-bas

def base64_url_decode(inp):
    padding_factor = (4 - len(inp) % 4) % 4
    inp += "="*padding_factor
    mapping = dict(zip(map(ord, u'-_'), u'+/'))
    return base64.b64decode(unicode(inp).translate(mapping))

def base64_url_encode(inp):
    mapping = dict(zip(map(ord, u'+/'), u'-_'))
    ret = unicode(base64.b64encode(inp)).translate(mapping)
    idx = ret.rfind('=')
    if idx >= 0:
        ret = ret[:idx]
    return ret

def parse_signed_request(signed_request, secret):
    l = signed_request.split('.', 2)
    if len(l) < 2:
        raise Exception('Malformed signed request: %s' % repr(signed_request))

    encoded_sig = l[0]
    payload = l[1]

    sig = base64_url_decode(encoded_sig)
    data = SpinJSON.loads(base64_url_decode(payload))

    algorithm = data.get('algorithm','unspecified').upper()

    if algorithm != 'HMAC-SHA256':
        raise Exception('Unknown signature algorithm: %s' % repr(algorithm))
    else:
        expected_sig = hmac.new(str(secret), msg=payload, digestmod=hashlib.sha256).digest()

    if sig != expected_sig:
        # verification failed
        return None
    else:
        # verification succeeded
        return data

def make_signed_request(data, secret):
    assert data['algorithm'] == 'HMAC-SHA256'
    payload = base64_url_encode(SpinJSON.dumps(data))
    sig = hmac.new(str(secret), msg=payload, digestmod=hashlib.sha256).digest()
    return base64_url_encode(sig)+'.'+payload

# encode/decode app-specific custom data field in FB payment flow
# normally we b64 encode our own data, but FB-generated purchases (in-app currency promos) are not b64-encoded
def order_data_encode(data):
    return 'SP'+base64.urlsafe_b64encode(SpinJSON.dumps(data))
def order_data_decode(data):
    if data[0:2] == 'SP': return SpinJSON.loads(base64.urlsafe_b64decode(str(data[2:])))
    else: return SpinJSON.loads(data)

# All URL calls to graph.facebook.com should use these functions in order to support version configuration:
# please keep in sync with gameclient/clientcode/SPFB.js

def api_version_string(feature):
    api_versions = SpinConfig.config.get('facebook_api_versions', {})
    if api_versions and (feature in api_versions):
        sver = api_versions[feature]
    elif api_versions and ('default' in api_versions):
        sver = api_versions['default']
    else:
        sver = 'v2.1' # fallback default (sync with: FacebookSDK.js, fb_guest.html, gameserver/SpinFacebook.py, gameclient/clientcode/SPFB.js)
    return (sver + '/') if sver else ''

def versioned_graph_endpoint(feature, path, protocol = 'https://', subdomain = 'graph'):
    return protocol + subdomain + '.facebook.com/'+api_version_string(feature) + path

if __name__ == '__main__':
    test_requests = 'AQ3EraQUe8e-DZ9eT6OHmLpr16sYxUigJLuIapupRas.eyJhbGdvcml0aG0iOiJITUFDLVNIQTI1NiIsImV4cGlyZXMiOjEzMjEwMDIwMDAsImlzc3VlZF9hdCI6MTMyMDk5ODA5Nywib2F1dGhfdG9rZW4iOiJBQUFEZmxqNmdrZElCQUxjc1hRMXoxUWw5SHd1Z1h0dDBBNzR1ZWJrZUluM1JVRnV0T1FFRElvaWg1RHd5U29lWkFmZDk5UlQ3VGdFWVhGczVpZG9yaVIyT3hpRFBmSmx5TkQ0NDhhUVpEWkQiLCJ1c2VyIjp7ImNvdW50cnkiOiJ1cyIsImxvY2FsZSI6ImVuX1VTIiwiYWdlIjp7Im1pbiI6MjF9fSwidXNlcl9pZCI6IjQyNzIzMyJ9'.split('.')
    for req in test_requests:
        assert base64_url_encode(base64_url_decode(req)) == req

    test_payload = {'foo':'bar','asdf':3,'algorithm':'HMAC-SHA256'}
    test_secret = 'd82sd8bui32jnmxc8dfg'
    assert parse_signed_request(make_signed_request(test_payload, test_secret), test_secret) == test_payload

    assert parse_fb_time("2014-02-11T14:42:38-0800") == 1392158558

    import sys
    if len(sys.argv) != 3:
        print 'usage: %s APP_SECRET SIGNED_REQUEST' % sys.argv[0]
        sys.exit(1)

    print parse_signed_request(sys.argv[2], sys.argv[1])
