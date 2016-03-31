#!/usr/bin/env python

# utility for making synchronous calls to ControlAPI via the proxyserver front end
# used by various command-line tools like PCHECK and PolicyBot

import SpinConfig
import SpinJSON
import socket
import requests
import copy

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
    response = requests.post(url, data = args)
    if response.status_code != 200:
        safe_args = args.copy()
        safe_args['secret'] = '...' # censor secret for logging
        raise Exception('CONTROLAPI request failed with status %d: %r for %s args %r' % \
                        (response.status_code, response.text, url, safe_args))
    return response.text

# this version assumes the CustomerSupport return value conventions
def CONTROLAPI(args, spin_user = None):
    ret = SpinJSON.loads(CONTROLAPI_raw(args, spin_user = spin_user))
    if 'error' in ret:
        raise Exception('CONTROLAPI method failed: ' + (ret['error'] if isinstance(ret['error'], basestring) else repr(ret['error'])))
    return ret['result']
