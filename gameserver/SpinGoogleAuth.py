#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import SpinJSON
import urllib, urllib2, urlparse, traceback

# Generic Google code

def google_auth_prompt_redirect(client_id, redirect_uri, scope = 'email', csrf_state = None, final_url = None):
    assert csrf_state
    assert final_url
    csrf_state += '|'+urllib.quote(final_url)
    params = {'response_type':'code',
              'client_id':client_id,
              'redirect_uri':redirect_uri,
              'scope':'email',
              'state':csrf_state,
              'approval_prompt':'auto'}
    url = 'https://accounts.google.com/o/oauth2/auth?'+urllib.urlencode(params)
    return '<html><body onload="location.href = \'%s\';"></body></html>' % url

def exchange_code_for_access_token(client_id, client_secret, redirect_uri, params, csrf_state_checker = None):
    returned_state, quoted_final_url = params['state'][-1].split('|')
    final_url = urllib.unquote(quoted_final_url)
    assert csrf_state_checker
    if csrf_state_checker:
        if not csrf_state_checker(returned_state):
            return {'error':'Login attempt failed due to being overwritten by a later login attempt. Please try again. (CSRF state mismatch %s)' % returned_state}

    if 'error' in params:
        return {'error':params['error'][-1]}
    try:
        response = urllib2.urlopen(urllib2.Request('https://accounts.google.com/o/oauth2/token',
                                                   urllib.urlencode({'code':params['code'][-1],
                                                                     'client_id':client_id,
                                                                     'client_secret':client_secret,
                                                                     'redirect_uri':redirect_uri,
                                                                     'grant_type':'authorization_code'})), None).read()
    except urllib2.HTTPError as e:
        return {'error':repr(e),
                'redirect':'<html><body onload="window.setTimeout(function(){location.href = \'%s?%s\';},1000)">Auth failure. Retrying...</body></html>' % \
                (redirect_uri, urllib.urlencode({'final_url':final_url}))}

    data = SpinJSON.loads(response)
    access_token = data['access_token']
    assert data['token_type'] == 'Bearer'
    expires_in = data['expires_in']
    return {'access_token':access_token,
            'expires_in':expires_in,
            'final_url':final_url}

def get_google_user_info(access_token):
    return SpinJSON.loads(urllib2.urlopen('https://www.googleapis.com/oauth2/v1/userinfo?'+urllib.urlencode({'access_token':access_token})).read())

# SpinPunch-specific code here

import SpinConfig
import SpinFacebook # borrow some code
make_signed_request = SpinFacebook.make_signed_request
parse_signed_request = SpinFacebook.parse_signed_request

def spin_token_realm(): return SpinConfig.config['spin_token_realm']
def spin_token_secret(): return SpinConfig.config['spin_token_secret']

def spin_auth_redirect(final_url):
    auth_endpoint = SpinConfig.config['realm_auth_endpoint']
    url = auth_endpoint+'?'+urllib.urlencode({'final_url':final_url})
    return '<html><body onload="window.setTimeout(function(){location.href = \'%s\';},1000)">Logging in for %s via %s...</body></html>' % (url, final_url, auth_endpoint)

def auth_spinpunch_user(access_token, expires_in, user_info, spin_users, realm, realm_secret, time_now):
    google_id = user_info['id']
    spin_user = None

    # match on google_id
    for username, entry in spin_users.iteritems():
        if ('google_id' in entry) and entry['google_id'] == google_id:
            spin_user = username
            break

    if not spin_user:
        # try match on hd
        for username, entry in spin_users.iteritems():
            if ('hd' in entry) and ('hd' in user_info) and (entry['hd'] == user_info['hd']):
                spin_user = username
                break

    if spin_user:
        spin_token_data = {'spin_user': spin_user,
                           'google_access_token': access_token,
                           'realm':realm,
                           'roles':spin_users[spin_user].get('roles',[]),
                           # note: we do NOT obey Google's "expires_in", which seems to be about one hour
                           # XXX should probably create some mechanism to renew tokens rather than using long expiration times
                           'expires_at': time_now + max(6*3600, expires_in),
                           'algorithm': 'HMAC-SHA256'}
        spin_token_data['spin_token'] = make_signed_request(spin_token_data, realm_secret)
        return spin_token_data

    else: # not recognized
        return {'spin_user': None, 'spin_token': None,
#                'google_id': google_id, 'hd': user_info.get('hd',None),
                'info_html': '<html><body>Unknown user in realm %s. Your Google ID is "%s". Your hd is "%s".</body></html>' % (realm, google_id, user_info.get('hd',''))}

def verify_spin_token(spin_token, realm, realm_secret, time_now):
    data = parse_signed_request(spin_token, realm_secret)
    if data and \
       data['realm'] == realm and \
       data['expires_at'] > time_now:
        return data
    return None

def do_auth(raw_token, realm, realm_secret, role, time_now, my_endpoint):
    spin_token_data = None
    token_error = None
    if raw_token:
        try:
            spin_token_data = verify_spin_token(raw_token, realm, realm_secret, time_now)
        except Exception:
            spin_token_data = None
            token_error = traceback.format_exc()
    if spin_token_data:
        if role not in spin_token_data['roles']:
            token_error = 'User %s not authorized for role %s in realm %s.' % (spin_token_data['spin_user'], role, realm)
            spin_token_data = None
    ret = {'ok': bool(spin_token_data),
           'spin_token': spin_token_data,
           'raw_token': raw_token}
    if token_error:
        ret['error'] = token_error
    elif not spin_token_data: # possibly a stale token
        ret['error'] = 'Your login session has expired. Please log in again.'
        ret['redirect'] = spin_auth_redirect(my_endpoint)
    return ret


def spin_token_cookie_name():
    return 'spin_'+spin_token_realm()+'_token'

# convenience functions for CGI scripts run from proxyserver (pcheck, analytics)

def cgi_get_my_endpoint():
    # get endpoint URL by looking at environment variables
    import os
    if (not os.getenv('REMOTE_ADDR')): return 'local'
    ret = ('https://' if bool(int(os.getenv('SPIN_IS_SSL'))) else 'http://')+os.getenv('HTTP_HOST')+os.getenv('REQUEST_URI')
    if ret.endswith('/'): ret = ret[:-1]
    return ret

def cgi_is_local():
    import os
    return (not os.getenv('REMOTE_ADDR')) or (os.getenv('REMOTE_ADDR') == '127.0.0.1')

def cgi_do_auth(args, role, time_now):
    import os, Cookie
    raw_token = None
    cookie_name = spin_token_cookie_name()
    cookie_string = os.getenv('HTTP_COOKIE')
    C = Cookie.SimpleCookie()
    if cookie_string:
        C.load(cookie_string)
    if ('spin_token' in args):
        raw_token = args['spin_token'][-1]
    elif cookie_name in C:
        raw_token = str(C[cookie_name].value)

    return do_auth(raw_token, spin_token_realm(), spin_token_secret(), role, time_now, cgi_get_my_endpoint())

# convenience functions for twisted apps (gameserver)

# get a raw HTTP header from Twisted request object
def get_twisted_header(request, x):
    temp = request.requestHeaders.getRawHeaders(x)
    if temp and len(temp) > 0:
        return str(temp[0])
    else:
        return ''

def url_to_domain(url):
    # be really careful here, since it could open exploits with carefully-crafted URLs
    domain = urlparse.urlparse(url).netloc
    if '@' in domain:
        fields = domain.split('@')
        assert len(fields) == 2
        domain = fields[1]
    if ':' in domain:
        fields = domain.split(':')
        assert len(fields) == 2
        assert int(fields[1])
        domain = fields[0]
    return domain

def twisted_request_is_local(request):
    orig_ip = get_twisted_header(request,'spin-orig-ip') or request.getClientIP()
    return orig_ip == '127.0.0.1'
def twisted_request_is_ssl(request):
    orig_protocol = get_twisted_header(request, 'spin-orig-protocol')
    if orig_protocol and orig_protocol == 'https://': return True
    return request.isSecure()

def twisted_get_my_endpoint(request):
    # get endpoint URL by looking at a Twisted request
    if get_twisted_header(request,'spin-orig-protocol'):
        # it's been proxied
        return get_twisted_header(request,'spin-orig-protocol')+ \
               get_twisted_header(request,'spin-orig-host')+':'+ \
               get_twisted_header(request,'spin-orig-port')+ \
               get_twisted_header(request,'spin-orig-uri')
    # not proxied
    return ('https://' if twisted_request_is_ssl(request) else 'http://')+request.getHeader('host')+request.uri


def twisted_do_auth(request, role, time_now):
    raw_token = None
    cookie_name = spin_token_cookie_name()
    if 'spin_token' in request.args:
        raw_token = request.args['spin_token'][-1]
    elif cookie_name in request.received_cookies:
        raw_token = request.received_cookies[cookie_name]

    return do_auth(raw_token, spin_token_realm(), spin_token_secret(), role, time_now, twisted_get_my_endpoint(request))
