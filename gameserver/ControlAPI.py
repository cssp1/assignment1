#!/usr/bin/env python

# utility for making synchronous calls to ControlAPI via the proxyserver front end
# used by various command-line tools like PCHECK and PolicyBot

import SpinConfig
import SpinJSON
import socket
import requests
import copy

# raw exception for technical server/network trouble, when the game request might have been OK
class ControlAPIException(Exception):
    def __init__(self, http_status_code, http_body, request_url, request_args = None, errmsg = 'ControlAPI request failed'):
        Exception.__init__(self, errmsg)
        self.http_status_code = http_status_code
        self.http_body = http_body
        self.request_url = request_url
        self.request_args = request_args
    def __str__(self):
        return 'CONTROLAPI request failed with status %d: %r for %s' % \
               (self.http_status_code, self.http_body, self.request_url) + \
               (repr(self.request_args) if self.request_args else '')

# exception when the server/network are fine, but the game code didn't like the request
class ControlAPIGameException(Exception):
    def __init__(self, ret_error):
        Exception.__init__(self)
        self.ret_error = ret_error # from the CustomerSupport ReturnValue error
    def __str__(self):
        return 'CONTROLAPI bad request: %r' + (self.ret_error if isinstance(self.ret_error, basestring) else repr(self.ret_error))

# makes no assumption about return value conventions - used for legacy non-CustomerSupport methods
def CONTROLAPI_raw(args, spin_user = None, host = None, http_port = None, ssl_port = None):
    host = host or SpinConfig.config['proxyserver'].get('internal_listen_host',
                                                        SpinConfig.config['proxyserver'].get('external_listen_host','localhost'))
    proto = 'http' if host in ('localhost', socket.gethostname(), SpinConfig.config['proxyserver'].get('internal_listen_host')) else 'https'
    url = '%s://%s:%d/CONTROLAPI' % (proto, host,
                                     (ssl_port or SpinConfig.config['proxyserver']['external_ssl_port']) if proto == 'https' else \
                                     (http_port or SpinConfig.config['proxyserver']['external_http_port'])
                                     )
    args = copy.copy(args)
    if spin_user:
        args['spin_user'] = spin_user
    args['secret'] = SpinConfig.config['proxy_api_secret']
    try:
        response = requests.post(url, data = args)
    except requests.exceptions.ConnectionError: raise ControlAPIException(-1, 'ConnectionError', url)
    except requests.exceptions.ConnectTimeout: raise ControlAPIException(-1, 'ConnectTimeout', url)
    except requests.exceptions.ReadTimeout: raise ControlAPIException(-1, 'ReadTimeout', url)
    except requests.exceptions.SSLError: raise ControlAPIException(-1, 'SSLError', url)
    if response.status_code != 200:
        safe_args = args.copy()
        safe_args['secret'] = '...' # censor secret for logging
        raise ControlAPIException(response.status_code, response.text, url, safe_args)
    return response.text

# this version assumes the CustomerSupport return value conventions
def CONTROLAPI(args, spin_user = None):
    ret = SpinJSON.loads(CONTROLAPI_raw(args, spin_user = spin_user))
    if 'error' in ret:
        raise ControlAPIGameException(ret['error'])
    return ret['result']
