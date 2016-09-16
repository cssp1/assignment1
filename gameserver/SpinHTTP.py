#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# HTTP utilities

import time

# create RFC2822 timestamp
def format_http_time(stamp):
    return time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(stamp))

from email.utils import mktime_tz, parsedate_tz

# parse RFC2822 timestamp, inverse of format_http_time()
def parse_http_time(http_time):
    return long(mktime_tz(parsedate_tz(http_time)))

import base64, re

# wrap/unwrap Unicode text strings for safe transmission across the AJAX connection
# mirrors gameclient/clientcode/SPHTTP.js

def unwrap_string(input):
    return unicode(base64.b64decode(str(input)).decode('utf-8'))

def wrap_string(input):
    return base64.b64encode(input.encode('utf-8'))

# below functions are specific to Twisted

from twisted import __version__ as twisted_version
twisted_major_version = int(twisted_version.split('.')[0])
from twisted.web.server import NOT_DONE_YET
from twisted.web.http import INTERNAL_SERVER_ERROR
from twisted.python.failure import Failure

# set cross-site allow headers on Twisted HTTP requests
def _set_access_control_headers(request, origin, max_age):
    if origin:
        request.setHeader('Access-Control-Allow-Origin', origin)
    request.setHeader('Access-Control-Allow-Credentials', 'true')
    request.setHeader('Access-Control-Allow-Methods', 'POST, GET, HEAD, OPTIONS')
    request.setHeader('Access-Control-Allow-Headers', 'X-Requested-With')
    if max_age >= 0:
        request.setHeader('Access-Control-Max-Age', str(max_age))

# get a raw HTTP header from Twisted request object
def get_twisted_header(request, x):
    temp = request.requestHeaders.getRawHeaders(x)
    if temp and len(temp) > 0:
        return str(temp[0])
    else:
        return ''
def set_twisted_header(request, x, val):
    request.requestHeaders.setRawHeaders(x, [val])

def set_access_control_headers(request):
    if request.requestHeaders.hasHeader('origin'):
        origin = get_twisted_header(request, 'origin')
    elif 'spin_origin' in request.args:
        origin = request.args['spin_origin'][-1]
    else:
        origin = '*'
    _set_access_control_headers(request, origin, 7*24*60*60)

def set_access_control_headers_for_cdn(request, max_age):
    # ensure that we ONLY attach a non-wildcard origin if it's in the query string
    if 'spin_origin' in request.args:
        origin = request.args['spin_origin'][-1]
    else:
        origin = '*'
    _set_access_control_headers(request, origin, max_age)

def set_service_unavailable(request):
    request.setResponseCode(503) # 503 Service Unavailable
    request.setHeader('Retry-After', '600') # suggest retrying in 10 minutes

service_unavailable_response_body = '503 Service Unavailable, please try again later\n'

def set_accepted(request):
    request.setResponseCode(202) # 202 Accepted
    # The request has been accepted for processing, but the processing has not been completed. The request might or might not be eventually acted upon, and may be disallowed when processing occurs.
    # request.setHeader('Connection', 'close')

accepted_response_body = '{"result": "ok", "status": 202}\n'

def set_twisted_cookie(request, cookie_name, value, expire_time,
                       domain = None, path = None, secure = None, httpOnly = False):
    if twisted_major_version >= 16:
        request.addCookie(cookie_name, value, expires = format_http_time(expire_time),
                          domain = domain, path = path, secure = secure, httpOnly = httpOnly)
    else:
        # Twisted before 16.3.2 and before 15.5.0 are missing httpOnly param to addCookie()
        request.addCookie(cookie_name, value, expires = format_http_time(expire_time),
                          domain = domain, path = path, secure = secure)

    # necessary for IE7+ to accept iframed cookies
    request.setHeader('P3P', 'CP="CAO DSP CURa ADMa DEVa TAIa PSAa PSDa IVAi IVDi CONi OUR UNRi OTRi BUS IND PHY ONL UNI COM NAV INT DEM CNT STA PRE GOV LOC"')

def clear_twisted_cookie(request, cookie_name,
                       domain = None, path = None, secure = None, httpOnly = False):
    set_twisted_cookie(request, cookie_name, 'deleted', 0, domain = domain, path = path, secure = secure, httpOnly = httpOnly)

# get info about an HTTP(S) request, "seeing through" reverse proxies back to the client
# NOTE! YOU MUST SANITIZE (DELETE HEADERS FROM) REQUESTS ACCEPTED DIRECTLY FROM CLIENTS TO AVOID SPOOFING!

import SpinSignature

private_ip_re = re.compile('(^127\.0\.0\.1)|(^10\.)|(^172\.1[6-9]\.)|(^172\.2[0-9]\.)|(^172\.3[0-1]\.)|(^192\.168\.)|(^unknown)')

def validate_proxy_headers(request, proxy_secret):
    # validate the signature applied by proxyserver's add_proxy_headers()
    their_signature = get_twisted_header(request, 'spin-orig-signature')
    our_signature = SpinSignature.sign_proxy_headers(
        get_twisted_header(request,'spin-orig-protocol'),
        get_twisted_header(request,'spin-orig-host'),
        get_twisted_header(request,'spin-orig-port'),
        get_twisted_header(request,'spin-orig-uri'),
        get_twisted_header(request,'spin-orig-ip'),
        get_twisted_header(request,'spin-orig-referer'),
        proxy_secret)
    return their_signature == our_signature

# return True if we think we can trust the X-Forwarded-* headers on a request
def validate_x_forwarded(request):
    # ensure the request is coming from the "private" (AWS) network
    return bool(private_ip_re.match(request.getClientIP()))

def get_twisted_client_ip(request, proxy_secret = None, trust_x_forwarded = True): # XXXXXX temporary
    if proxy_secret:
        forw = get_twisted_header(request, 'spin-orig-ip')
        if forw:
            assert validate_proxy_headers(request, proxy_secret)
            return forw

    cf_con = get_twisted_header(request, 'CF-Connecting-IP')
    if cf_con:
        return cf_con

    incap = get_twisted_header(request, 'incap-client-ip')
    if incap:
        return incap

    forw_list = request.requestHeaders.getRawHeaders('X-Forwarded-For')
    if forw_list and len(forw_list) > 0:
        forw = ','.join(map(str, forw_list))
        if forw:
            if trust_x_forwarded or validate_x_forwarded(request):
                # return leftmost non-private address
                for ip in forw.split(','):
                    ip = ip.strip()
                    if private_ip_re.match(ip): continue # skip private IPs
                    return ip

                # ... or fall back to native request IP

            else:
                # can't trust X-Forwarded-For because it came out of a public IP
                # fall back to the native request IP
                if private_ip_re.match(request.getClientIP()):
                    raise Exception('X-Forwarded-For a private address: %r' % forw)
                else:
                    return request.getClientIP()

    return request.getClientIP()

def twisted_request_is_ssl(request, proxy_secret = None, trust_x_forwarded = True): # XXXXXX temporary
    if proxy_secret:
        orig_protocol = get_twisted_header(request, 'spin-orig-protocol')
        if orig_protocol:
            assert validate_proxy_headers(request, proxy_secret)
            return orig_protocol == 'https://'

    orig_protocol = get_twisted_header(request, 'X-Forwarded-Proto')
    if orig_protocol:
        assert trust_x_forwarded or validate_x_forwarded(request)
        return orig_protocol.startswith('https')

    return request.isSecure()

# this is the final Deferred callback that finishes asynchronous HTTP request handling
# note that "body" is inserted by Twisted as the return value of the callback chain BEFORE other args.

def complete_deferred_request(body, request, http_status = None):
    if body == NOT_DONE_YET:
        return body
    if type(body) not in (str, unicode, bytes):
        raise Exception('unexpected body type %r: %r' % (type(body), body))
    if hasattr(request, '_disconnected') and request._disconnected: return
    if http_status:
        request.setResponseCode(http_status)
    request.write(body)
    request.finish()

# wrapper for complete_deferred_request() that handles Failure results so you can put it
# at the end of a Deferred chain and it will do the right thing for successes and errors.
def complete_deferred_request_safe(body, request, http_status = None, full_traceback = False):
    if isinstance(body, Failure):
        request.setHeader('Content-Type', 'text/plain')
        request.setResponseCode(INTERNAL_SERVER_ERROR)
        if full_traceback: # dangerous - includes sensitive info in public error message
            body = 'error: %s\n%s' % (repr(body), body.getTraceback())
        else:
            body = 'error: %s' % repr(body)
    complete_deferred_request(body, request, http_status = http_status)
