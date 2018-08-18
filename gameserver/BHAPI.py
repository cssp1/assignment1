#!/usr/bin/env python

# utility for making synchronous calls to bhlogin
# used by various command-line tools like PCHECK

import SpinConfig
import SpinJSON
import requests
import copy
import time

def supported():
    return bool(SpinConfig.config.get('enable_battlehouse', False))

# raw exception for technical server/network trouble, when the API request might have been OK
class BHAPITechnicalException(Exception):
    def __init__(self, http_status_code, http_body, request_url, request_args = None, errmsg = 'BHAPI request failed'):
        Exception.__init__(self, errmsg)
        self.http_status_code = http_status_code
        self.http_body = http_body
        self.request_url = request_url
        self.request_args = request_args
    def __str__(self):
        return 'BHAPI request failed with status %d: %r for %s' % \
               (self.http_status_code, self.http_body, self.request_url) + \
               (repr(self.request_args) if self.request_args else '')

# exception when the server/network are fine, but the bhlogin code didn't like the request
class BHAPIException(Exception):
    def __init__(self, ret_error):
        Exception.__init__(self)
        self.ret_error = ret_error # from the CustomerSupport ReturnValue error
    def __str__(self):
        return 'BHAPI bad request: %r' + (self.ret_error if isinstance(self.ret_error, basestring) else repr(self.ret_error))

# makes no assumption about return value conventions - used for legacy non-CustomerSupport methods
def BHAPI_raw(path, args = {}, max_tries = 1, retry_delay = 5, verbose = False, error_on_404 = True):
    url = SpinConfig.config['battlehouse_api_path'] + path
    secret = SpinConfig.config['battlehouse_api_secret']

    args_cp = copy.copy(args)
    args_cp['service'] = SpinConfig.game()

    attempt = 1
    last_err = None

    while attempt <= max_tries:
        if attempt > 1:
            time.sleep(retry_delay)

        try:
            response = requests.post(url, data = args_cp, headers = {'X-BHLogin-API-Secret': secret})

            if response.status_code == 200:
                # success!
                return response.text

            elif response.status_code == 404 and (not error_on_404):
                # success, with a 404
                return 'NOTFOUND'

            else:
                last_err = BHAPITechnicalException(response.status_code, response.text, url, args)
                if response.status_code >= 500 and response.status_code <= 599:
                    pass # retry for 5xx series errors
                else:
                    break # no retry for other errors

        except requests.exceptions.ConnectionError:
            last_err = BHAPITechnicalException(-1, 'ConnectionError', url)
            pass # retry
        except requests.exceptions.ConnectTimeout:
            last_err = BHAPITechnicalException(-1, 'ConnectTimeout', url)
            pass # retry
        except requests.exceptions.ReadTimeout:
            last_err = BHAPITechnicalException(-1, 'ReadTimeout', url)
            pass # retry
        except requests.exceptions.SSLError:
            last_err = BHAPITechnicalException(-1, 'SSLError', url)
            pass # retry

        attempt += 1

    raise last_err

def BHAPI(path, args = {}, max_tries = 1, retry_delay = 5, verbose = False):
    ret = SpinJSON.loads(BHAPI_raw(path, args = args, max_tries = max_tries, retry_delay = retry_delay,
                                   verbose = verbose))
    if 'error' in ret:
        raise BHAPIException(ret['error'])
    return ret['result']

if __name__ == '__main__':
    print BHAPI_raw('/user/9ccffa07-7195-410b-b058-c29812f85dda')
