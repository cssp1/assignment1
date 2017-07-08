#!/usr/bin/env python

# utility for making synchronous calls to ControlAPI via the proxyserver front end
# used by various command-line tools like PCHECK and PolicyBot

import SpinConfig
import SpinJSON
import socket
import requests
import copy
import time

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
        return 'CONTROLAPI bad request: ' + (self.ret_error if isinstance(self.ret_error, basestring) else repr(self.ret_error))

# makes no assumption about return value conventions - used for legacy non-CustomerSupport methods
def CONTROLAPI_raw(args, spin_user = None, host = None, http_port = None, ssl_port = None,
                   max_tries = 1, retry_delay = 5, verbose = False):
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
    if verbose:
        print 'CONTROLAPI', url, args
    args['secret'] = SpinConfig.config['proxy_api_secret']

    attempt = 1
    last_err = None

    while attempt <= max_tries:
        if attempt > 1:
            time.sleep(retry_delay)

        try:
            response = requests.post(url, data = args)

            if response.status_code == 200:
                # success!
                return response.text

            else:
                safe_args = args.copy()
                safe_args['secret'] = '...' # censor secret for logging
                last_err = ControlAPIException(response.status_code, response.text, url, safe_args)
                if response.status_code >= 500 and response.status_code <= 599:
                    pass # retry for 5xx series errors
                else:
                    break # no retry for other errors

        except requests.exceptions.ConnectionError:
            last_err = ControlAPIException(-1, 'ConnectionError', url)
            pass # retry
        except requests.exceptions.ConnectTimeout:
            last_err = ControlAPIException(-1, 'ConnectTimeout', url)
            pass # retry
        except requests.exceptions.ReadTimeout:
            last_err = ControlAPIException(-1, 'ReadTimeout', url)
            pass # retry
        except requests.exceptions.SSLError:
            last_err = ControlAPIException(-1, 'SSLError', url)
            pass # retry

        attempt += 1

    raise last_err

# this version assumes the CustomerSupport return value conventions
def CONTROLAPI(args, spin_user = None, max_tries = 1, retry_delay = 5, verbose = False):
    ret = SpinJSON.loads(CONTROLAPI_raw(args, spin_user = spin_user, max_tries = max_tries, retry_delay = retry_delay,
                                        verbose = verbose))
    if 'error' in ret:
        raise ControlAPIGameException(ret['error'])
    return ret['result']
