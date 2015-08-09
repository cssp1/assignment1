#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import os, sys, math, random, functools, glob
import string, re, hmac, hashlib, gzip, cStringIO
import time
import signal
import urllib
import urlparse
import socket
import traceback

# on Linux, try to use Twisted's high-performance epoll reactor
if sys.platform == 'linux2':
    from twisted.internet import epollreactor
    epollreactor.install()

from twisted.internet import reactor, task, defer, protocol
from twisted.web import proxy, resource, static, http, twcgi
import twisted.web.error
import twisted.web.server
from twisted.python import log

# handle different Twisted versions that moved NoResource around
if hasattr(twisted.web.resource, 'NoResource'):
    TwistedNoResource = twisted.web.resource.NoResource
else:
    TwistedNoResource = twisted.web.error.NoResource

import TwistedLatency

from urllib import quote as urlquote
import AsyncHTTP
import Daemonize
import SpinJSON
import SpinSSL
import SpinHTTP
import SpinFacebook
import SpinKongregate
import BrowserDetect
import SpinLog
import SpinNoSQL
import SpinNoSQLLog
import SocialIDCache
import SpinConfig
import SpinPasswordProtection
import SpinSignature
import SpinGoogleAuth
import SpinGeoIP

proxy_daemonize = ('-n' not in sys.argv)
verbose_in_argv = ('-v' in sys.argv)
proxy_pidfile = 'proxyserver.pid'
proxy_log_dir = SpinConfig.config.get('log_dir', 'logs')

# GLOBALS

db_client = None
social_id_table = None
geoip_client = SpinGeoIP.SpinGeoIP()
raw_log = None
metrics_log = None
exception_log = None
facebook_log = None
kongregate_log = None
armorgames_log = None
fbrtapi_raw_log = None
fbrtapi_json_log = None
xsapi_raw_log = None
xsapi_json_log = None
proxy_time = -1

def update_time():
    global proxy_time
    proxy_time = int(time.time())
    if db_client:
        db_client.set_time(proxy_time)

update_time()
proxy_launch_time = proxy_time

def format_http_time(stamp):
    return time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(stamp))

const_one_year = 60*60*24*365

fb_async_http = None
if SpinConfig.config.get('enable_facebook', 0):
    config = SpinConfig.config['proxyserver'].get('AsyncHTTP_Facebook', {})
    fb_async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',30), 0,
                                                 lambda x: facebook_log.event(proxy_time, x) if facebook_log else sys.stderr.write(x+'\n'),
                                                 max_tries = config.get('max_tries',1),
                                                 retry_delay = config.get('retry_delay',3))
kg_async_http = None
if SpinConfig.config.get('enable_kongregate', 0):
    config = SpinConfig.config['proxyserver'].get('AsyncHTTP_Kongregate', {})
    kg_async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',30), 0,
                                                 lambda x: kongregate_log.event(proxy_time, x) if kongregate_log else sys.stderr.write(x+'\n'),
                                                 max_tries = config.get('max_tries',1),
                                                 retry_delay = config.get('retry_delay',3))
ag_async_http = None
if SpinConfig.config.get('enable_armorgames', 0):
    config = SpinConfig.config['proxyserver'].get('AsyncHTTP_ArmorGames', {})
    ag_async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',30), 0,
                                                 lambda x: armorgames_log.event(proxy_time, x) if armorgames_log else sys.stderr.write(x+'\n'),
                                                 max_tries = config.get('max_tries',1),
                                                 retry_delay = config.get('retry_delay',3))

control_async_http = None
config = SpinConfig.config['proxyserver'].get('AsyncHTTP_CONTROLAPI', {})
control_async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',300),
                                                  -1,
                                                  lambda x: exception_log.event(proxy_time, x),
                                                  max_tries = config.get('max_tries',1),
                                                  retry_delay = config.get('retry_delay',10))

# clean session-/auth-flow-specific parameters out of a uri query string
def clean_qs(uri, add_props = None):
    parts = urlparse.urlparse(uri)
    q = urlparse.parse_qs(parts.query)
    for UNWANTED in ('state', 'code', 'signed_request'):
        if UNWANTED in q: del q[UNWANTED]
    if add_props:
        for k, v in add_props.iteritems():
            q[k] = v
    return urllib.urlencode([(k,v[-1]) for k,v in q.iteritems()]) if q else ''

def q_clean_qs(*args, **kwargs):
    ret = clean_qs(*args, **kwargs)
    return ('?'+ret) if ret else ''

class GameServer:
    def __init__(self, name, host, port, ssl_port, ws_port, wss_port):
        self.name = name
        self.host = host
        self.port = port
        self.ssl_port = ssl_port
        self.ws_port = ws_port
        self.wss_port = wss_port
        self.accept_new_connections = True
        self.affinities = None

    def __repr__(self):
        if self.ws_port > 0 or self.wss_port > 0:
            ws_port_info = ' WS %5d/%5d' % (self.ws_port, self.wss_port)
        else:
            ws_port_info = ''
        if self.affinities:
            affinity_info = ' aff '+repr(self.affinities)
        else:
            affinity_info = ''
        return '%-20s on port %5d/%5d%s (proxying %d sessions) %s' % (self.name, self.port, self.ssl_port, ws_port_info, session_load.get_by_server(self.name),
                                                                      '(OPEN%s)' % affinity_info if self.accept_new_connections else '(CLOSED)')

# cache in-memory versions of the small files that are statically included in the game index page
static_includes = None
def reload_static_includes():
    global static_includes
    STATIC_INCLUDE_FILES = ['proxy_index.html', 'index_body_fb.html', 'index_body_kg.html', 'index_body_ag.html', 'kg_guest.html', 'fb_guest.html',
                            'BrowserDetect.js', 'SPLWMetrics.js',
                            'FacebookSDK.js', 'KongregateSDK.js', 'ArmorGamesSDK.js', 'facebookexternalhit.html',
                            'XsollaSDK.js']
    new_includes = dict([(basename, str(open('../gameclient/'+basename).read())) for basename in STATIC_INCLUDE_FILES])
    static_includes = new_includes
def get_static_include(name):
    return static_includes[name]

def verbose():
    if verbose_in_argv:
        return 1
    return SpinConfig.config['proxyserver'].get('verbose',0)

def metric_event_coded(visitor, event_name, props):
    props['code'] = int(event_name[0:4])
    props['event_name'] = event_name
    if visitor: props['anon_id'] = visitor.anon_id
    metrics_log.event(proxy_time, props)
    if verbose():
        print 'metric_event(%d,' % proxy_time, props, ')'

def uniqid(prefix='', more_entropy=False):
    m = time.time()
    uniqid = '%8x%05x' %(math.floor(m),(m-math.floor(m))*1000000)
    if more_entropy:
        valid_chars = list(set(string.hexdigits.lower()))
        entropy_string = ''
        for i in range(0,10,1):
            entropy_string += random.choice(valid_chars)
        uniqid = uniqid + entropy_string
    uniqid = prefix + uniqid
    return uniqid

unique_session_counter = 0

def generate_session_id():
    global unique_session_counter
    unique_session_counter += 1
    return hashlib.sha256('SP!NP0NCH' + str(time.time()) + str(unique_session_counter)).hexdigest()[32:64]


def parse_host_port(hostport, is_ssl):
    if ':' in hostport:
        host, port = hostport.split(':')
    else:
        host = hostport
        if is_ssl:
            port = '443'
        else:
            port = '80'
    if is_ssl:
        protocol = 'https://'
    else:
        protocol = 'http://'
    return (protocol, host, port)

def get_http_origin(visitor, is_ssl):
    ret = visitor.server_protocol + visitor.server_host
    if (is_ssl and visitor.server_port == '443') or \
       ((not is_ssl) and visitor.server_port == '80'):
        pass
    else:
        ret += ':' + visitor.server_port
    return ret

# inject original host/port/ssl info into custom HTTP headers so that
# the server behind the proxy knows where the request originally came from

def add_proxy_headers(request):
    orig_protocol, orig_host, orig_port = parse_host_port(SpinHTTP.get_twisted_header(request, 'host') or 'unknown', request.isSecure())
    SpinHTTP.set_twisted_header(request,'spin-orig-protocol',orig_protocol)
    SpinHTTP.set_twisted_header(request,'spin-orig-host',orig_host)
    SpinHTTP.set_twisted_header(request,'spin-orig-port',orig_port)
    SpinHTTP.set_twisted_header(request,'spin-orig-uri',request.uri)
    SpinHTTP.set_twisted_header(request,'spin-orig-ip',request.getClientIP() or 'unknown')
    SpinHTTP.set_twisted_header(request,'spin-orig-referer',SpinHTTP.get_twisted_header(request, 'referer') or 'unknown')

def dump_request(request):
    print 'REQUEST', request
    print 'HEADERS', repr(request.requestHeaders)
    print 'COOKIES', request.received_cookies
    print 'ARGS', request.args
    #print 'CONTENT', str(request.content)

def log_request(request):
    ret = repr(request)+ \
          ' args '+repr(request.args)+ \
          ' cookies '+repr(request.received_cookies)+ \
          ' user-agent "'+SpinHTTP.get_twisted_header(request,'user-agent')+ \
          '" ip ' + repr(request.getClientIP())
    return ret

def set_cookie(request, cookie_name, value, duration):
    request.addCookie(cookie_name, value, expires = format_http_time(proxy_time+duration))
    # necessary for IE7+ to accept iframed cookies
    request.setHeader('P3P', 'CP="CAO DSP CURa ADMa DEVa TAIa PSAa PSDa IVAi IVDi CONi OUR UNRi OTRi BUS IND PHY ONL UNI COM NAV INT DEM CNT STA PRE GOV LOC"')

def visitors_browser_supports_xhr_eval(visitor):
    ag = visitor.demographics.get('User-Agent',None)
    if not ag: return False
    return BrowserDetect.browser_supports_xhr_eval(BrowserDetect.get_browser(ag))


# this is for anti-spam ONLY

class IPRecord(object):
    def __init__(self, ip):
        self.ip = ip
        self.attempts = []
        self.lockout_until = -1

    def prune(self):
        lookback = SpinConfig.config['proxyserver'].get('ip_spam_lookback',60)
        if lookback <= 0:
            self.attempts = []
        else:
            while len(self.attempts) > 0 and self.attempts[0] < (proxy_time - lookback):
                self.attempts.remove(self.attempts[0])
        return len(self.attempts) > 0
    def add_attempt(self, t):
        self.prune()
        self.attempts.append(t)
        lookback = SpinConfig.config['proxyserver'].get('ip_spam_lookback',60)
        max_count = SpinConfig.config['proxyserver'].get('ip_spam_max_count',60)
        penalty = SpinConfig.config['proxyserver'].get('ip_spam_penalty_time', 60)

        if max_count <= 0:
            return False
        if self.lockout_until > 0 and proxy_time < self.lockout_until:
            if penalty > 0 and SpinConfig.config['proxyserver'].get('ip_spam_penalty_cumulative', True):
                self.lockout_until = proxy_time + penalty
            return True
        count = 0
        for t in self.attempts:
            if t >= (proxy_time - lookback):
                count += 1
        if count >= max_count:
            if penalty > 0:
                self.lockout_until = proxy_time + penalty
            return True
        return False

ip_table = {}

# Visitors are used for remembering state across repeated calls to / (root)
# during the login process ONLY. After login, you become a Session, not a Visitor.
# Visitors are NOT persisted in the cross-instance database, they're local to one proxyserver.
# This doesn't handle the rare edge case where you start the login/auth process on one server
# and then finish it on another.

class Visitor(object):
    def __init__(self, request, anon_id):
        self.anon_id = anon_id
        self.social_id = None

        self.demographics = {'ip': 'unknown',
                             'country': 'unknown'}
        self.last_active_time = 0
        self.first_hit_uri = None
        self.game_container = None

        self.server_protocol = None
        self.server_host = None
        self.server_port = None

    def update_on_hit(self, request):
        self.last_active_time = proxy_time
        self.update_campaign_data(request)
        if 'locale_override' in request.args:
            self.demographics['locale'] = request.args['locale_override'][0]
        self.demographics['User-Agent'] = SpinHTTP.get_twisted_header(request, 'user-agent') or 'unknown'
        self.demographics['ip'] = request.getClientIP() or 'unknown'
        self.browser_info = BrowserDetect.get_browser(self.demographics['User-Agent'])

        # canonical protocol/host/port for game server (in case browser needs to reload it)
        self.server_protocol, self.server_host, self.server_port = \
                              parse_host_port(SpinHTTP.get_twisted_header(request, 'host') or 'unknown', request.isSecure())

        if self.first_hit_uri is None:
            self.set_first_hit(request)

    def update_campaign_data(self, request):
        # init campaign data
        if 'spin_campaign' in request.args:
            self.demographics['campaign_name'] = request.args['spin_campaign'][0]
            MAP = {'spin_ge': 'age_group', 'spin_aimg': 'acquisition_ad_image',
                   'spin_attl': 'acquisition_ad_title', 'spin_atxt': 'acquisition_ad_text',
                   'spin_tgt': 'acquisition_ad_target', 'spin_atgt': 'acquisition_ad_skynet'}
            for key, val in MAP.iteritems():
                if key in request.args:
                    self.demographics[val] = request.args[key][0]

        elif 'campaign' in request.args:
            self.demographics['campaign_name'] = request.args['campaign'][0]

    # save "pure" URI of first hit (for carrying campaign data and other query parameters across an auth redirect)
    def set_first_hit(self, request):
        self.first_hit_uri = request.uri
        # construct URI to parent frame container
        # note: append query parameters from original URI, possibly including ad campaign data
        self.set_game_container(request)

    def add_demographics(self, props):
        props.update(self.demographics)
        if self.browser_info:
            for FIELD in ('OS', 'name', 'version', 'hardware'):
                if ('browser_'+FIELD not in props) and (FIELD in self.browser_info):
                    props['browser_'+FIELD] = self.browser_info[FIELD]
        return props

    def __repr__(self):
        print_dict = dict((k,v) for k,v in self.__dict__.iteritems() if k not in ('raw_signed_request', 'oauth_token', 'kongregate_auth_token', 'armorgames_auth_token'))
        return self.anon_id + ' (active %ds ago): ' % (proxy_time-self.last_active_time) + repr(print_dict)

class FBVisitor(Visitor):
    def __init__(self, *args, **kwargs):
        Visitor.__init__(self, *args, **kwargs)
        self.frame_platform = self.demographics['frame_platform'] = 'fb'
        self.facebook_id = None
        self.scope_string = None # comma-separated permissions
        self.oauth_token = None
        self.raw_signed_request = None
        self.csrf_state = None

    def set_facebook_id(self, fbid):
        if fbid:
            self.facebook_id = str(fbid)
            self.demographics['social_id'] = self.social_id = 'fb'+self.facebook_id
            #self.demographics['facebook_id'] = self.facebook_id
        else:
            self.facebook_id = None
            self.social_id = None
            if 'social_id' in self.demographics: del self.demographics['social_id']
            #if 'facebook_id' in self.demographics: del self.demographics['facebook_id']

    def add_demographics(self, props):
        props = Visitor.add_demographics(self, props)
        if self.scope_string is not None:
            props['scope'] = self.scope_string
        return props

    def auth_token(self): return self.oauth_token

    def immune_to_country_restrictions(self):
        return self.facebook_id in SpinConfig.config.get('facebook_id_whitelist', [])

    def must_go_away(self):
        return ('go_away_whitelist' in SpinConfig.config) and (self.facebook_id not in SpinConfig.config['go_away_whitelist'])

    def set_game_container(self, request):
        self.game_container = self.server_protocol + 'apps.facebook.com/' + SpinConfig.config['facebook_app_namespace'] + '/' + q_clean_qs(request.uri)

    # canvas_url is the URL for the CONTENTS of the iframe, used for refreshing/reloading the game - SHOULD include signed_request
    def canvas_url(self):
        return self.server_protocol + self.server_host + ':' + self.server_port + '/' + q_clean_qs(self.first_hit_uri,
                                                                                                   add_props = {'signed_request':[self.raw_signed_request,]} if self.raw_signed_request else None)

class KGVisitor(Visitor):
    def __init__(self, *args, **kwargs):
        Visitor.__init__(self, *args, **kwargs)
        self.frame_platform = self.demographics['frame_platform'] = 'kg'
        self.kongregate_id = None
        self.kongregate_username = None
        self.kongregate_auth_token = None
        self.kongregate_game_url = None
        self.kongregate_game_id = None

    def set_kongregate_id(self, kgid):
        self.kongregate_id = str(kgid)
        self.demographics['social_id'] = self.social_id = 'kg'+self.kongregate_id

    def auth_token(self): return self.kongregate_auth_token
    def immune_to_country_restrictions(self): return False
    def must_go_away(self):
        return ('go_away_whitelist' in SpinConfig.config) and (self.kongregate_id not in SpinConfig.config['go_away_whitelist'])

    def set_game_container(self, request):
        if 'kongregate_game_url' in request.args:
            self.game_container = request.args['kongregate_game_url'][0] + q_clean_qs(request.uri)
        else:
            self.game_container = 'http://www.spinpunch.com' # punt :(

    def canvas_url(self):
        return self.server_protocol + self.server_host + ':' + self.server_port + '/KGROOT' + q_clean_qs(self.first_hit_uri,
                                                                                                         {'kongregate_username':[self.kongregate_username,],
                                                                                                          'kongregate_user_id': [self.kongregate_id,],
                                                                                                          'kongregate_game_auth_token': [self.kongregate_auth_token,],
                                                                                                          'kongregate_game_id': [self.kongregate_game_id,],
                                                                                                          'kongregate_game_url': [self.kongregate_game_url,],
                                                                                                          })
    def canvas_url_no_auth(self):
        # send the browser the URL to redirect to after authorizing
        assert self.kongregate_game_id and self.kongregate_game_url
        return self.server_protocol + self.server_host + ':' + self.server_port + '/KGROOT' + q_clean_qs(self.first_hit_uri,
                                                                                                         {'kongregate_username':['__KONGREGATE_USERNAME__',],
                                                                                                          'kongregate_user_id': ['__KONGREGATE_USER_ID__',],
                                                                                                          'kongregate_game_auth_token': ['__KONGREGATE_GAME_AUTH_TOKEN__',],
                                                                                                          'kongregate_game_id': [self.kongregate_game_id,],
                                                                                                          'kongregate_game_url': [self.kongregate_game_url,],
                                                                                                          })

class AGVisitor(Visitor):
    def __init__(self, *args, **kwargs):
        Visitor.__init__(self, *args, **kwargs)
        self.frame_platform = self.demographics['frame_platform'] = 'ag'
        self.armorgames_id = None
        self.armorgames_auth_token = None

    def set_armorgames_id(self, agid):
        self.armorgames_id = str(agid)
        self.demographics['social_id'] = self.social_id = 'ag'+self.armorgames_id

    def auth_token(self): return self.armorgames_auth_token
    def immune_to_country_restrictions(self): return False
    def must_go_away(self):
        return ('go_away_whitelist' in SpinConfig.config) and (self.armorgames_id not in SpinConfig.config['go_away_whitelist'])

    def set_game_container(self, request):
        self.game_container = 'http://www.spinpunch.com' # punt :(

    def canvas_url(self):
        return self.server_protocol + self.server_host + ':' + self.server_port + '/AGROOT' + q_clean_qs(self.first_hit_uri, {})

    def canvas_url_no_auth(self):
        # send the browser the URL to redirect to after authorizing
        return self.server_protocol + self.server_host + ':' + self.server_port + '/AGROOT' + q_clean_qs(self.first_hit_uri, {})

visitor_table = {}

# Currently active GAMEAPI sessions

def controlapi_url(gameserver_host, gameserver_port):
    return 'http://%s:%d/CONTROLAPI' % (gameserver_host, gameserver_port)

class ProxySession(object):
    # note: make local copies of some server fields at creation, so
    # that this object does not rely on a reference to the GameServer
    # (since that is going to be replaced by live database queries).
    def __init__(self, session_id, user_id, social_id, ip, gameserver_name, gameserver_host, gameserver_port):
        self.session_id = session_id
        self.user_id = user_id
        self.social_id = social_id
        self.ip = ip
        self.last_active_time = 0
        self.gameserver_name = gameserver_name # name of assigned server, for debugging and (old) load balancing
        self.gameserver_fwd = (gameserver_host, gameserver_port) # where to forward proxied GAMEAPI/CREDITAPI/etc requests
        self.gameserver_ctrl= controlapi_url(gameserver_host, gameserver_port) # endpoint for CONTROLAPI requests


    def __repr__(self):
        return self.session_id[:4] + '... user %5d %15s (active %ds ago on %s)' % (self.user_id, repr(self.ip), proxy_time-self.last_active_time, self.gameserver_name)

# keep track of outstanding async session termination requests, so that we can cancel overlapped ones
# this is for user convenience (making sure the last login attempt wins, if several arrive in a row)
# but it does not affect correctness (the session table ensures atomic logins). So, it does not need to
# be shared across processes.
async_terminations = {}

# track number of sessions assigned by server name for load-balancing purposes (in old static mode)
class SessionLoad(object):
    def __init__(self):
        self.by_server = {}
    def get_by_server(self, server_name):
        return len(self.by_server.get(server_name, []))
    def add(self, server_name, session_id):
        if server_name not in self.by_server:
            self.by_server[server_name] = set()
        self.by_server[server_name].add(session_id)
    def remove(self, server_name, session_id):
        if server_name in self.by_server:
            self.by_server[server_name].discard(session_id)
            if len(self.by_server[server_name]) <= 0:
                del self.by_server[server_name]

session_load = SessionLoad()

def collect_garbage():

    # delete state IPRecords
    for rec in ip_table.values():
        if not rec.prune():
            del ip_table[rec.ip]

    # delete stale Visitor records
    visitor_timeout = SpinConfig.config['proxyserver'].get('visitor_timeout',900)
    for visitor in visitor_table.values():
        if (proxy_time - visitor.last_active_time) >= visitor_timeout:
            del visitor_table[visitor.anon_id]

    # delete stale ProxySessions
    session_timeout = SpinConfig.config['proxyserver'].get('session_timeout', 600)
    db_client.sessions_prune(session_timeout)
    # kill sessions attached to dead servers?

class GameProxyClient(proxy.ProxyClient):
    pass

class GameProxyClientFactory(proxy.ProxyClientFactory):
    noisy = False
    protocol = GameProxyClient
    def clientConnectionFailed(self, connector, reason):
        print 'connection to game server failed! ', reason
        return proxy.ProxyClientFactory.clientConnectionFailed(self, connector, reason)


# launch an external process that sends out notifications when payments are disputed
# "response" = the JSON for the payment graph object

class PaymentDisputeProcess(protocol.ProcessProtocol):
    def __init__(self, exe, response):
        self.exe = exe
        self.response = response
        self.error = ''
    def connectionMade(self):
        self.transport.write(SpinJSON.dumps(self.response, newline=True))
        self.transport.closeStdin()
    def errReceived(self, data):
        self.error += data
    def processEnded(self, status):
        if not isinstance(status.value, twisted.internet.error.ProcessDone):
            exception_log.event(proxy_time, 'error running %s: %s\n%s' % (self.exe, repr(status), self.error))
        else:
            exception_log.event(proxy_time, '%s was run successfully' % (self.exe,))

def send_payment_dispute_notification(response, user_id, dry_run = False):
    s_amount = 'unknown'
    s_currency = 'unknown'
    for action in response['actions']:
        if ('currency' in action) and ('amount' in action):
            s_currency = action['currency']
            s_amount = action['amount']
            break
    exception_log.event(proxy_time, 'DISPUTE payment %s player %d paid_amount %s paid_currency %s' % \
                        (response['id'], user_id, s_amount, s_currency))
    exe = './payment_dispute_notification.py'
    args = [exe, str(user_id)]
    if dry_run: args.append('--dry-run')
    reactor.spawnProcess(PaymentDisputeProcess(exe, response), exe, args=args, env=os.environ)


class GameProxy(proxy.ReverseProxyResource):
    proxyClientFactoryClass = GameProxyClientFactory

    def __init__(self, path):
        # note: host and port are reset on a per-request basis in render()
        proxy.ReverseProxyResource.__init__(self, None, None, path)

    def getChild(self, path, request):
        if verbose():
            print 'getChild', 'self.path', self.path, 'path', path, 'postpath', request.postpath
        return GameProxy(self.path + '/' + urlquote(path, safe=''))
        # disabled since static file requests are not forwarded
        return None

    def render_ROOT(self, request, frame_platform = None):
        update_time()

        request.setHeader('Pragma','no-cache, no-store')
        request.setHeader('Cache-Control','no-cache, no-store')
        request.setHeader('Expires','0')

        if SpinConfig.config['proxyserver'].get('use_http_keep_alive', True) and \
           (SpinHTTP.get_twisted_header(request,'connection').lower() == 'keep-alive'):
            request.setHeader('Connection', 'keep-alive')
            request.setHeader('Keep-Alive', 'timeout=%d' % SpinConfig.config['proxyserver'].get('http_connection_timeout', 300))

        SpinHTTP.set_access_control_headers(request)

        # check for spam from this IP
        ip = request.getClientIP()
        if ip:
            if ip in ip_table:
                rec = ip_table[ip]
            else:
                rec = IPRecord(ip)
                ip_table[ip] = rec
            if rec.add_attempt(proxy_time):
                print 'blocked login spam from %s' % repr(ip)
                return self.index_visit_login_spam()

        # check for overload condition
        if control_async_http.num_on_wire() >= SpinConfig.config['proxyserver'].get('AsyncHTTP_CONTROLAPI', {}).get('max_in_flight',100):
            return self.index_visit_server_overload()

        if verbose() >= 2:
            print '============= ROOT ============='
            dump_request(request)

        reflect_cookie = 'SP_QS'

        # check for cookie-reflect landing
        if (reflect_cookie in request.received_cookies) and SpinConfig.config['proxyserver'].get('enable_reflect_cookie_landing',True):
            new_args = urlparse.parse_qs(request.received_cookies[reflect_cookie])
            metric_event_coded(None, '0011_reflect_cookie_landing', {'Viewed URL': request.uri, 'ip': request.getClientIP(), 'referer': SpinHTTP.get_twisted_header(request, 'referer'), 'args': request.args, 'new_args': new_args})
            for k, v in new_args.iteritems():
                if k not in request.args:
                    request.args[k] = v

        # check for cookie-reflect launch
        elif ('spin_rfl' in request.args) and SpinConfig.config['proxyserver'].get('enable_reflect_cookie_launch',True):
            new_qs = urllib.urlencode([(k,v[-1]) for k,v in request.args.iteritems() if (k.startswith('spin_') and k != 'spin_rfl')])
            set_cookie(request, reflect_cookie, new_qs, SpinConfig.config['proxyserver'].get('reflect_cookie_duration',300))
            metric_event_coded(None, '0010_reflect_cookie_launch', {'Viewed URL': request.uri, 'ip': request.getClientIP(), 'referer': SpinHTTP.get_twisted_header(request, 'referer'), 'args': request.args})
            return self.index_visit_redirect(request.args['spin_rfl'][-1])

        return self.index_visit(request, frame_platform)

    def index_visit(self, request, frame_platform):
        # check for anon ID cookie
        cookie_name = 'spin_anon_id2_'+str(SpinConfig.config['game_id']) + '_' + frame_platform

        if (cookie_name in request.received_cookies) and \
           SpinSignature.AnonID.verify(request.received_cookies[cookie_name], proxy_time, request.getClientIP(), frame_platform, SpinConfig.config['proxy_api_secret']):
            anon_id = request.received_cookies[cookie_name]
            #exception_log.event(proxy_time, 'proxyserver: recognized cookie '+anon_id)
        else:
            # generate anon ID
            duration = SpinConfig.config['proxyserver'].get('anon_id_duration', 600)
            anon_id = SpinSignature.AnonID.create(proxy_time + duration,
                                                  request.getClientIP(), frame_platform, SpinConfig.config['proxy_api_secret'], str(random.randint(0,100000)))
            set_cookie(request, cookie_name, anon_id, duration)
            #exception_log.event(proxy_time, 'proxyserver: NEW cookie '+anon_id)

        if anon_id not in visitor_table:
            visitor_table[anon_id] = visitor = {'fb': FBVisitor, 'kg': KGVisitor, 'ag': AGVisitor}[frame_platform](request, anon_id)
        else:
            visitor = visitor_table[anon_id]

        visitor.update_on_hit(request)
        return {'fb': self.index_visit_fb, 'kg': self.index_visit_kg, 'ag': self.index_visit_ag}[frame_platform](request, visitor)

    def index_visit_kg(self, request, visitor):
        # example hit:
        # http://myserver.example.com:8005/KGROOT
        # ?DO_NOT_SHARE_THIS_LINK=1
        # &kongregate_username=...
        # &kongregate_user_id=...
        # &kongregate_game_auth_token=...
        # &kongregate_game_id=...
        # &kongregate_host=http://www.kongregate.com
        # &kongregate_game_url=http://www.kongregate.com/games/../appname
        # &kongregate_api_host=http://api.kongregate.com
        # &kongregate_channel_id=...
        # &kongregate_api_path=http://chat.kongregate.com/flash/API_AS3_....swf
        # &kongregate_ansible_path=chat.kongregate.com/flash/ansible_....swf
        # &kongregate_preview=true
        # &kongregate_language=en
        # &preview=true
        # &kongregate_split_treatments=none
        # &kongregate=true
        # &KEEP_THIS_DATA_PRIVATE=1

        # always set these parameters so the post-auth redirect can work
        if ('kongregate_game_url' in request.args) and ('kongregate_game_id' in request.args):
            visitor.kongregate_game_url = str(request.args['kongregate_game_url'][0])
            visitor.kongregate_game_id = str(request.args['kongregate_game_id'][0])

        valid = True
        skip_verify = False

        for FIELD in ('kongregate_username', 'kongregate_user_id', 'kongregate_game_auth_token', 'kongregate_game_id', 'kongregate_game_url'):
            if FIELD not in request.args:
                valid = False
                break

        if valid and int(request.args['kongregate_user_id'][0]) < 1:
            # reject unregistered guests
            return self.index_visit_kg_auth_redirect(request, visitor)

        if not valid:
            # random non-game hit
            if ((not SpinConfig.config.get('enable_kongregate',0)) or (request.args.get('kongregate_username',['invalid'])[0] == 'Guest')) \
               and (not SpinConfig.config.get('secure_mode',0)): # do not allow in secure mode
                # use fake sandbox credentials
                # note: match server.py retrieve_kg_info() test credentials
                skip_verify = True
                request.args['kongregate_username'] = ['example1']
                request.args['kongregate_user_id'] = ['12345']
                request.args['kongregate_game_auth_token'] = ['123456789']
                request.args['kongregate_game_id'] = ['54321']
                request.args['kongregate_game_url'] = ['http://www.kongregate.com/games/example1/test-game']
                visitor.kongregate_game_url = str(request.args['kongregate_game_url'][0])
                visitor.kongregate_game_id = str(request.args['kongregate_game_id'][0])
            else:
                if visitor.kongregate_game_url and visitor.kongregate_game_id:
                    return self.index_visit_kg_auth_redirect(request, visitor)
                else:
                    request.setResponseCode(http.BAD_REQUEST)
                    return str('kongregate_game_url and kongregate_game_id parameters required')

        visitor.set_kongregate_id(request.args['kongregate_user_id'][0])
        visitor.kongregate_username = str(request.args['kongregate_username'][0])
        visitor.kongregate_auth_token = str(request.args['kongregate_game_auth_token'][0])

        # geolocate country
        visitor.demographics['country'] = geoip_client.get_country(request.getClientIP())

        if self.the_pool_is_closed():
            return self.index_visit_go_away(request, visitor)

        metric_event_coded(visitor, '0020_page_view',
                           visitor.add_demographics({#'Viewed URL': request.uri,
                                                     'query_string': clean_qs(request.uri),
                                                     'referer': SpinHTTP.get_twisted_header(request, 'referer') or 'unknown',
                                                     'kongregate_user_id': visitor.kongregate_id
                                                     }))
        if skip_verify:
            return self.index_visit_authorized(request, visitor)
        else:
            return self.index_visit_kg_verify(request, visitor)

    def index_visit_kg_auth_redirect(self, request, visitor):
        replacements = {
            '$CANVAS_URL$': visitor.canvas_url_no_auth(),
            '$KG_GUEST_IMAGE$': SpinConfig.config['proxyserver'].get('kg_guest_image', ''),
            '$KG_GUEST_BG_COLOR$': SpinConfig.config['proxyserver'].get('kg_guest_bg_color', '#acb2b7'),
            }
        expr = re.compile('|'.join([key.replace('$','\$') for key in replacements.iterkeys()]))
        template = get_static_include('kg_guest.html')
        return str(expr.sub(lambda match: replacements[match.group(0)], template))

    def index_visit_kg_verify(self, request, visitor):
        d = defer.Deferred()
        d.addBoth(self.complete_deferred_request, request)
        vc = self.KGVerifyCheck(self, request, visitor, d)
        kg_async_http.queue_request(proxy_time,
                                    'https://www.kongregate.com/api/authenticate.json?'+urllib.urlencode({'user_id':visitor.kongregate_id,
                                                                                                          'game_auth_token':visitor.kongregate_auth_token,
                                                                                                          'api_key':SpinConfig.config['kongregate_api_key']}),
                                    vc.on_response, error_callback = vc.on_error)
        return twisted.web.server.NOT_DONE_YET

    class KGVerifyCheck:
        def __init__(self, parent, request, visitor, d):
            self.parent = parent
            self.request = request
            self.visitor = visitor
            self.d = d
        def on_response(self, response):
            self.d.callback(self.parent.index_visit_kg_verify_response(self.request, self.visitor, response))
        def on_error(self, reason):
            self.d.callback(self.parent.index_visit_kg_verify_response(self.request, self.visitor, '{"success":false}', allow_user_retry = False))

    def index_visit_kg_verify_response(self, request, visitor, response, preload_data = None, allow_user_retry = True):
        r = SpinJSON.loads(response)
        if not r.get('success',False):
            if allow_user_retry:
                return self.index_visit_kg_auth_redirect(request, visitor)
            else:
                return self.index_visit_go_away(request, visitor)

        return self.index_visit_authorized(request, visitor)

    def index_visit_ag(self, request, visitor):
        # example hit:
        # http://myserver.example.com:8005/AGROOT?user_id=0000abcd&auth_token=something

        valid = True
        skip_verify = False

        for FIELD in ('user_id', 'auth_token'):
            if FIELD not in request.args:
                valid = False
                break

        if not valid:
            # random non-game hit
            if not SpinConfig.config.get('enable_armorgames',0) \
               and (not SpinConfig.config.get('secure_mode',0)): # do not allow in secure mode
                # use fake sandbox credentials
                # note: match server.py retrieve_ag_info() test credentials
                skip_verify = True
                request.args['user_id'] = ['example2' if 'james' in request.args else 'example1']
                request.args['auth_token'] = ['123456789']
            else:
                request.setResponseCode(http.BAD_REQUEST)
                return str('user_id and auth_token parameters required')

        visitor.set_armorgames_id(request.args['user_id'][0])
        visitor.armorgames_auth_token = str(request.args['auth_token'][0])

        # geolocate country
        visitor.demographics['country'] = geoip_client.get_country(request.getClientIP())

        if self.the_pool_is_closed():
            return self.index_visit_go_away(request, visitor)

        metric_event_coded(visitor, '0020_page_view',
                           visitor.add_demographics({#'Viewed URL': request.uri,
                                                     'query_string': clean_qs(request.uri),
                                                     'referer': SpinHTTP.get_twisted_header(request, 'referer') or 'unknown',
                                                     'armorgames_user_id': visitor.armorgames_id
                                                     }))
        if skip_verify:
            return self.index_visit_authorized(request, visitor)
        else:
            return self.index_visit_ag_verify(request, visitor)

    def index_visit_ag_verify(self, request, visitor):
        d = defer.Deferred()
        d.addBoth(self.complete_deferred_request, request)
        vc = self.AGVerifyCheck(self, request, visitor, d)
        ag_async_http.queue_request(proxy_time,
                                    'https://services.armorgames.com/services/rest/v1/authenticate/user.json?' + \
                                    urllib.urlencode({'user_id':visitor.armorgames_id,
                                                      'auth_token':visitor.armorgames_auth_token,
                                                      'api_key':SpinConfig.config['armorgames_api_key']}),
                                    vc.on_response, error_callback = vc.on_error)
        return twisted.web.server.NOT_DONE_YET

    class AGVerifyCheck:
        def __init__(self, parent, request, visitor, d):
            self.parent = parent
            self.request = request
            self.visitor = visitor
            self.d = d
        def on_response(self, response):
            self.d.callback(self.parent.index_visit_ag_verify_response(self.request, self.visitor, response))
        def on_error(self, reason):
            self.d.callback(self.parent.index_visit_ag_verify_response(self.request, self.visitor, '{"payload":null,"message":"SpinPunch error"}'))

    def index_visit_ag_verify_response(self, request, visitor, response):
        r = SpinJSON.loads(response)
        # ArmorGames docs say to use payload being null or non-null as the way to determine if a login is valid
        # https://docs.google.com/document/pub?id=1oewk-9Y8yLTUohxCK5by-clEg7qy7-U05FVeC-lSRIc
        if not r.get('payload',None):
            return self.index_visit_go_away(request, visitor)
        return self.index_visit_authorized(request, visitor)

    def index_visit_fb(self, request, visitor):

        # check for signed_request (either sent as POST arg or GET query string)
        if 'signed_request' in request.args:
            visitor.raw_signed_request = request.args['signed_request'][-1]
        elif (not SpinConfig.config.get('enable_facebook',0)) and (not SpinConfig.config.get('secure_mode',0)):
            # Facebook not enabled, use fake test user

            visitor.raw_signed_request = SpinFacebook.make_signed_request({'user_id':'example2' if ('james' in request.args) else 'example1', # note: must match test-facebook-profile.txt
                                                                           'algorithm':'HMAC-SHA256',
                                                                           'expires': proxy_time+86400,
                                                                           'oauth_token': '123456789',
                                                                           'user': {'locale': 'en_US', 'country': 'us', 'age': {'min': 21}}, 'issued_at': proxy_time},
                                                                          SpinConfig.config['facebook_app_secret'])
        else:
            # but don't reset oauth info
            pass

        if visitor.raw_signed_request:

            try:
                signed_request = SpinFacebook.parse_signed_request(visitor.raw_signed_request, SpinConfig.config['facebook_app_secret'])
            except:
                exception_log.event(proxy_time, 'proxyserver: Failure parsing signed_request "%s":\n%sfrom request %s' % (visitor.raw_signed_request, traceback.format_exc(), log_request(request)))
                signed_request = None
                # but don't reset oauth info

            # check expiration time of signed request
            if signed_request:
                if signed_request.has_key('expires') and \
                   int(signed_request['expires']) > 0 and \
                   (proxy_time >= int(signed_request['expires'])) and \
                   SpinConfig.config.get('enable_facebook',0):
                    # request was expired - send user back to auth
                    raw_log.event(proxy_time, ('browser presented an expired Facebook signed request (expires at %d, current time %d): ' % (int(signed_request['expires']), proxy_time))+log_request(request))
                    signed_request = None
                    # don't reset?
                    #visitor.oauth_token = None

            if signed_request:
                if verbose():
                    raw_log.event(proxy_time, 'got signed request from %s: %s' % (repr(visitor.demographics['ip']), repr(signed_request)))

                if 'user' in signed_request:
                    udata = signed_request['user']
                    if 'country' in udata:
                        visitor.demographics['country'] = udata['country']
                    if 'locale' in udata and ('locale' not in visitor.demographics):
                        visitor.demographics['locale'] = udata['locale']


                # test option for testing the oauth token fetch path
                if SpinConfig.config['proxyserver'].get('code_overrides_signed_request',False):
                    if 'oauth_token' in signed_request and ('code' in request.args):
                        if 'user_id' in signed_request: del signed_request['user_id']
                        del signed_request['oauth_token']


                if 'user_id' in signed_request:
                    visitor.set_facebook_id(signed_request['user_id'])
                else:
                    visitor.set_facebook_id(None)

                if 'oauth_token' in signed_request:
                    visitor.oauth_token = signed_request['oauth_token']

                else:
                    # don't reset?
                    # visitor.oauth_token = None
                    pass

        if self.the_pool_is_closed(): # note: this needs "country" demographic info
            return self.index_visit_go_away(request, visitor)

        if ('go_away_whitelist' in SpinConfig.config) and visitor.facebook_id and (visitor.facebook_id not in SpinConfig.config['go_away_whitelist']):
            return self.index_visit_go_away(request, visitor)


        if (not visitor.raw_signed_request):
            if SpinHTTP.get_twisted_header(request,'user-agent').startswith('facebookexternalhit'):
                replacements = {
                    '$FBEXTERNALHIT_TITLE$': SpinConfig.config['proxyserver'].get('fbexternalhit_title', 'SpinPunch'),
                    '$FBEXTERNALHIT_IMAGE$': SpinConfig.config['proxyserver'].get('fbexternalhit_image', ''),
                    '$FBEXTERNALHIT_DESCRIPTION$': SpinConfig.config['proxyserver'].get('fbexternalhit_description', ''),
                    }
                expr = re.compile('|'.join([key.replace('$','\$') for key in replacements.iterkeys()]))
                template = get_static_include('facebookexternalhit.html')
                return str(expr.sub(lambda match: replacements[match.group(0)], template))

            # no signed_request was sent!
            raw_log.event(proxy_time, 'index hit that did not come with a Facebook signed request: '+log_request(request))

            # if it's truly a random web spider and not a real Facebook visitor, return HTTP 400 Bad Request
            if ('spin_ref' not in request.args) and ('spin_campaign' not in request.args) and ('fb_source' not in request.args):
                request.setResponseCode(http.BAD_REQUEST)
                return str('no signed_request')

        metric_event_coded(visitor, '0020_page_view',
                           visitor.add_demographics({#'Viewed URL': request.uri,
                                                     'query_string': clean_qs(request.uri),
                                                     'referer': SpinHTTP.get_twisted_header(request, 'referer') or 'unknown',
                                                     'signed_request': visitor.raw_signed_request
                                                     }))

        # visitors are not considered "logged in" until we get their Facebook ID AND a valid oauth token
        # this MIGHT come together inside the signed_request, or we might have to retrieve them if we get a "code" argument (after an auth redirect)

        if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 2:
            exception_log.event(proxy_time, 'index visitor: fbid "%s" oauth_token "%s" args: %s' % (repr(visitor.facebook_id), repr(visitor.oauth_token), repr(request.args)))

        if visitor.facebook_id and visitor.oauth_token:
            if SpinConfig.config.get('enable_facebook',0): # and SpinConfig.config['proxyserver'].get('check_auth_scope', True): this is mandatory now, to pass permissions proxy->client->server
                # perform deferred /permissions check
                return self.index_visit_check_scope(request, visitor)
            else:
                # immediate entry to game
                return self.index_visit_authorized(request, visitor)

        if 'code' in request.args:
            # we got a code with which to retrieve an oauth token
            code = request.args['code'][0]

            if visitor.csrf_state and SpinConfig.config['proxyserver'].get('csrf_protection',True) and \
               (('state' not in request.args) or (request.args['state'][-1] != visitor.csrf_state)):
                exception_log.event(proxy_time, 'got auth code with bad CSRF state: '+repr(request)+' args '+repr(request.args)+' wanted '+visitor.csrf_state)
                code = None

            if code:
                return self.index_visit_fetch_oauth_token(request, visitor, code)

        # fall back to auth request
        return self.index_visit_do_fb_auth(request, visitor)

    # this is the final Deferred callback that finishes asynchronous HTTP request handling
    # note that "body" is inserted by Twisted as the return value of the callback chain.
    def complete_deferred_request(self, body, request):
        if body == twisted.web.server.NOT_DONE_YET:
            return body
        assert type(body) in (str, unicode)
        if hasattr(request, '_disconnected') and request._disconnected: return
        request.write(body)
        request.finish()

    #
    # ASYNC CALL TO /oauth/access_token TO GET AN OAUTH TOKEN
    #

    def index_visit_fetch_oauth_token(self, request, visitor, code):
        # asynchronously call Facebook API to retrieve an oauth_token using the "code" from the auth redirect
        d = defer.Deferred()
        d.addBoth(self.complete_deferred_request, request)
        sc = self.OAuthGetter(self, request, visitor, d)

        url = SpinFacebook.versioned_graph_endpoint('oauth', 'oauth')

        url += '/access_token?' + \
               urllib.urlencode({'client_id':SpinConfig.config['facebook_app_id'],
                                 'redirect_uri':visitor.game_container,
                                 'client_secret':SpinConfig.config['facebook_app_secret'],
                                 'code':code
                                 })
        if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 2:
            exception_log.event(proxy_time, 'fetching OAuth token: ' + url)
        fb_async_http.queue_request(proxy_time, url, sc.on_response, error_callback = sc.on_error)
        return twisted.web.server.NOT_DONE_YET

    class OAuthGetter:
        def __init__(self, parent, request, visitor, d):
            self.parent = parent
            self.request = request
            self.visitor = visitor
            self.d = d
        def on_response(self, response):
            self.d.callback(self.parent.index_visit_fetch_oauth_token_response(self.request, self.visitor, response))
        def on_error(self, reason):
            self.d.callback(self.parent.index_visit_fetch_oauth_token_response(self.request, self.visitor, ''))

    def index_visit_fetch_oauth_token_response(self, request, visitor, response):
        # note: "response" is JSON for errors, otherwise a string
        if response and (response[0] != '{') and ('access_token' in response):
            data = urlparse.parse_qs(response)
            # note! we don't have facebook_id yet!
            return self.index_visit_verify_oauth_token(request, visitor, data['access_token'][0])
        # fail back to auth re-request
        raw_log.event(proxy_time, 'failed to fetch oauth token: '+repr(request)+' args '+repr(request.args)+' signed_request '+repr(visitor.raw_signed_request)+' response '+repr(response))
        return self.index_visit_do_fb_auth(request, visitor)

    #
    # ASYNC CALL TO /debug_token TO VERIFY TOKEN AND GET FACEBOOK_ID AND SCOPE
    #

    def index_visit_verify_oauth_token(self, request, visitor, token):
        # asynchronously call Facebook API to verify an oauth_token and get its associated facebook_id
        d = defer.Deferred()
        d.addBoth(self.complete_deferred_request, request)
        sc = self.OAuthVerifier(self, request, visitor, token, d)
        url = SpinFacebook.versioned_graph_endpoint('oauth', 'debug_token') + '?' + \
              urllib.urlencode({'input_token':token,
                                'access_token': SpinConfig.config['facebook_app_access_token'],
                                })
        if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 2:
            exception_log.event(proxy_time, 'verifying OAuth token: ' + url)
        fb_async_http.queue_request(proxy_time, url, sc.on_response, error_callback = sc.on_error)
        return twisted.web.server.NOT_DONE_YET

    class OAuthVerifier:
        def __init__(self, parent, request, visitor, token, d):
            self.parent = parent
            self.request = request
            self.visitor = visitor
            self.token = token
            self.d = d
        def on_response(self, response):
            self.d.callback(self.parent.index_visit_verify_oauth_token_response(self.request, self.visitor, self.token, response))
        def on_error(self, reason):
            self.d.callback(self.parent.index_visit_verify_oauth_token_response(self.request, self.visitor, self.token, 'false'))

    def index_visit_verify_oauth_token_response(self, request, visitor, token, response):
        response = SpinJSON.loads(response)
        # carefully check for a valid token

        if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 3:
            exception_log.event(proxy_time, 'proxyserver: index_visit_verify_oauth_token_response() facebook ID %s response %s' % (visitor.facebook_id, response))

        if type(response) is dict and ('data' in response):
            data = response['data']
            if str(data.get('app_id','')) == SpinConfig.config['facebook_app_id']:
                if ('expires_at' not in data) or (data['expires_at'] <= 0) or (data['expires_at'] > proxy_time):
                    if data.get('is_valid',0):
                        if ('user_id' in data) and data['user_id'] and ('scopes' in data):
                            # OK, we're confident this token will work now
                            visitor.set_facebook_id(data['user_id'])
                            visitor.oauth_token = token

                            # reformat the returned auth scopes into the same form as /permissions gives, so we can skip the roundtrip
                            scope_data = dict((x,1) for x in data['scopes'])
                            scope_data['installed'] = 1
                            scope_data['public_profile'] = 1
                            return self.index_visit_check_scope_response(request, visitor, None, preload_data = scope_data)

        # fail, request auth again
        exception_log.event(proxy_time, 'failed to verify oauth token: '+repr(request)+' args '+repr(request.args)+' signed_request '+repr(visitor.raw_signed_request)+' token '+repr(token)+' response '+repr(response))
        return self.index_visit_do_fb_auth(request, visitor)

    #
    # ASYNC CALL TO /permissions TO GET CURRENT PERMISSIONS
    #

    def index_visit_check_scope(self, request, visitor):
        d = defer.Deferred()
        d.addBoth(self.complete_deferred_request, request)
        sc = self.ScopeCheck(self, request, visitor, d)
        sc.go()
        return twisted.web.server.NOT_DONE_YET

    class ScopeCheck:
        def __init__(self, parent, request, visitor, d):
            self.parent = parent
            self.request = request
            self.visitor = visitor
            self.d = d
            self.attempt = 0
        def go(self):
            fb_async_http.queue_request(proxy_time,
                                        SpinFacebook.versioned_graph_endpoint('user/permissions', str(self.visitor.facebook_id)+'/permissions')+'?'+urllib.urlencode({'access_token':SpinConfig.config['facebook_app_access_token']}),
                                        self.on_response, error_callback = self.on_error)
            if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 3:
                exception_log.event(proxy_time, 'proxyserver: index_visit_check_scope(attempt %d) facebook ID %s' % (self.attempt, self.visitor.facebook_id))

        def on_response(self, response):
            self.d.callback(self.parent.index_visit_check_scope_response(self.request, self.visitor, response))

        def on_error(self, reason):
            if reason and ('500' in reason) and ('"is_transient":true' in reason) and self.attempt < 1:
                # manually retry - this does not use the normal
                # AsyncHTTP retry mechanism, since we want most
                # failures (e.g. 400 Bad Request) to give up
                # immediately, in order to not delay the user's login
                # process any further. However, a 500 Internal Server Error should be retried at least once.
                self.attempt += 1
                self.go()
                return

            # in the event of an API failure, return a fake JSON response that encodes the error so that we can detect and handle it below
            self.d.callback(self.parent.index_visit_check_scope_response(self.request, self.visitor,
                                                                         '{"data":[{"permission":"spin_error","status":'+SpinJSON.dumps(reason)+'}]}',
                                                                         allow_user_retry = False))

    # allow_user_retry means "you can kick the user back to the do_auth page"
    def index_visit_check_scope_response(self, request, visitor, response, preload_data = None, allow_user_retry = True):
        auth_scope = SpinConfig.config.get('facebook_auth_scope', 'email')
        min_scope = SpinConfig.config.get('facebook_auth_scope_min', '')

        if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 3:
            exception_log.event(proxy_time, 'proxyserver: index_visit_check_scope_response() facebook ID %s error preload_data %s response %s auth_scope %s min_scope %s' % (visitor.facebook_id, preload_data, response, auth_scope, min_scope))

        perms_ok = False
        data_list = []
        try:
            if (preload_data is not None) or response:
                if preload_data is not None:
                    data_list = [preload_data]
                else:
                    data_list = SpinJSON.loads(response)['data']
                if len(data_list) > 0:
                    if 'permission' in data_list[0]:
                        perm_map = dict([(x['permission'],1) for x in data_list if x.get('status',None) == 'granted'])
                    else:
                        perm_map = dict([(k,1) for k,v in data_list[0].iteritems() if v])

                    if perm_map.get('spin_error',0):
                        pass # API call failure, leave perms_ok False
                    elif perm_map.get('installed',0) or perm_map.get('public_profile',0):
                        # good, user has installed the game
                        perms_ok = True
                        for perm in auth_scope.split(','):
                            if not perm_map.get(perm, 0):
                                is_mandatory = (perm in min_scope.split(','))
                                if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 2:
                                    exception_log.event(proxy_time, '%s permission %s missing from user %s (has %s)' % (('mandatory' if is_mandatory else 'optional'), perm, visitor.facebook_id, repr(perm_map)))
                                if is_mandatory:
                                    perms_ok = False
                                    break

        except:
            perms_ok = False
            if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 0:
                exception_log.event(proxy_time, 'proxyserver: index_visit_check_scope_response() facebook ID %s exception %s' % (visitor.facebook_id, traceback.format_exc()))

        if not perms_ok:
            if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 1:
                exception_log.event(proxy_time, 'proxyserver: index_visit_check_scope_response() facebook ID %s perms_ok False allow_user_retry %s data_list %s' % (visitor.facebook_id, repr(allow_user_retry), repr(data_list)))

            if allow_user_retry:
                return self.index_visit_do_fb_auth(request, visitor)
            else:
                return self.index_visit_denied_auth(request, visitor)

        visitor.scope_string = ','.join(k for k,v in perm_map.iteritems() if v)
        return self.index_visit_authorized(request, visitor)

    #
    # FAILED TO AUTHORIZE - REDIRECT BROWSER TO OAUTH DIALOG
    #

    def index_visit_do_fb_auth(self, request, visitor):
        scope = SpinConfig.config.get('facebook_auth_scope', 'email')

        # see if this is a failed attempt
        if 'error' in request.args:
            metric_event_coded(visitor, '0920_user_denied_auth', visitor.add_demographics({'scope':scope}))
            return self.index_visit_denied_auth(request, visitor)

        # create anti-CSRF state that Facebook should pass back to us
        # but use same one for repeated attempts in one session, in case of reload bugs
        if not visitor.csrf_state:
            visitor.csrf_state = hashlib.sha256(SpinConfig.config['facebook_app_secret']+'666'+str(visitor.anon_id)+str(proxy_time)).hexdigest()

        method = SpinConfig.config['proxyserver'].get('fb_auth_method', 'fb_guest_page')
        metric_props = visitor.add_demographics({'scope':scope, 'method': method})

        if visitor.first_hit_uri:
            metric_props['query_string'] = clean_qs(visitor.first_hit_uri)


        if method == 'oauth_redirect': # old method
            redirect_url = SpinFacebook.versioned_graph_endpoint('dialog/oauth','dialog/oauth',
                                                                 subdomain = 'www', protocol = visitor.server_protocol)

            # note: FB's handling of the response_type arg is weird, it wants code%20token for the combined one
            redirect_url += '?'+urllib.urlencode({'client_id': SpinConfig.config['facebook_app_id'],
                                                  'redirect_uri': visitor.game_container,
                                                  'state': visitor.csrf_state,
                                                  'scope': scope }) + '&response_type=' + SpinConfig.config['proxyserver'].get('fb_auth_response_type', 'code')

            # redirect (with frame break) to redirect_url
            if SpinConfig.config['proxyserver'].get('log_auth_scope', 0) >= 2:
                exception_log.event(proxy_time, 'do_auth: %s from %s' % (repr(redirect_url), traceback.format_stack()))

            ret = '<html><body onload="top.location.href = \'%s\';"></body></html>' % str(redirect_url)

        elif method == 'fb_guest_page':
            # use fb_guest.html - NOTE! probably requires Login API v2.0+
            replacements = self.get_fb_global_variables(request, visitor)
            screen_name, screen_data = get_loading_screen('fb_guest')
            replacements['$FACEBOOK_GUEST_SPLASH_IMAGE$'] = SpinJSON.dumps(screen_data)
            metric_props['splash_image'] = screen_name
            expr = re.compile('|'.join([key.replace('$','\$') for key in replacements.iterkeys()]))
            ret = str(expr.sub(lambda match: replacements[match.group(0)], get_static_include('fb_guest.html')))

        else:
            raise Exception('unknown FB auth method '+method)

        metric_event_coded(visitor, '0030_request_permission', metric_props)
        return ret

    # check visitor's whitelist/blacklist status
    def is_visitor_prohibited(self, visitor):

        # first check if player's ID is whitelisted - this overrides every other check
        if visitor.immune_to_country_restrictions():
            if verbose():
                print 'user is whitelisted'
            return False
        else:
            if 'country_whitelist' in SpinConfig.config:
                if visitor.demographics['country'] not in SpinConfig.config['country_whitelist']:
                    if verbose():
                        print 'not in country whitelist'
                    return True
            if visitor.demographics['country'] in SpinConfig.config.get('country_blacklist', []):
                if verbose():
                    print 'in country blacklist'
                return True
        return False

    def is_visitor_throttled(self, request, visitor):
        # throttle low-Tier logins if system is overloaded
        if True: return False # XXXXXX unimplemented with dynamic routing
        throttle_sessions = SpinConfig.config.get('throttle_sessions', -1)
        if (throttle_sessions >= 0) and False: # XXX (len(session_table) >= throttle_sessions)
            country = visitor.demographics['country']
            whitelist = SpinConfig.config.get('throttle_country_whitelist', None)
            if whitelist and (country in whitelist):
                return False
            country_tier = SpinConfig.country_tier_map.get(country, 4)
            if country_tier in SpinConfig.config.get('throttle_country_tiers', []):
                throttle_sources = SpinConfig.config.get('throttle_acquisition', None)
                source = ''
                if throttle_sources:
                    try:
                        q = urlparse.parse_qs(urlparse.urlparse(request.uri).query)
                        if q.has_key('fb_source'):
                            source = q['fb_source'][0]
                    except:
                        pass

                if (throttle_sources is None) or (source in throttle_sources):
                    raw_log.event(proxy_time, 'proxyserver: session overload! denied login to socid %s source "%s" (%s tier %d)' % \
                                  (visitor.social_id, source, country, country_tier))
                    return True
        return False

    def index_visit_redirect(self, redirect_url):
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_prohibited_country(self, request, visitor):
        metric_event_coded(visitor, '0930_prohibited_country', visitor.add_demographics({}))
        redirect_url = SpinConfig.config['proxyserver'].get('prohibited_country_landing', '//www.spinpunch.com/')
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_go_away(self, request, visitor):
        redirect_url = SpinConfig.config['proxyserver'].get('server_maintenance_landing', '//www.spinpunch.com/server-maintenance/')
        if ('country' in visitor.demographics) and ('server_maintenance_landing_country_override' in SpinConfig.config['proxyserver']):
            for entry in SpinConfig.config['proxyserver']['server_maintenance_landing_country_override']:
                if visitor.demographics['country'] in entry['countries']:
                    redirect_url = entry['url']
                    break
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_denied_auth(self, request, visitor):
        redirect_url = SpinConfig.config['proxyserver'].get('user_denied_auth_landing', None)
        if not redirect_url: return self.index_visit_go_away(request, visitor)
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_server_overload(self):
        redirect_url = SpinConfig.config['proxyserver'].get('server_overload_landing', '//www.spinpunch.com/mars-frontier-server-overload/')
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_login_spam(self):
        redirect_url = SpinConfig.config['proxyserver'].get('login_spam_landing', '//www.spinpunch.com/login-spam/')
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_race_condition(self, request, visitor):
        redirect_url = SpinConfig.config['proxyserver'].get('login_race_condition_landing', '//www.spinpunch.com/login-race-condition/')
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_coming_soon(self, request, visitor):
        redirect_url = SpinConfig.config['proxyserver'].get('coming_soon_landing', '//www.spinpunch.com/coming-soon-to-your-country/')
        return '<html><body onload="location.href = \'%s\';"></body></html>' % str(redirect_url)

    def index_visit_authorized(self, request, visitor):
        if not visitor.social_id:
            # this can happen when the Facebook fetch_oauth_token API fails
            request.setResponseCode(http.BAD_REQUEST)
            return str('error')

        if self.is_visitor_prohibited(visitor):
            return self.index_visit_prohibited_country(request, visitor)

        if self.is_visitor_throttled(request, visitor):
            return self.index_visit_coming_soon(request, visitor)

        if visitor.must_go_away():
            return self.index_visit_go_away(request, visitor)

        # apply auth to sandbox servers
        if (not SpinConfig.config.get('enable_facebook',0)) and \
           (not SpinConfig.config.get('enable_kongregate',0)) and \
           (not SpinConfig.config.get('enable_armorgames',0)) and \
           (not SpinGoogleAuth.twisted_request_is_local(request)) and (SpinConfig.config['proxyserver'].get('require_google_auth',1)):
            auth_info = SpinGoogleAuth.twisted_do_auth(request, 'GAME', proxy_time)
            if not auth_info['ok']:
                if 'redirect' in auth_info:
                    return str(auth_info['redirect'])
                else:
                    return str(auth_info['error'])

        return self.index_visit_game(request, visitor)

    def the_pool_is_closed(self):
        # global kill switch
        if SpinConfig.config.get('the_pool_is_closed',False): return True
        return False # dynamic routing does not use this path

    def assign_game_server(self, request, visitor):
        # note: visitor may be None for METRICSAPI requests

        # determine visitor's country affinity
        affinity = 'default'
        if visitor:
            country = visitor.demographics.get('country',None)
            if country and ('server_affinities' in SpinConfig.config):
                for key, val in SpinConfig.config['server_affinities'].iteritems():
                    if country in val:
                        affinity = key
                        break

        force_name = request.args['force_server'][0] if ('force_server' in request.args) else None

        return self.assign_game_server_dynamic(force_name, affinity)

    def assign_game_server_dynamic(self, force_name, affinity):
        qs = {'type':SpinConfig.game(), 'state':'ok',
              'gamedata_build': proxysite.proxy_root.static_resources['gamedata-%s-en_US.js' % SpinConfig.game()].build_date,
              'gameclient_build': proxysite.proxy_root.static_resources['compiled-client.js'].build_date}
        if force_name:
            qs['_id'] = force_name
        else:
            qs['affinities'] = affinity
        rows = db_client.server_status_query(qs, fields = {'_id':1, 'hostname':1, 'game_http_port':1, 'game_ssl_port':1, 'game_ws_port':1, 'game_wss_port':1, 'server_time':1}, sort = 'load', limit = 1)
        if rows and rows[0]:
            data = rows[0]
            return GameServer(data['server_name'], data['hostname'], data['game_http_port'], data['game_ssl_port'], data['game_ws_port'], data['game_wss_port'])
        return None

    def start_async_termination(self, request, session_id, user_id, server_name, ctrl_url, cb, reason = ''):
        # asynchronously ask the server to log out an existing
        # session, and remove it from the session table once it is
        # definitely logged out
        qs = urllib.urlencode(dict(secret = str(SpinConfig.config['proxy_api_secret']),
                                   method = 'terminate_session',
                                   session_id = session_id))
        url = ctrl_url+'?'+qs

        def handle_response(self, session_id, user_id, server_name, wait_count, cb, explanation, response_or_error):
            if type(response_or_error) is str: response_or_error = response_or_error.strip()
            success = (response_or_error == 'ok')
            if success:
                db_client.session_drop_by_session_id(session_id) # XXX redundant with server?
            else:
                exception_log.event(proxy_time, 'warning: CONTROLAPI returned unexpected result from server %s: %s for request %s' % \
                                    (server_name, repr(response_or_error), explanation))

            is_latest = wait_count >= async_terminations[user_id]['last']
            async_terminations[user_id]['count'] -= 1
            if async_terminations[user_id]['count'] <= 0:
                del async_terminations[user_id]
            cb(success, is_latest)

        # ugly - track both the last-created serial number (for determining who "wins" an overlapped series of termination requests)
        # as well as the count of outstanding requests (for garbage collection)
        if user_id not in async_terminations:
            async_terminations[user_id] = {'count':0, 'last':0}
        async_terminations[user_id]['last'] = wait_count = async_terminations[user_id]['last'] + 1
        async_terminations[user_id]['count'] += 1

        handler = functools.partial(handle_response, self, session_id, user_id, server_name, wait_count, cb, 'terminate_session %s user %d count %d' % (session_id, user_id, wait_count))
        control_async_http.queue_request(proxy_time, url, handler, error_callback = handler)
        if verbose(): print 'forcefully terminating for', reason, 'user', user_id, 'server', server_name, 'session', session_id, 'wait_count', wait_count

    # XXX emulate in-memory session table with MongoDB backend
    def session_emulate(self, info):
        if not info: return None
        srvinfo = info['server_info']
        ret = ProxySession(info['session_id'], info['_id'], info['social_id'],
                           info['ip'], srvinfo['server_name'], srvinfo['hostname'], srvinfo['game_http_port'])
        ret.last_active_time = info['last_active_time']
        return ret
    def session_insert_dynamic(self, session, server):
        old_info = db_client.session_insert(session.session_id, session.user_id, session.social_id, session.ip,
                                            {'server_name':server.name, 'hostname':server.host, 'game_http_port':server.port,
                                             'game_ssl_port':server.ssl_port, 'game_ws_port':server.ws_port, 'game_wss_port':server.wss_port},
                                            session.last_active_time)
        return self.session_emulate(old_info)

    def index_visit_game(self, request, visitor):
        # this could be delayed to after the async portion, if we update the session after the async completes
        # (and we accept the race where a second request can't async terminate because the server is not chosen yet)
        server = self.assign_game_server(request, visitor)
        if server is None:
            # no servers available
            return self.index_visit_go_away(request, visitor)

        # create and insert user_id
        user_id = social_id_table.social_id_to_spinpunch(visitor.social_id, True)
        visitor.demographics['user_id'] = user_id

        # note: we're remembering the gameserver's HTTP port no matter what protocol the client is using,
        # since this is for proxy forwarding
        session = ProxySession(generate_session_id(), user_id, visitor.social_id, visitor.demographics['ip'],
                               server.name, server.host, server.port)
        session.last_active_time = proxy_time

        # to avoid simultaneous logins, we have to make sure the session table is clear of any sessions on this user_id
        # if any are found, make an asynchronous call to CONTROLAPI and wait until the server finishes flushing the player
        # before continuing the login attempt. If we hit a pre-existing login a second time, give up.
        old_session = self.session_insert_dynamic(session, server)

        if old_session:
            # invalidate the old session on this user, then try again
            d = defer.Deferred()
            d.addBoth(self.complete_deferred_request, request)
            if verbose(): print 'encountered old session on %s for %d, invalidating %s...' % (old_session.gameserver_name, user_id, old_session.session_id)

            # prev_session here is just for debugging messages
            def callback(self, request, visitor, session, prev_session, server, d, success, is_latest):
                if not success: # CONTROLAPI call failed
                    if verbose(): print 'invalidate: CONTROLAPI failure on server %s user %d session %s' % (prev_session.gameserver_name, session.user_id, prev_session.session_id)
                    session_load.remove(session.gameserver_name, session.session_id)
                    ret = self.index_visit_server_overload()
                else:
                    if not is_latest:
                        # another async termination took priority - do not proceed
                        if verbose(): print 'invalidate: replaced by later request user %d session %d' % (session.user_id, session.session_id)
                        session_load.remove(session.gameserver_name, session.session_id)
                        ret = self.index_visit_race_condition(request, visitor)
                    else:
                        old_session = self.session_insert_dynamic(session, server)

                        if old_session:
                            if verbose(): print 'invalidate: still blocked user %d' % session.user_id
                            # still blocked - give up
                            session_load.remove(session.gameserver_name, session.session_id)
                            ret = self.index_visit_race_condition(request, visitor)
                        else:
                            if verbose(): print 'invalidate: OK! prev server %s prev session %s new server %s user %d session %s' % (prev_session.gameserver_name, prev_session.session_id, session.gameserver_name, session.user_id, session.session_id)
                            # is the latest login attempt
                            ret = self.index_visit_game_complete(request, visitor, session, server)

                d.callback(ret)

            self.start_async_termination(request, old_session.session_id, old_session.user_id,
                                         old_session.gameserver_name, old_session.gameserver_ctrl,
                                         functools.partial(callback, self, request, visitor, session, old_session, server, d),
                                         reason = 'index_visit')
            return twisted.web.server.NOT_DONE_YET

        # ordinary synchronous path
        return self.index_visit_game_complete(request, visitor, session, server)

    # return dictionary of strings to replace in the Facebook page template
    def get_fb_global_variables(self, request, visitor):
        http_origin = get_http_origin(visitor, request.isSecure())
        # pull promo codes out of request.uri since we need to tack those on to the query string
        extra_query_params = {}
        request_q = urlparse.parse_qs(urlparse.urlparse(request.uri).query)
        if 'spin_promo_code' in request_q:
            extra_query_params['spin_promo_code'] = request_q['spin_promo_code']
        game_query_string = clean_qs(visitor.first_hit_uri if SpinConfig.config.get('secure_mode',0) else request.uri, add_props = extra_query_params)
        replacements = {
            '$DEMOGRAPHICS$': SpinJSON.dumps(visitor.demographics),
            '$FBEXTERNALHIT_TITLE$': SpinConfig.config['proxyserver'].get('fbexternalhit_title', 'SpinPunch'),
            '$FBEXTERNALHIT_IMAGE$': SpinConfig.config['proxyserver'].get('fbexternalhit_image', ''),
            '$FBEXTERNALHIT_DESCRIPTION$': SpinConfig.config['proxyserver'].get('fbexternalhit_description', ''),
            '$CANVAS_URL$': visitor.canvas_url(), # https://apps.facebook.com/MYAPP/
            '$GAME_CONTAINER_URL$': visitor.game_container, # https://apps.facebook.com/MYAPP/?original_query_string=goes_here
            # query string sent with GAMEAPI requests - should NOT include signed_request
            '$GAME_QUERY_STRING$': game_query_string,
            # might need to add a $GAME_REFERER$ here
            '$APP_NAMESPACE$': SpinConfig.config['facebook_app_namespace'],
            '$APP_ID$': SpinConfig.config.get('facebook_app_id',''),
            '$TRIALPAY_VENDOR_ID$': SpinConfig.config.get('trialpay_vendor_id',''),
            '$HTTP_ORIGIN$': ("'"+http_origin+"'") if http_origin else 'null',
            '$SERVER_PROTOCOL$': visitor.server_protocol,
            '$SERVER_HOST$': visitor.server_host,
            '$SERVER_PORT$': visitor.server_port,
            '$ANON_ID$': visitor.anon_id,
            '$FACEBOOK_API_VERSIONS$': SpinJSON.dumps(SpinConfig.config.get('facebook_api_versions', {})) if 'facebook_api_versions' in SpinConfig.config else 'null',
            '$FACEBOOK_AUTH_SCOPE$': SpinConfig.config.get('facebook_auth_scope', 'email'),
            '$ART_PATH$': SpinConfig.config['proxyserver'].get('art_cdn_path', None),
            '$ART_PROTOCOL$': SpinConfig.config['proxyserver'].get('art_protocol', None) or '',
            '$BROWSERDETECT_CODE$': get_static_include('BrowserDetect.js'),
            '$SPLWMETRICS_CODE$': get_static_include('SPLWMetrics.js'),
            }
        return replacements

    def index_visit_game_complete(self, request, visitor, session, server):
        if verbose():
            print 'new game session for user_id', session.user_id, 'social_id', '"'+visitor.social_id+'"', 'on', server.name, 'session', session.session_id

        art_protocol = SpinConfig.config['proxyserver'].get('art_protocol', None)
        art_path = SpinConfig.config['proxyserver'].get('art_cdn_path', None)

        # the page request won't have an Origin: header, but we can figure it out
        http_origin = get_http_origin(visitor, request.isSecure())

        if SpinConfig.config['proxyserver'].get('high_latency_tiers', None):
            if ('country' in visitor.demographics) and \
               SpinConfig.country_tier_map.get(visitor.demographics['country'], 4) in SpinConfig.config['proxyserver']['high_latency_tiers']:
                ajax_config = 'high_latency'
            else:
                ajax_config = 'default'
        else:
            ajax_config = 'default'

        # these strings are appended to the main HTML body onload() callback.
        # used to manually kick off spin_try_start() when game code is loaded inline (for non-compiled mode)
        onload = []

        # return a chunk of JavaScript that creates a new script
        # element asynchronously and sets its own onload callback to
        # spin_try_start(module).
        def make_async_js_load(art_protocol, art_path, http_origin, visitor, script, script_length, module, onload):
            if art_path and SpinConfig.config['proxyserver'].get('cdn_js_files', False):
                script_url = (visitor.server_protocol if not art_protocol else art_protocol) + art_path + script
                if http_origin:
                    script_url += '?' + urllib.urlencode({'spin_origin':http_origin})
            else:
                script_url = visitor.server_protocol + visitor.server_host + ':' + visitor.server_port + '/' + script
            funcname = 'spin_async_load_'+module
            ret = '<script type="text/javascript">\n'
            if SpinConfig.config['proxyserver'].get('xhr_js_files', False) and visitors_browser_supports_xhr_eval(visitor):
                ret += "spin_async_load_progress['"+module+"'][1] = %d;\n" % script_length
                #console.log("YYYYY"""+module+""""+_s.status.toString()+' '+_s.readyState.toString());
                ret += """function """+funcname+"""() {var s = new XMLHttpRequest();
                            if(!('withCredentials' in s) && (typeof XDomainRequest == "object")) {
                                s = new XDomainRequest(); // support IE<10
                                s.contentType = 'text/plain';
                            }
                            s.open('GET', '"""+script_url+"""');
                            if('withCredentials' in s) { s.withCredentials = true; }
                            s.onreadystatechange = s.onload = (function(_s) { return function() {
                                if(_s.status == 200 && _s.readyState == 4) {
                                    if(!spin_"""+module+"""_loaded) { eval.call(window, _s.responseText); spin_"""+module+"""_loaded = true; }
                                    spin_try_start('"""+module+"""');
                                }
                            }; })(s);
                            s.onprogress = (function (_s) { return function(e) {
                                    spin_async_load_progress['"""+module+"""'][0] = e.loaded;
                                    spin_async_load_show_progress();
                            }; })(s);
                            s.send();}"""
            else:
                ret += """function """+funcname+"""() {var s = document.createElement('script');
                            s.type = 'text/javascript';
                            s.async = true;
                            s.onreadystatechange = (function(_s) { return function() {
                                if(_s.readyState == 'complete') { spin_try_start('"""+module+"""'); }
                            }; })(s);
                            s.onload = function() { spin_try_start('"""+module+"""'); };
                            s.src = '"""+script_url+"""';
                            var x = document.getElementsByTagName('script')[0];
                            x.parentNode.insertBefore(s, x);}"""
            ret += '\n</script>'
            onload.append(funcname+'();')
            return ret

        if SpinConfig.config.get('use_compiled_client',0):
            load_game_code = make_async_js_load(art_protocol, art_path, http_origin, visitor,
                                                proxysite.proxy_root.static_resources['compiled-client.js'].add_checksum('compiled-client.js'),
                                                proxysite.proxy_root.static_resources['compiled-client.js'].length(),
                                                'code', onload)
        else:
            load_game_code  = '<script type="text/javascript" src="google/closure/goog/base.js"></script>'
            load_game_code += '<script type="text/javascript" src="generated-deps.js"></script>'
            load_game_code += '<script type="text/javascript">goog.require("SPINPUNCHGAME");</script>'
            # call this directly in page onload because the code is loaded in-line
            onload.append("spin_try_start('code');")

        # look up which gamedata.js to serve
        game_data_js = None
        locale = visitor.demographics.get('locale','en_US')
        for loc in SpinConfig.locales_to_try(locale):
            game_data_js = os.path.basename(SpinConfig.gamedata_filename(locale=loc, extension='.js'))
            if game_data_js in proxysite.proxy_root.static_resources: break

        if game_data_js not in proxysite.proxy_root.static_resources:
            return self.index_visit_prohibited_country(request, visitor)

        load_game_data = make_async_js_load(art_protocol, art_path, http_origin, visitor,
                                            proxysite.proxy_root.static_resources[game_data_js].add_checksum(game_data_js),
                                            proxysite.proxy_root.static_resources[game_data_js].length(),
                                            'gamedata', onload)

        # look up other accounts logged in from the same IP and tell
        # the gameserver about it so that we can detect alt accounts
        possible_alts = db_client.sessions_get_users_by_ip(session.ip)

        if possible_alts:
            extra_data = string.join([str(alt_user_id) for alt_user_id in possible_alts], ',')
        else:
            extra_data = ''

        screen_name, screen_data = get_loading_screen('game')

        # temporary, to ensure sign_session() does not fail
        assert visitor.social_id is not None
        assert visitor.auth_token() is not None
        assert extra_data is not None

        replacements = self.get_fb_global_variables(request, visitor)
        replacements.update({
            '$SERVER_HTTP_PORT$': str(SpinConfig.config['proxyserver']['external_http_port']),
            '$SERVER_SSL_PORT$': str(SpinConfig.config['proxyserver'].get('external_ssl_port',-1)),
            '$GAME_SERVER_HOST$': server.host,
            '$GAME_SERVER_HTTP_PORT$': str(server.port),
            '$GAME_SERVER_SSL_PORT$': str(server.ssl_port),
            '$GAME_SERVER_WS_PORT$': str(server.ws_port),
            '$GAME_SERVER_WSS_PORT$': str(server.wss_port),
            '$DIRECT_CONNECT$': 'true' if SpinConfig.config['proxyserver'].get('direct_connect',0) else 'false',
            '$AJAX_CONFIG$': ajax_config,
            '$USER_ID$': str(session.user_id),
            '$LOGIN_COUNTRY$': visitor.demographics['country'],
            '$SESSION_ID$': session.session_id,
            '$SESSION_TIME$': str(proxy_time),
            '$SESSION_SIGNATURE$': SpinSignature.sign_session(session.user_id, visitor.demographics['country'], session.session_id, proxy_time, server.name, visitor.social_id, visitor.auth_token(), extra_data, SpinConfig.config['proxy_api_secret']),
            '$SESSION_DATA$': extra_data,
            '$SECURE_MODE$': 'true' if SpinConfig.config.get('secure_mode',0) else 'false',
            '$KISSMETRICS_ENABLED$': 'true' if SpinConfig.config.get('enable_kissmetrics',0) else 'false',
            '$FACEBOOK_ENABLED$': 'true' if SpinConfig.config.get('enable_facebook',0) else 'false',
            '$KONGREGATE_ENABLED$': 'true' if SpinConfig.config.get('enable_kongregate',0) else 'false',
            '$ARMORGAMES_ENABLED$': 'true' if SpinConfig.config.get('enable_armorgames',0) else 'false',
            '$FRAME_PLATFORM$': visitor.frame_platform,
            '$SOCIAL_ID$': visitor.social_id,
            '$FACEBOOK_ID$': "'"+visitor.facebook_id+"'" if isinstance(visitor, FBVisitor) else 'null',
            '$ARMORGAMES_ID$': "'"+visitor.armorgames_id+"'" if isinstance(visitor, AGVisitor) else 'null',
            '$KONGREGATE_ID$': "'"+visitor.kongregate_id+"'" if isinstance(visitor, KGVisitor) else 'null',
            '$SIGNED_REQUEST$': "'"+visitor.raw_signed_request+"'" if isinstance(visitor, FBVisitor) else 'null',
            '$FACEBOOK_PERMISSIONS$': visitor.scope_string if (isinstance(visitor, FBVisitor) and visitor.scope_string) else '', # note: client may get more permissions later, this is just the set available upon login
            '$OAUTH_TOKEN$': visitor.auth_token(),
            '$UNSUPPORTED_BROWSER_LANDING$': SpinConfig.config['proxyserver'].get('unsupported_browser_landing', 'http://www.spinpunch.com/approaching-mars/'),

            '$LOAD_GAME_DATA$': load_game_data,
            '$LOAD_GAME_CODE$': load_game_code,
            '$ONLOAD$': string.join(onload,' '),

            '$FACEBOOK_SDK$': get_static_include('FacebookSDK.js') if (visitor.frame_platform == 'fb' and SpinConfig.config.get('enable_facebook',0)) else '',
            '$KONGREGATE_SDK$': get_static_include('KongregateSDK.js') if (visitor.frame_platform == 'kg' and SpinConfig.config.get('enable_kongregate',0)) else '',
            '$ARMORGAMES_SDK$': get_static_include('ArmorGamesSDK.js') if (visitor.frame_platform == 'ag' and SpinConfig.config.get('enable_armorgames',0)) else '',
            # XXX probably need a frame platform restriction on loading Xsolla
            '$XSOLLA_SDK$': get_static_include('XsollaSDK.js') if (SpinConfig.config.get('enable_xsolla',0)) else '',
            '$LOADING_SCREEN_NAME$': screen_name,
            '$LOADING_SCREEN_DATA$': SpinJSON.dumps(screen_data),
            '$INDEX_BODY$': get_static_include('index_body_%s.html' % visitor.frame_platform),
            })

        expr = re.compile('|'.join([key.replace('$','\$') for key in replacements.iterkeys()]))

        template = get_static_include('proxy_index.html')

        metric_event_coded(visitor, '0100_authenticated_visit', visitor.add_demographics({'splash_image':screen_name}))

        if 0:
            ret = []
            for line in template.split('\n'):
                line = expr.sub(lambda match: replacements[match.group(0)], line)
                ret.append(str(line))
            return '\n'.join(ret)
        else:
            return str(expr.sub(lambda match: replacements[match.group(0)], template))

    def render_API(self, request):
        update_time()

        add_proxy_headers(request)

        if verbose() >= 2:
            print '================',self.path,'=================='
            dump_request(request)

        if self.path == '/GAMEAPI':
            if ('session' not in request.args) or (not request.args['session'][0]):
                raw_log.event(proxy_time, 'GAMEAPI request without a session '+log_request(request))
                request.setResponseCode(http.BAD_REQUEST)
                return str('error')
            session_id = request.args['session'][0]
            if verbose() >= 2: print 'GAMEAPI proxy call for session', session_id

            session = self.session_emulate(db_client.session_get_by_session_id(session_id, reason=self.path))
            if not session:
                if verbose(): print 'GAMEAPI proxy error: session not recognized', session_id
                return SpinJSON.dumps({'serial':0, 'clock': proxy_time, 'msg': [["ERROR", "UNKNOWN_SESSION"]]})

            if 'proxy_logout' in request.args:
                # client is politely telling us it's going away
                # but we need to force the termination before removing the session from our table, to prevent double logins.
                # it is NOT safe to just drop session immediately, because the server could still be busy doing the logout right now,
                # and we need to wait until it completes before allowing another login to proceed.
                d = defer.Deferred()
                d.addBoth(self.complete_deferred_request, request)
                self.start_async_termination(request, session.session_id, session.user_id,
                                             session.gameserver_name, session.gameserver_ctrl,
                                             lambda success, is_latest: d.callback("true"), reason = 'proxy_logout')
                return twisted.web.server.NOT_DONE_YET

            # peek into the message to see if it should keepalive or not
            if ('nokeepalive' not in request.args) or ('proxy_keepalive_only' in request.args):
                # message sent with human interaction, keep game connection alive
                session.last_active_time = proxy_time

                if 'proxy_keepalive_only' in request.args:
                    # do not forward to game server, just keepalive and return

                    # XXX not really necessary anymore since the server does the keepalive
                    db_client.session_keepalive(session.session_id, reason=self.path)

                    return "true"

            return self.render_via_proxy(session.gameserver_fwd, request)

        elif self.path == '/CONTROLAPI':
            if 'secret' not in request.args or request.args['secret'][-1] != SpinConfig.config['proxy_api_secret'] or 'method' not in request.args:
                raise Exception('unauthorized')

            method = request.args['method'][-1]

            if 'broadcast' in request.args:
                qs = {'type':SpinConfig.game(), 'state':'ok'}
                fwdlist = [(x['hostname'], x['game_http_port'], x['server_name']) for x in db_client.server_status_query(qs, fields = {'_id':1, 'hostname':1, 'game_http_port':1})]

                dlist = []
                namelist = []
                for fwd in fwdlist:
                    url = 'http://%s:%d/CONTROLAPI?' % (fwd[0], fwd[1]) + urllib.urlencode(dict((k, v[0]) for k, v in request.args.iteritems() if k not in ('broadcast','server')))
                    exception_log.event(proxy_time, url)
                    d = defer.Deferred()
                    control_async_http.queue_request(proxy_time, url, d.callback, error_callback = d.callback)
                    dlist.append(d)
                    namelist.append(fwd[2])

                d = defer.DeferredList(dlist, consumeErrors=1)
                def gather_responses(self, request, namelist, rlist):
                    response = [{'server_name':namelist[i], 'result':rlist[i][1]} if rlist[i][0] else {'server_name':namelist[i], 'error':rlist[i][1]} \
                                for i in xrange(len(rlist))]
                    self.complete_deferred_request(SpinJSON.dumps(response, newline=True), request)
                d.addBoth(functools.partial(gather_responses, self, request, namelist))
                return twisted.web.server.NOT_DONE_YET

            fwd = None

            if 'server' in request.args:
                server_name = request.args['server'][-1]
                if server_name == 'proxyserver': # it's for us!
                    if method == 'reconfig':
                        return SpinJSON.dumps(reconfig(), newline=True)
                    elif method == 'test_payment_dispute':
                        test_response = SpinJSON.loads('''{"id":"example_payment","user":{"name":"Frank","id":"example3"},"actions":[{"type":"charge","status":"completed","currency":"USD","amount":"50.00","time_created":"2014-02-09T16:34:55+0000","time_updated":"2014-02-09T16:34:55+0000"}],"refundable_amount":{"currency":"USD","amount":"50.00"},"items":[{"type":"IN_APP_PURCHASE","product":"http:\/\/trprod.spinpunch.com\/OGPAPI?spellname=BUY_GAMEBUCKS_5000_FBP_P100M_USD&type=tr_sku","quantity":1}],"country":"US","request_id":"tr_1102945_8f64174bf243e51fedfeb2f468dcccb6_1541","created_time":"2014-02-09T16:34:55+0000","payout_foreign_exchange_rate":1,"disputes":[{"user_comment":"I bougth 50 dollars and press the x in the corner so I took me back to the game so I triedgain it did give me my 50 dollars worth in  gold I had a hundred in card so I tried again to get my other 50 dollars in gold and it declined my card that means that one of the payments went tru but I didn\'t got my gold!! pls help me","time_created":"2014-02-10T23:12:49+0000","user_email":"asdf\u0040example.com"}]}''')
                        send_payment_dispute_notification(test_response, 1112, dry_run = True)
                        return 'ok\n'
                    else:
                        raise Exception('unhandled method '+method)
                else:
                    row = db_client.server_status_query_one({'_id':server_name}, {'hostname':1, 'game_http_port':1})
                    if row:
                        fwd = (row['hostname'], row['game_http_port'], server_name)
                    else:
                        raise Exception('server %s not found' % server_name)

            # if method acts on a user, and that user is logged in, route it to the server handling that user
            # otherwise, pick any open server
            if (not fwd) and ('user_id' in request.args):
                user_id = int(request.args['user_id'][-1])
                session = self.session_emulate(db_client.session_get_by_user_id(user_id, reason=self.path))
                if session:
                    fwd = session.gameserver_fwd
            elif (not fwd) and (('facebook_id' in request.args) or ('social_id' in request.args)):
                if 'facebook_id' in request.args:
                    social_id = 'fb'+request.args['facebook_id'][-1]
                else:
                    social_id = request.args['social_id'][-1]
                session = self.session_emulate(db_client.session_get_by_social_id(social_id, reason=self.path))
                if session:
                    fwd = session.gameserver_fwd

            if not fwd:
                # pick any open server (e.g. for customer support requests on offline players)
                qs = {'type':SpinConfig.game(), 'state':'ok',
                      'gamedata_build': proxysite.proxy_root.static_resources['gamedata-%s-en_US.js' % SpinConfig.game()].build_date,
                      'gameclient_build': proxysite.proxy_root.static_resources['compiled-client.js'].build_date}
                result = db_client.server_status_query_one(qs, fields = {'hostname':1, 'game_http_port':1})
                if result:
                    fwd = (result['hostname'], result['game_http_port'])

            if not fwd: raise Exception('cannot find server for CONTROLAPI call: '+log_request(request))
            return self.render_via_proxy(fwd, request)

        elif self.path == '/KGAPI':
            #exception_log.event(proxy_time, 'KGAPI call: '+repr(request.args))
            request_data = SpinKongregate.parse_signed_request(request.args['signed_request'][-1], SpinConfig.config['kongregate_api_key'])
            if not request_data: raise Exception('KGAPI call with invalid signed_request: '+log_request(request))

            session = None

            if request_data['event'] in ('item_order_request', 'item_order_placed'):
                kongregate_id = str(request_data['buyer_id'])
                session = self.session_emulate(db_client.session_get_by_social_id('kg'+kongregate_id, reason=self.path))
            else:
                raise Exception('KGAPI call with invalid "event": '+log_request(request))

            if not session: raise Exception('cannot find session for KGAPI call: '+repr(request_data))
            return self.render_via_proxy(session.gameserver_fwd, request)

        elif self.path == '/XSAPI':
            # note: we don't check the signature here - that needs to be done by the gameserver
            request_body = request.content.read()
            xsapi_raw_log.event(proxy_time, request_body)
            request_data = SpinJSON.loads(request_body)
            xsapi_json_log.event(proxy_time, request_data)

            session = None
            if 'user' in request_data and 'id' in request_data['user']:
                xs_id = request_data['user']['id']
                # note: assume we are using social_id as the Xsolla ID
                session = self.session_emulate(db_client.session_get_by_social_id(xs_id, reason=self.path))
            else:
                raise Exception('invalid XSAPI call: '+log_request(request)+' body '+repr(request_data))

            if not session:
                exception_log.event(proxy_time, 'cannot find session for XSAPI call: '+repr(request_data))
                request.setResponseCode(http.BAD_REQUEST)
                return SpinJSON.dumps({'error': {'code':'INVALID_USER', 'message': 'session not found (by proxyserver)'}})

            return self.render_via_proxy(session.gameserver_fwd, request)

        elif self.path == '/CREDITAPI':
            # extract session from the custom order_info the client passed to Facebook
            method = request.args['method'][0]
            request_data = SpinFacebook.parse_signed_request(request.args['signed_request'][-1], SpinConfig.config['facebook_app_secret'])

            session = None

            if method == 'payments_get_item_price':
                # NEW FB Payments flow (with dynamic pricing)
                facebook_id = str(request_data['user_id'])
                session = self.session_emulate(db_client.session_get_by_social_id('fb'+facebook_id, reason=self.path))
            else:
                # OLD FB Credits flow
                order_details = None
                if method == 'payments_get_items':
                    order_info = SpinJSON.loads(request_data['credits']['order_info'])
                elif method == 'payments_status_update':
                    order_details = SpinJSON.loads(request_data['credits']['order_details'])
                    order_info = SpinFacebook.order_data_decode(order_details['items'][0]['data'])

                if 'session_id' in order_info:
                    session_id = str(order_info['session_id'])
                    session = self.session_emulate(db_client.session_get_by_session_id(session_id, reason=self.path))
                    if verbose(): print 'CREDITAPI proxy call for session', session_id
                elif order_details and 'buyer' in order_details:
                    # in-app currency promo orders do not come with a session_id since they are generated
                    # by Facebook. Search the session table for it instead.
                    buyer = str(order_details['buyer'])
                    session = self.session_emulate(db_client.session_get_by_social_id('fb'+buyer, reason=self.path))

            if not session: raise Exception('cannot find session for CREDITAPI call: '+repr(order_details))
            return self.render_via_proxy(session.gameserver_fwd, request)

        elif self.path == '/TRIALPAYAPI':
            assert str(request.args['app_id'][0]) == SpinConfig.config['facebook_app_id']
            order_info = request.args['order_info'][0]
            user_id = int(order_info)
            session = self.session_emulate(db_client.session_get_by_user_id(user_id, reason=self.path))
            if session:
                # synchronous path
                return self.render_via_proxy(session.gameserver_fwd, request)
            else:
                # asynchronous path - queue message to be processed on next login
                db_client.msg_send([{'to':[user_id],
                                     'type':'TRIALPAYAPI_payment',
                                     'time':proxy_time,
                                     'expire_time': proxy_time + SpinConfig.config['proxyserver'].get('TRIALPAYAPI_payment_msg_duration', 30*24*60*60),
                                     'their_hash': SpinHTTP.get_twisted_header(request, 'TrialPay-HMAC-MD5'),
                                     'request_args': request.args,
                                     'request_body': request.content.read()}])
                # return success immediately
                return str('1')

        elif self.path == '/METRICSAPI':
            SpinHTTP.set_access_control_headers(request)
            request.setHeader('Content-Type', 'image/gif')
            request.setHeader('Pragma','no-cache, no-store')
            request.setHeader('Cache-Control','no-cache, no-store')
            request.setHeader('Expires','0')
            anon_id = request.args['id'][0] if 'id' in request.args else None
            event_name = request.args['event'][0]
            props_raw = request.args['props'][0]

            # some browsers append '/' to the URL and cause failure in JSON parsing, fix it here
            if props_raw[-1] == '/':
                props_raw = props_raw[:-1]

            props = SpinJSON.loads(props_raw)
            assert 'code' in props
            assert int(event_name[0:4]) == props['code']
            if anon_id: props['anon_id'] = anon_id
            props['event_name'] = event_name
            metrics_log.event(proxy_time, props)
            return 'GIF89a\x01\x00\x01\x00\x80\xff\x00\xff\xff\xff\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'

        elif self.path == '/OGPAPI':
            # pick any open server
            fwd = None

            qs = {'type':SpinConfig.game(), 'state':'ok',
                  'gamedata_build': proxysite.proxy_root.static_resources['gamedata-%s-en_US.js' % SpinConfig.game()].build_date,
                  'gameclient_build': proxysite.proxy_root.static_resources['compiled-client.js'].build_date}
            result = db_client.server_status_query_one(qs, fields = {'hostname':1, 'game_http_port':1})
            if result:
                fwd = (result['hostname'], result['game_http_port'])

            if not fwd: raise Exception('cannot find server for OGPAPI call: '+log_request(request))

            return self.render_via_proxy(fwd, request)

        elif self.path == '/FBRTAPI':
            request.setHeader('Content-Type', 'application/json')
            if request.method == 'GET':
                assert request.args['hub.mode'][0] == 'subscribe'
                assert request.args['hub.verify_token'][0] == SpinConfig.config['fbrtapi_verify_token']
                challenge = request.args['hub.challenge'][0]
                return challenge
            elif request.method == 'POST':
                payload = request.content.read()
                expected_sig = 'sha1='+hmac.new(str(SpinConfig.config['facebook_app_secret']), msg=payload, digestmod=hashlib.sha1).hexdigest()
                assert expected_sig == str(request.requestHeaders.getRawHeaders('X-Hub-Signature')[0])
                pay = SpinJSON.loads(payload)
                fbrtapi_raw_log.event(proxy_time, repr(pay))
                fbrtapi_json_log.event(proxy_time, pay)

                if pay['object'] == 'payments':
                    # need to ping Facebook to get the associated user's Facebook ID
                    payment_id = pay['entry'][0]['id']
                    d = defer.Deferred()
                    class FBRTAPI_payment_pinger:
                        def __init__(self, payment_id, notification, d):
                            self.payment_id = payment_id
                            self.notification = notification
                            self.d = d
                        def on_response(self, str_response):
                            try:
                                self._on_response(str_response)
                            except:
                                exception_log.event(proxy_time, 'FBRTAPI_payment exception on payment_id %s: %s' % \
                                                    (self.payment_id, traceback.format_exc()))
                            self.d.callback('')
                        def _on_response(self, str_response):
                            response = SpinJSON.loads(str_response)
                            user_id = None

                            # first try getting user_id via facebook_id
                            if response.get('user',None):
                                facebook_id = str(response['user']['id'])
                                user_id = social_id_table.social_id_to_spinpunch('fb'+facebook_id, False)

                            # fallback - pull user_id from new request_id format
                            if (not user_id) and len(response.get('request_id','').split('_'))==4:
                                user_id = int(response['request_id'].split('_')[1])

                            if not user_id:
                                raise Exception('cannot determine user_id')

                            db_client.msg_send([{'to':[user_id],
                                                 'type':'FBRTAPI_payment',
                                                 'time':proxy_time,
                                                 'expire_time': proxy_time + SpinConfig.config['proxyserver'].get('FBRTAPI_payment_msg_duration', 30*24*60*60),
                                                 'response': response,
                                                 'payment_id': self.payment_id}])

                            if 'disputes' in self.notification['entry'][0]['changed_fields']:
                                # also log the dispute and notify support
                                send_payment_dispute_notification(response, user_id)

                        def on_error(self, reason):
                            self.d.callback('')
                    pinger = FBRTAPI_payment_pinger(payment_id, pay, d)
                    fb_async_http.queue_request(proxy_time,
                                                SpinFacebook.versioned_graph_endpoint('payment', payment_id) + \
                                                '?'+urllib.urlencode({'access_token': SpinConfig.config['facebook_app_access_token']}),
                                                pinger.on_response, error_callback = pinger.on_error, max_tries = 4)
                    # fire-and-forget - let the pinger go asynchronously
                    return ''

                return ''
            else:
                raise Exception('unhandled request: '+repr(request))

        elif self.path == '/FBDEAUTHAPI':
            signed_request = SpinFacebook.parse_signed_request(request.args['signed_request'][0], SpinConfig.config['facebook_app_secret'])
            user_id = social_id_table.social_id_to_spinpunch('fb'+str(signed_request['user_id']), False)
            if user_id:
                metric_event_coded(None, '0113_account_deauthorized', {'user_id': user_id})
                # mark account as "deauthorized"

                # pick any open server
                qs = {'type':SpinConfig.game(), 'state':'ok',
                      'gamedata_build': proxysite.proxy_root.static_resources['gamedata-%s-en_US.js' % SpinConfig.game()].build_date,
                      'gameclient_build': proxysite.proxy_root.static_resources['compiled-client.js'].build_date}
                result = db_client.server_status_query_one(qs, fields = {'hostname':1, 'game_http_port':1})
                if result:
                    url = controlapi_url(result['hostname'], result['game_http_port']) + '?' + \
                          urllib.urlencode(dict(secret = str(SpinConfig.config['proxy_api_secret']),
                                                method = 'mark_uninstalled',
                                                user_id = str(user_id)))
                    control_async_http.queue_request(proxy_time, url, lambda response: None)
            return ''

        elif self.path == '/ADMIN/':
            return admin_stats.render_html()

        elif self.path == '/PING':
            SpinHTTP.set_access_control_headers(request)
            request.setHeader('Pragma','no-cache, no-store')
            request.setHeader('Cache-Control','no-cache, no-store')
            request.setHeader('Expires','0')
            return 'ok\n'

        # should not get here
        raise Exception('unhandled API request '+repr(request))

    def render_via_proxy(self, hostport, request):
        self.host = str(hostport[0]) # Twisted barfs if the hostname is Unicode
        self.port = hostport[1]
        return proxy.ReverseProxyResource.render(self, request)

    def render(self, request):
        try:
            start_time = time.time()
            if self.path == '/':
                ret = self.render_ROOT(request, frame_platform = 'fb')
            elif self.path == '/KGROOT':
                ret = self.render_ROOT(request, frame_platform = 'kg')
            elif self.path == '/AGROOT':
                ret = self.render_ROOT(request, frame_platform = 'ag')
            elif self.path in ('/GAMEAPI', '/CREDITAPI', '/TRIALPAYAPI', '/KGAPI', '/XSAPI', '/CONTROLAPI', '/METRICSAPI', '/ADMIN/', '/PING', '/OGPAPI', '/FBRTAPI', '/FBDEAUTHAPI'):
                ret = self.render_API(request)
            else:
                ret = str('error')
                raw_log.event(proxy_time, 'refusing to proxy unexpected request '+log_request(request))
            end_time = time.time()
            admin_stats.record_latency('GameProxy '+self.path, end_time-start_time)
            return ret

        except Exception:
            exception_log.event(proxy_time, 'proxyserver Exception: ' + traceback.format_exc()+'while handling request '+log_request(request))

        request.setResponseCode(http.BAD_REQUEST)
        return str('error')

class AdminStats(object):
    def __init__(self):
        self.start_time = proxy_time
        self.latency = {}

    # XXX merge with similar code in server.py
    def record_latency(self, name, elapsed):
        if name not in self.latency:
            self.latency[name] = {'N':0.0, 'total':0.0, 'max': 0.0}
        self.latency[name]['N'] += 1
        self.latency[name]['total'] += elapsed
        self.latency[name]['max'] = max(self.latency[name]['max'], elapsed)
    def get_load(self):
        if 'ALL' in self.latency:
            return self.latency['ALL']['total'] / float(proxy_time - self.start_time)
        else:
            return -1
    def get_latency(self):
        ret = ''
        if 'ALL' in self.latency:
            ret += 'Approximate unhalted load: <b>%.1f%%</b><br>' % (100.0*self.get_load())
            ret += 'Average request latency: <b>%.1f ms</b><p>' % ((1000.0*self.latency['ALL']['total'])/self.latency['ALL']['N'])

        def sort_by_max(kv): return -kv[1]['max']
        def sort_by_average(kv): return -kv[1]['total']/kv[1]['N']
        def sort_by_total(kv): return -kv[1]['total']

        grand_total = sum([data['total'] for name, data in self.latency.iteritems() if name != 'ALL'])

        for sort_name, sort_func in {'Max': sort_by_max, 'Avg': sort_by_average, 'Total': sort_by_total}.iteritems():
            ret += '<p>Sort by %s<br>' % sort_name
            ret += '<table border="1" cellspacing="1">'
            ret += '<tr><td>Request</td><td>Average</td><td>Max</td><td>Total</td><td>Total %</td><td>#Calls</td></tr>'
            ls = self.latency.items()
            ls.sort(key = sort_func)
            for name, data in ls[0:25]:
                ret += '<tr><td>%s</td><td>%.1f ms</td><td>%.1f ms</td><td>%.1f s</td><td>%.1f%%</td><td>%d</td></tr>' % \
                       (name, 1000.0*data['total']/data['N'],
                        1000.0*data['max'],
                        data['total'],
                        (100.0*data['total']/grand_total) if grand_total != 0 else 0,
                        int(data['N'])
                        )
            ret += '</table>'
        return ret
    def render_html(self):
        ret = ''
        for name, async in (('control_async_http', control_async_http),
                            ('fb_async_http', fb_async_http),
                            ('ag_async_http', ag_async_http),
                            ('kg_async_http', kg_async_http)):
            if async:
                ret += '<hr><b>%s</b><p>' % name
                ret += async.get_stats_html(proxy_time, expose_info = (not SpinConfig.config.get('secure_mode',0)))

        ret += '<hr><p>'
        ret += self.get_latency()
        return ret

    def get_server_status_json(self):
        return {'server_time': proxy_time,
                'launch_time': proxy_launch_time,
                'type': 'proxyserver',
                'state': 'ok',
                'hostname': SpinConfig.config['proxyserver'].get('external_host', os.getenv('HOSTNAME') or socket.gethostname()),
                'pid': os.getpid(),
                'external_listen_host': SpinConfig.config['proxyserver'].get('external_listen_host',''),
                'external_http_port': SpinConfig.config['proxyserver']['external_http_port'],
                'external_ssl_port': SpinConfig.config['proxyserver'].get('external_ssl_port',-1),
                'gamedata_build': proxysite.proxy_root.static_resources['gamedata-%s-en_US.js' % SpinConfig.game()].build_date,
                'gameclient_build': proxysite.proxy_root.static_resources['compiled-client.js'].build_date,
                'uptime': proxy_time - self.start_time,
                'load_unhalted': self.get_load(),
                'active_visitors': len(visitor_table),
                'active_sessions': 0 # with dynamic routing, this would involve a mongodb query
                }

admin_stats = AdminStats()

# special kind of HTTP resource for compiled-client.js and gamedata.js
# these have checksums appended to the filenames, and are set for long cache lifetimes
# to ensure browsers and the CDN use the right version of JavaScript resources
# also, we cache gzipped versions of these for browsers that can handle it
class CachedJSFile(resource.Resource):
    max_age = 60*60*24*7

    # regular expression that strips version checksum out of filename
    checksum_stripper = re.compile('-CSV.+V')
    @classmethod
    def strip_checksum(cls, name):
        return cls.checksum_stripper.sub('', name)

    gameclient_build_date_detector = re.compile('^var gameclient_build_date = "(.*)";')
    gamedata_build_info_detector = re.compile('"gamedata_build_info":{(.*)}')

    # 'checksum' appends an MD5 hash to the filename
    def __init__(self, filename):
        resource.Resource.__init__(self)
        self.filename = filename
        self.checksum_time = -1
        self.checksum_value = ''
        self.contents = None
        self.contents_gz = None
        self.build_date = None
        self.update()

    def length(self): return len(self.contents)

    def update(self):
        try:
            file_time = os.path.getmtime(self.filename)
            if file_time > self.checksum_time or (self.contents is None):
                # ordinary string buffer
                buf = cStringIO.StringIO()

                # create a cStringIO to receive a gzipped version of the file
                gz_buf = cStringIO.StringIO()
                gz_fd = gzip.GzipFile(os.path.basename(self.filename)[:5], mode='w', compresslevel=9, fileobj=gz_buf)

                first_line = None
                last_line = None
                checksum = hashlib.md5()

                for line in open(self.filename).xreadlines():
                    checksum.update(line)
                    buf.write(line)
                    gz_fd.write(line)
                    if first_line is None: first_line = line
                    last_line = line

                gz_fd.close()

                # scan file for build date info
                self.build_date = None
                match = self.gamedata_build_info_detector.search(first_line)
                if match:
                    self.build_date = SpinJSON.loads('{'+match.group(1)+'}')['date']
                match = self.gameclient_build_date_detector.search(last_line)
                if match:
                    self.build_date = match.group(1)

                self.contents = str(buf.getvalue())
                self.contents_gz = str(gz_buf.getvalue())

                self.checksum_value = checksum.hexdigest()
                self.checksum_time = file_time
                if exception_log:
                    exception_log.event(proxy_time, 'proxyserver updated checksum of %s -> %s build %s' % (self.filename, self.checksum_value, repr(self.build_date)))

        except:
            msg = 'proxyserver exception checksumming %s: ' % self.filename + traceback.format_exc()
            if exception_log:
                exception_log.event(proxy_time, msg)
            else:
                sys.stderr.write(msg+'\n')

    def add_checksum(self, name):
        return name.replace('.js', '-CSV%sV.js' % self.checksum_value)

    def set_cdn_headers(self, request):
        max_age = SpinConfig.config['proxyserver'].get('js_files_max_cache_age', 90*24*60*60)
        request.setHeader('Cache-Control', 'max-age='+str(max_age))
        if SpinConfig.config['proxyserver'].get('cdn_expires_header', False):
            request.setHeader('Expires', format_http_time(proxy_time + max_age))
        # IE<10 requires text/plain for CORS requests to work
        content_type = 'text/plain' if SpinConfig.config['proxyserver'].get('xhr_js_files', False) else 'text/javascript'
        request.setHeader('Content-Type', content_type)
        SpinHTTP.set_access_control_headers_for_cdn(request, max_age)

    def render_OPTIONS(self, request):
        self.set_cdn_headers(request)
        return ''

    def render(self, request):
        self.set_cdn_headers(request)
        accept_encoding = request.getHeader('Accept-Encoding')
        if accept_encoding:
            encodings = accept_encoding.split(',')
            for encoding in encodings:
                name = encoding.split(';')[0].strip()
                if name == 'gzip':
                    request.setHeader('Content-Encoding','gzip')
                    return self.contents_gz
        return self.contents

class UncachedJSFile(static.File):
    def render(self, request):
        SpinHTTP.set_access_control_headers(request)
        request.setHeader('Pragma','no-cache, no-store')
        request.setHeader('Cache-Control','no-cache, no-store')
        request.setHeader('Expires','0')
        return static.File.render(self, request)

# used for artwork files retrieved both directly and via CDN
class ArtFile(static.File):
    def set_cdn_headers(self, request):
        max_age = SpinConfig.config['proxyserver'].get('art_assets_max_cache_age', 90*24*60*60)
        request.setHeader('Cache-Control', 'max-age='+str(max_age))
        if SpinConfig.config['proxyserver'].get('cdn_expires_header', False):
            request.setHeader('Expires', format_http_time(proxy_time + max_age))

        # necessary for art files fetched by XMLHttpRequest to work when they're on the CDN
        # note! this means that CDN requests MUST have a unique ?origin=whatever in the URL!
        SpinHTTP.set_access_control_headers_for_cdn(request, max_age)

    def render_OPTIONS(self, request):
        self.set_cdn_headers(request)
        return ''

    def render(self, request):
        self.set_cdn_headers(request)
        return static.File.render(self, request)

# We have to proxy Facebook and Kongregate portraits, to attach a specific Access-Control-Allow-Origin
# so that drawing them will not taint the HTML Canvas.
class PortraitProxy(twisted.web.resource.Resource):
    # boilerplate to short-circuit path lookups
    def getChildWithDefault(self, path, request): return self

    def set_cdn_headers(self, request):
        # Cache for 24hrs by default
        max_age = SpinConfig.config['proxyserver'].get('portraits_max_cache_age', 24*60*60)
        request.setHeader('Cache-Control', 'max-age='+str(max_age))
        if SpinConfig.config['proxyserver'].get('cdn_expires_header', False):
            request.setHeader('Expires', format_http_time(proxy_time + max_age))

        # note! this means that requests MUST have a unique ?origin=whatever in the URL!
        SpinHTTP.set_access_control_headers_for_cdn(request, max_age)

    def render_OPTIONS(self, request):
        self.parse_request(request) # just to assert it is a valid request
        self.set_cdn_headers(request)
        return ''

    def render(self, request):
        source_url = self.parse_request(request)
        self.set_cdn_headers(request)
        d = defer.Deferred()
        d.addBoth(self.complete_deferred_request, request)
        fw = self.Forwarded(self, request, d)
        self.async_http.queue_request(proxy_time, source_url, fw.on_response, error_callback = fw.on_error, callback_type = self.async_http.CALLBACK_FULL)
        return twisted.web.server.NOT_DONE_YET

    class Forwarded(object):
        def __init__(self, parent, request, d):
            self.parent = parent
            self.request = request
            self.d = d
        def on_response(self, body = None, headers = None, status = None):
            # forward a subset of applicable headers back to the client
            for HEADER in ('content-type', 'content-length', 'content-encoding',
                           'last-modified', 'date',
                           #'expires', 'cache-control',
                           ):
                if HEADER in headers:
                    self.request.setHeader(HEADER, headers[HEADER][-1])
            self.d.callback(body)
        def on_error(self, ui_reason = None, body = None, headers = None, status = None):
            self.d.errback(ui_reason)

    def complete_deferred_request(self, body, request):
        if body == twisted.web.server.NOT_DONE_YET:
            return body
        assert type(body) in (str, unicode)
        if hasattr(request, '_disconnected') and request._disconnected: return
        request.write(body)
        request.finish()

class FBPortraitProxy(PortraitProxy):
    def __init__(self):
        # keep our own private requester to avoid disturbing the main API calls, and to operate when the platform is disabled
        config = SpinConfig.config['proxyserver'].get('AsyncHTTP_Facebook', {})
        self.async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',30), 0,
                                                       lambda x: facebook_log.event(proxy_time, x) if facebook_log else sys.stderr.write(x+'\n'),
                                                       max_tries = config.get('max_tries',1),
                                                       retry_delay = config.get('retry_delay',3))

    def parse_request(self, request):
        # sanity-check the URL we are about to proxy
        parts = urlparse.urlparse(request.uri)
        path_fields = parts.path.split('/')
        assert len(path_fields) == 4
        assert path_fields[1] == 'fb_portrait'
        fbid = path_fields[2]
        assert path_fields[3] == 'picture'
        assert (not parts.params) and (not parts.fragment)
        qs = urlparse.parse_qs(parts.query)
        assert ('spin_origin' in qs)
        for key, val in qs.iteritems():
            if key not in ('v', 'spin_origin'):
                exception_log.event(proxy_time, 'unrecognized FB portrait URL: %s' % repr(parts))
                assert False # force fail
        return SpinFacebook.versioned_graph_endpoint('user/picture', '%s/picture' % fbid)

class KGPortraitProxy(PortraitProxy):
    def __init__(self):
        # keep our own private requester to avoid disturbing the main API calls, and to operate when the platform is disabled
        config = SpinConfig.config['proxyserver'].get('AsyncHTTP_Kongregate', {})
        self.async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',30), 0,
                                                       lambda x: kongregate_log.event(proxy_time, x) if kongregate_log else sys.stderr.write(x+'\n'),
                                                       max_tries = config.get('max_tries',1),
                                                       retry_delay = config.get('retry_delay',3))

    def parse_request(self, request):
        # sanity-check the URL we are about to proxy
        parts = urlparse.urlparse(request.uri)
        path_fields = parts.path.split('/')
        assert len(path_fields) == 3
        assert path_fields[1] == 'kg_portrait'
        assert path_fields[0] == '' and path_fields[2] == ''
        assert (not parts.params) and (not parts.fragment)
        qs = urlparse.parse_qs(parts.query)
        assert ('spin_origin' in qs) and ('avatar_url' in qs)
        for key, val in qs.iteritems():
            if key not in ('spin_origin', 'avatar_url', 'v'):
                exception_log.event(proxy_time, 'unrecognized KG portrait qs: %s' % repr(parts))
                assert False # force fail
        avatar_url = qs['avatar_url'][-1]
        avatar_parts = urlparse.urlparse(avatar_url)
        if not (avatar_parts.netloc.endswith('kongcdn.com') or avatar_parts.netloc.endswith('insnw.net')):
            exception_log.event(proxy_time, 'unrecognized KG portrait URL: %s' % repr(avatar_parts))
            assert False # force fail
        return avatar_url

class AGPortraitProxy(PortraitProxy):
    def __init__(self):
        # keep our own private requester to avoid disturbing the main API calls, and to operate when the platform is disabled
        config = SpinConfig.config['proxyserver'].get('AsyncHTTP_ArmorGames', {})
        self.async_http = AsyncHTTP.AsyncHTTPRequester(-1, -1, config.get('request_timeout',30), 0,
                                                       lambda x: armorgames_log.event(proxy_time, x) if armorgames_log else sys.stderr.write(x+'\n'),
                                                       max_tries = config.get('max_tries',1),
                                                       retry_delay = config.get('retry_delay',3))

    def parse_request(self, request):
        # sanity-check the URL we are about to proxy
        parts = urlparse.urlparse(request.uri)
        path_fields = parts.path.split('/')
        assert len(path_fields) == 3
        assert path_fields[1] == 'ag_portrait'
        assert path_fields[0] == '' and path_fields[2] == ''
        assert (not parts.params) and (not parts.fragment)
        qs = urlparse.parse_qs(parts.query)
        assert ('spin_origin' in qs) and ('avatar_url' in qs)
        for key, val in qs.iteritems():
            if key not in ('spin_origin', 'avatar_url', 'v'):
                exception_log.event(proxy_time, 'unrecognized AG portrait qs: %s' % repr(parts))
                assert False # force fail
        avatar_url = qs['avatar_url'][-1]
        if '%2F' in avatar_url: # handle browsers that (improperly?) leave avatar_url URL-encoded
            avatar_url = urllib.unquote(avatar_url)
        avatar_parts = urlparse.urlparse(avatar_url)
        if not avatar_parts.netloc.endswith('armorgames.com'):
            exception_log.event(proxy_time, 'unrecognized AG portrait URL: %s' % repr(avatar_parts))
            assert False # force fail
        return avatar_url

class XDChannelResource(static.Data):
    # returns the "channel" file necessary for Facebook cross-domain JavaScript calls
    isLeaf = True
    def __init__(self):
        data = '<script src="//connect.facebook.net/en_US/all.js"></script>'
        type = 'text/html'
        static.Data.__init__(self, data, type)
    def render(self, request):
        SpinHTTP.set_access_control_headers(request)
        request.setHeader('pragma', 'public')
        request.setHeader('Cache-Control', 'max-age='+str(const_one_year))
        request.setHeader('Expires', format_http_time(proxy_time+const_one_year))
        return static.Data.render(self, request)

class FlashXDResource(static.Data):
    # similarly, tell Flash player that it's OK to talk to mfprod and OK to load art files through the CDN
    isLeaf = True
    def __init__(self):
        data = '''<?xml version="1.0"?>
        <!DOCTYPE cross-domain-policy SYSTEM "http://www.macromedia.com/xml/dtds/cross-domain-policy.dtd">
        <cross-domain-policy>
        <allow-access-from domain="*" />
        </cross-domain-policy>'''
        type = 'text/xml'
        static.Data.__init__(self, data, type)
    def render(self, request):
        SpinHTTP.set_access_control_headers(request)
        request.setHeader('pragma', 'public')
        request.setHeader('Cache-Control', 'max-age='+str(const_one_year))
        request.setHeader('Expires', format_http_time(proxy_time+const_one_year))
        return static.Data.render(self, request)

# wrapper for twcgi.CGIScript that adds a SPIN_IS_SSL environment variable
class SpinCGIScript(twcgi.CGIScript):
    def render(self, request):
        # when server is in secure_mode, do not respond unless it's HTTPS
        if SpinConfig.config.get('secure_mode',0) and (not request.isSecure()):
            return TwistedNoResource().render(request)
        return twcgi.CGIScript.render(self, request)

    def runProcess(self, env, request, *args, **kwargs):
        env['SPIN_IS_SSL'] = '1' if request.isSecure() else '0'
        return twcgi.CGIScript.runProcess(self, env, request, *args, **kwargs)

# first stop for all requests in the hierarchy
# this defaults to returning "No Resource Found" for anything we haven't specifically exposed to the world
class ProxyRoot(TwistedNoResource):
    def __init__(self):
        TwistedNoResource.__init__(self)

        channel_resource = XDChannelResource()
        flash_xd_resource = FlashXDResource()

        self.static_resources = {
            'art': ArtFile('../gameclient/art'),
            'fb_portrait': FBPortraitProxy(),
            'kg_portrait': KGPortraitProxy(),
            'ag_portrait': AGPortraitProxy(),
            'channel': channel_resource, 'channel.php': channel_resource,
            'crossdomain.xml': flash_xd_resource,
            'compiled-client.js': CachedJSFile('../gameclient/compiled-client.js'),
            }

        self.static_resources['PCHECK'] = SpinCGIScript('./cgipcheck.py')
        self.static_resources['AUTH'] = SpinCGIScript('./cgiauth.py')
        self.static_resources['ANALYTICS2'] = SpinCGIScript('./cgianalytics.py')

        # serve all gamedata
        self.rescan_static_gamedata_resources()

        # access to raw source code (dangerous!)
        if (not SpinConfig.config.get('use_compiled_client',1)):
            for srcfile in ('generated-deps.js', 'google', 'clientcode'):
                self.static_resources[srcfile] = UncachedJSFile('../gameclient/'+srcfile)

        self.proxied_resources = {}
        for chnam in ('', 'KGROOT', 'AGROOT', 'GAMEAPI', 'METRICSAPI', 'CREDITAPI', 'TRIALPAYAPI', 'KGAPI', 'XSAPI', 'CONTROLAPI', 'ADMIN', 'OGPAPI', 'FBRTAPI', 'FBDEAUTHAPI', 'PING'):
            res = GameProxy('/'+chnam)

            # configure auth on canvas page itself (OPTIONAL now, only for demoing game outside of company)
            if chnam == '' and SpinConfig.config['proxyserver'].get('require_simple_auth', False):
                res = SpinPasswordProtection.SecureResource(lambda _res=res: _res,
                                                            username = SpinConfig.config['proxyserver']['simple_auth_username'],
                                                            password = SpinConfig.config['proxyserver']['simple_auth_password'])
            self.proxied_resources[chnam] = res

    def rescan_static_gamedata_resources(self):
        self.static_resources['compiled-client.js'].update()
        # serve any file of the form gamedata/GAME_ID/built/gamedata-GAME_ID*.js
        pattern = SpinConfig.gamedata_filename(extension = '*.js')
        for fname in glob.glob(pattern):
            bname = os.path.basename(fname)
            if bname in self.static_resources:
                self.static_resources[bname].update()
            else:
                self.static_resources[bname] = CachedJSFile(fname)

    def getChild(self, chnam, request):
        # forward these requests to the game server
        if chnam in self.proxied_resources:
            return self.proxied_resources[chnam]

        # all other resources are served directly by the proxyserver

        # strip checksum strings
        if '-CSV' in chnam:
            chnam = CachedJSFile.strip_checksum(chnam)

        if chnam in self.static_resources:
            return self.static_resources[chnam]
        else:
            if verbose() >= 2:
                print 'DEAD END', chnam
            return self

class ProxySite(twisted.web.server.Site):
    displayTracebacks = False
    def __init__(self):
        self.proxy_root = ProxyRoot()
        # note: the "timeout" here applies to HTTP KeepAlive
        # connections, it does NOT have any impact on game-relevant
        # timeouts like the session or proxy timeout
        twisted.web.server.Site.__init__(self, self.proxy_root, timeout = SpinConfig.config['proxyserver'].get('http_connection_timeout', 300))
    def log(self, request):
        if verbose() >= 3:
            return twisted.web.server.Site.log(self, request)
        else:
            # don't log every boring HTTP request
            pass

proxysite = None

def log_exception_func(x):
    exception_log.event(proxy_time, x)

# can be either a path in 'art/facebook_assets/nnn.jpg', or a literal HTML color like '#ffffff', or a JSON layer object (see loading_screens.json)
loading_screens = {'fb_guest': {'#ffffff':'#ffffff'}, 'game': {'canvas':'canvas'}}
def reconfig_loading_screens():
    global loading_screens
    temp = SpinJSON.load(open(SpinConfig.gamedata_component_filename('loading_screens_compiled.json')))
    # sanity check
    for kind in temp:
        for name, data in temp[kind].iteritems():
            if type(data) in (str,unicode):
                if data[0] == '#': continue
                if not os.path.exists('../gameclient/'+data):
                    exception_log.event(proxy_time, 'proxyserver: loading_screen image not found: "%s"' % data)
            else:
                for layer in data['layers']:
                    if 'image' in layer and not os.path.exists('../gameclient/'+layer['image']):
                        exception_log.event(proxy_time, 'proxyserver: loading_screen image not found: "%s"' % layer['image'])
    loading_screens = temp

def get_loading_screen(kind):
    data = loading_screens[kind]
    name = random.choice(data.keys())
    return name, data[name]

def reconfig():
    update_time()
    try:
        reload(SpinConfig) # reload SpinConfig module
        SpinConfig.reload() # reload config.json file

        reconfig_loading_screens()

        if db_client:
            db_client.update_dbconfig(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))
        reload_static_includes()
        proxysite.proxy_root.rescan_static_gamedata_resources()
        status_json = admin_stats.get_server_status_json()
        if db_client:
            db_client.server_status_update('proxyserver', status_json, reason='reconfig')
        return {'result':status_json}
    except:
        msg = traceback.format_exc()
        exception_log.event(proxy_time, 'proxyserver reconfig Exception: ' + msg)
        return {'error':msg}

def do_main():
    global proxysite

    for d in [proxy_log_dir]:
        if not os.path.exists(d):
            os.mkdir(d)

    # connect to database server
    global db_client
    db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                      identity = 'proxyserver', log_exception_func = log_exception_func,
                                      max_retries = -1 # never give up
                                      )
    global social_id_table
    social_id_table = SocialIDCache.SocialIDCache(db_client)

    # init server list
    reload_static_includes()
    reconfig_loading_screens()

    myport_http = SpinConfig.config['proxyserver']['external_http_port']
    myport_ssl  = SpinConfig.config['proxyserver'].get('external_ssl_port',-1)
    backlog = SpinConfig.config['proxyserver'].get('tcp_accept_backlog', 50)
    proxysite = ProxySite()
    reactor.listenTCP(myport_http, proxysite, backlog=backlog)
    if myport_ssl > 0:
        reactor.listenSSL(myport_ssl, proxysite,
                          SpinSSL.ChainingOpenSSLContextFactory(SpinConfig.config['ssl_key_file'],
                                                                SpinConfig.config['ssl_crt_file'],
                                                                certificateChainFile=SpinConfig.config['ssl_chain_file']),
                          backlog=backlog)

    global metrics_log
    # keep this in sync with the metrics_log setup in server.py!
    metrics_log = SpinLog.MultiLog([SpinLog.DailyJSONLog(proxy_log_dir+'/','-metrics.json'), # ALL metrics to local file
                                    SpinLog.MetricsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_metrics')), # important metrics to MongoDB log_metrics
                                    SpinLog.AcquisitionsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_acquisitions')), # (re)acquisitions to MongoDB log_acquisitions
                                    SpinLog.InventoryLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_inventory')), # inventory events to MongoDB log_inventory
                                    SpinLog.LadderPvPLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_ladder_pvp')), # ladder pvp events to MongoDB log_ladder_pvp
                                    SpinLog.DamageProtectionLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_damage_protection')), # damage protection events to MongoDB log_damage_protection
                                    SpinLog.AlliancesLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_alliances')), # alliance events to MongoDB log_alliances
                                    SpinLog.AllianceMembersLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_alliance_members')), # alliance member events to MongoDB log_alliance_members
                                    SpinLog.FishingLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fishing')), # fishing events to MongoDB log_fishing
                                    SpinLog.QuestsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_quests')), # quests events to MongoDB log_quests
                                    SpinLog.LotteryLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_lottery')), # lottery events to MongoDB log_lottery
                                    SpinLog.AchievementsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_achievements')), # achievements events to MongoDB log_achievements
                                    SpinLog.UnitDonationLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_unit_donation')), # unit donation events to MongoDB log_unit_donation
                                    SpinLog.LoginSourcesFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_login_sources')), # login source events to MongoDB log_login_sources
                                    SpinLog.LoginFlowFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_login_flow')), # login flow events to MongoDB log_login_flow
                                    SpinLog.FBPermissionsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fb_permissions')), # FB Permissions events to MongoDB log_fb_notifications
                                    SpinLog.FBNotificationsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fb_notifications')), # FB Notification events to MongoDB log_fb_notifications
                                    SpinLog.FBRequestsLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fb_requests')), # FB Requests events to MongoDB log_fb_requests
                                    SpinLog.FBSharingLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fb_sharing')), # FB Sharing events to MongoDB log_fb_sharing
                                    SpinLog.FBOpenGraphLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fb_open_graph')), # FB Open Graph events to MongoDB log_fb_open_graph
                                    SpinLog.ClientTroubleLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_client_trouble')), # misc client trouble to MongoDB log_client_trouble (for analytics)
                                    SpinLog.ClientExceptionLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_client_trouble'), brief = True), # abbreviated client exceptions to MongoDB log_client_trouble (for analytics)
                                    SpinLog.ClientExceptionLogFilter(SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_client_exceptions'), brief = False)]) # full client exceptions to MongoDB log_client_exceptions (for PCHECK)
    global exception_log
    exception_log = SpinLog.MultiLog([SpinLog.DailyRawLog(proxy_log_dir+'/', '-exceptions.txt'),
                                      SpinLog.ProxyserverExceptionLogFilter(SpinNoSQLLog.NoSQLRawLog(db_client, 'log_exceptions'))])
    global facebook_log
    facebook_log = SpinLog.DailyRawLog(proxy_log_dir+'/', '-facebook.txt')
    global kongregate_log
    kongregate_log = SpinLog.DailyRawLog(proxy_log_dir+'/', '-kongregate.txt')
    global armorgames_log
    armorgames_log = SpinLog.DailyRawLog(proxy_log_dir+'/', '-armorgames.txt')
    global fbrtapi_raw_log, fbrtapi_json_log
    fbrtapi_raw_log = SpinLog.DailyRawLog(proxy_log_dir+'/', '-fbrtapi.txt')
    fbrtapi_json_log = SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_fbrtapi')
    global xsapi_raw_log, xsapi_json_log
    xsapi_raw_log = SpinLog.DailyRawLog(proxy_log_dir+'/', '-xsapi.txt')
    xsapi_json_log = SpinNoSQLLog.NoSQLJSONLog(db_client, 'log_xsapi')
    global raw_log
    raw_log = SpinLog.DailyRawLog(proxy_log_dir+'/', '-proxyserver.txt')

    def bgtask_func():
        update_time()

        try:
            collect_garbage()
            # reload config file (e.g. to pick up whitelist changes)
            # but DO NOT mess with server list
            # SpinConfig.reload()

            db_client.server_status_update('proxyserver', admin_stats.get_server_status_json(), reason='bgfunc')

        except:
            exception_log.event(proxy_time, 'proxyserver bgfunc Exception: ' + traceback.format_exc())

    bgtask = task.LoopingCall(bgtask_func)
    bgtask.start(60)

    # dump info to stdout on SIGUSR1
    def handle_SIGUSR1(signum, frm):
        update_time()
        print 'ASYNC TERMINATIONS:'
        sys.stdout.write(repr(async_terminations)+'\n')
        print 'VISITOR TABLE:'
        [sys.stdout.write(repr(visitor)+'\n') for visitor in visitor_table.itervalues()]
        sys.stdout.flush()

    # rescan game server list on SIGHUP
    def handle_SIGHUP(signum, frm):
        reactor.callLater(0, reconfig)

    signal.signal(signal.SIGUSR1, handle_SIGUSR1)
    signal.signal(signal.SIGHUP, handle_SIGHUP)

    print 'Proxy server up and running on ports %d (HTTP) %d (SSL)' % (myport_http, myport_ssl)

    if proxy_daemonize:
        Daemonize.daemonize()

        # update PID file with new PID
        open(proxy_pidfile, 'w').write('%d\n' % os.getpid())

        # turn on Twisted logging
        def log_exceptions(eventDict):
            if eventDict['isError']:
                if 'failure' in eventDict:
                    text = ((eventDict.get('why') or 'Unhandled Error')
                            + '\n' + eventDict['failure'].getTraceback().strip())
                else:
                    text = ' '.join([str(m) for m in eventDict['message']])
                exception_log.event(proxy_time, text)
        def log_raw(eventDict):
            text = log.textFromEventDict(eventDict)
            if text is None:
                return
            raw_log.event(proxy_time, text)

        log.startLoggingWithObserver(log_raw)
        log.addObserver(log_exceptions)

    TwistedLatency.setup(reactor, admin_stats.record_latency)

    reactor.run()

    db_client.server_status_update('proxyserver', None, reason='shutdown')

def main():
    if os.path.exists(proxy_pidfile):
        print 'Proxy server is already running (%s).' % proxy_pidfile
        sys.exit(1)

    # create PID file
    open(proxy_pidfile, 'w').write('%d\n' % os.getpid())
    try:
        do_main()
    finally:
        # remove PID file
        os.unlink(proxy_pidfile)

if __name__ == '__main__':
    main()
