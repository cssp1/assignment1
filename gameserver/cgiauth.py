#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# CGI script that handles the Google login process

import cgi, cgitb
import sys, os, time, datetime, functools
import urlparse
import pymongo # 3.0+ OK
import SpinConfig
import SpinGoogleAuth

def format_http_time(stamp):
    return time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(stamp))

def gen_csrf_state(tbl, remote_host):
    state = ''.join([('%02x' % ord(c)) for c in os.urandom(16)])
    tbl.create_index('created', expireAfterSeconds=300)
    tbl.insert_one({'_id':state, 'created':datetime.datetime.utcnow(), 'host': remote_host})
    return state

def check_csrf_state(tbl, remote_host, returned_state):
    return tbl.delete_one({'_id':returned_state, 'host': remote_host}).deleted_count >= 1

if __name__ == "__main__":
    if (not SpinConfig.config.get('secure_mode',False)):
        cgitb.enable()

    args = cgi.parse() or {}
    remote_addr = os.getenv('REMOTE_ADDR') or 'local'
    MY_DOMAIN = SpinConfig.config['spin_token_domain'] # domain used for cookie
    time_now = int(time.time())
    url_parts = urlparse.urlparse(os.getenv('REQUEST_URI'))
    path = url_parts.path.split('/')
    if not path[0]: path = path[1:]
    if not path[-1]: path = path[:-1]
    assert len(path) == 1
    assert path[0] == 'AUTH'

    my_endpoint = 'https://'+SpinConfig.config['proxyserver']['external_listen_host']+':'+str(SpinConfig.config['proxyserver']['external_ssl_port'])+'/AUTH'

    if 'mongodb_servers' in SpinConfig.config:
        dbconfig = SpinConfig.get_mongodb_config(SpinConfig.config.get('spin_token_db', 'AUTH'))
        dbcon = pymongo.MongoClient(*dbconfig['connect_args'], **dbconfig['connect_kwargs'])
        db = dbcon[dbconfig['dbname']]
        tbl = db[dbconfig['table_prefix']+'csrf_state']
    else:
        print "need mongodb_servers config for AUTH"
        sys.exit(1)

    print 'Content-Type: text/html'
    print 'Pragma: no-cache, no-store'
    print 'Cache-Control: no-cache, no-store'

    if ('code' not in args): # first hit
        final_url = args['final_url'][-1]
        final_url_domain = SpinGoogleAuth.url_to_domain(final_url)
        if not (final_url_domain == MY_DOMAIN or final_url_domain.endswith('.'+MY_DOMAIN)):
            print
            print 'can only give auth for URLs within %s' % MY_DOMAIN
            sys.exit(0)

        print
        print SpinGoogleAuth.google_auth_prompt_redirect(SpinConfig.config['google_client_id'],
                                                         my_endpoint, csrf_state = gen_csrf_state(tbl, remote_addr), final_url = final_url)
        sys.exit(0)

    else:
        result = SpinGoogleAuth.exchange_code_for_access_token(SpinConfig.config['google_client_id'],
                                                               SpinConfig.config['google_client_secret'],
                                                               my_endpoint, args,
                                                               csrf_state_checker = functools.partial(check_csrf_state, tbl, remote_addr))
        if 'redirect' in result:
            time.sleep(1)
            print
            print result['redirect']
            sys.exit(0)
        elif 'error' in result:
            print
            print result['error']
            sys.exit(0)

        auth = SpinGoogleAuth.auth_spinpunch_user(result['access_token'], result['expires_in'],
                                                  SpinGoogleAuth.get_google_user_info(result['access_token']),
                                                  SpinConfig.config['realm_users'],
                                                  SpinConfig.config['spin_token_realm'],
                                                  SpinConfig.config['spin_token_secret'],
                                                  time_now)
        if auth['spin_token']:
            spin_token = auth['spin_token']
            # good auth, redirect to resource
            final_url = result['final_url']
            cookie_name = SpinGoogleAuth.spin_token_cookie_name()
            cookie_expires = format_http_time(auth['expires_at'])
            print 'Set-Cookie: %s=%s;domain=.%s;path=/;expires=%s;' % (cookie_name, spin_token, MY_DOMAIN, cookie_expires)
            print
            print '<html><body onload="location.href = \'%s\';">Authenticated! Loading %s...</body></html>' % (final_url, final_url)
            sys.exit(0)
        else:
            print
            print auth['info_html']
            sys.exit(0)

    # shouldn't get here
    print
    print 'auth fail'
