#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# client side of chatserver connection
# this uses the fully asynchronous Twisted AMP library
# it attempts to handle lost connections seamlessly

from twisted.internet import reactor, defer
from twisted.protocols import amp
from twisted.internet.protocol import ClientCreator

import SpinAmp
import SpinChatProtocol
import SpinJSON
SpinChat_CMDs = SpinAmp.init_for_twisted_amp(SpinChatProtocol.commands)

import time

time_now = int(time.time())

# compact JSON dump method
def json_dumps_compact(x):
    return SpinJSON.dumps(x, pretty = False, newline = False, double_precision = 5)

class Client:
    # states
    NOT_CONNECTED = 0
    CONNECTING = 1
    AUTHENTICATING = 2
    CONNECTED = 3

    class Proxy (amp.AMP):
        # this is one "session" - can be re-instantiated if we reconnect after a failure
        def __init__(self, **kw):
            amp.AMP.__init__(self, **kw)
            self.chat_parent = None
        def chat_recv(self, data):
            self.chat_parent.chat_recv(data)
            return {'success': 1}
        def chat_recv_batch(self, data):
            self.chat_parent.chat_recv_batch(data)
            return {'success': 1}
        SpinChat_CMDs['chat_recv'].responder(chat_recv)
        SpinChat_CMDs['chat_recv_batch'].responder(chat_recv_batch)

    def __init__(self, host, port, secret, log_exception_func, identity = 'unknown', catchup = -1, subscribe = True, latency_func = None, verbose = False):
        self.host = host
        self.port = int(port)
        self.secret = secret
        self.log_exception_func = log_exception_func
        self.identity = identity
        self.catchup = catchup
        self.subscribe = subscribe
        self.latency_func = latency_func
        self.verbose = verbose
        self.connect_sem = None
        self.listener = None

        self.chat_state = self.NOT_CONNECTED
        self.proxy = None
        self.connect_start()

    def callRemote_safe(self, cmd_name, **kw):
        if (cmd_name == 'authenticate' and self.chat_state != self.AUTHENTICATING) or \
           (cmd_name != 'authenticate' and self.chat_state != self.CONNECTED):
            self.log_exception_func('SpinChatClient not connected, dropping request "%s"' % cmd_name)
            return None

        cmd = SpinChat_CMDs[cmd_name]

        # sanitize string arguments from unicode so that AMP doesn't freak out :|
        for key, argtype in SpinChatProtocol.commands[cmd_name]['arguments']:
            if argtype == 'string' or argtype == 'unicode':
                kw[key] = str(kw[key])

        d = self.proxy.callRemote(cmd, **kw)
        if d:
            d.addErrback(self.handle_remote_error)
        return d

    def handle_remote_error(self, result):
        self.log_exception_func('SpinChatClient error: '+repr(result))
        if self.chat_state != self.NOT_CONNECTED:
            self.chat_state = self.NOT_CONNECTED
            self.connect_sem = None
            # wait 10sec, then try to reconnect
            reactor.callLater(10.0, self.connect_start)

    def connect_start(self):
        if self.verbose: print 'connect_start'
        assert self.chat_state == self.NOT_CONNECTED
        self.connect_sem = defer.Deferred()
        creator = ClientCreator(reactor, self.Proxy)
        d = creator.connectTCP(self.host, self.port)
        d.addCallback(self.connect_finish)
        d.addErrback(self.handle_remote_error)
        self.chat_state = self.CONNECTING

    def connect_finish(self, proxy):
        if self.verbose: print 'connect_finish', proxy
        assert self.chat_state == self.CONNECTING
        self.proxy = proxy
        self.proxy.chat_parent = self
        self.chat_state = self.AUTHENTICATING
        d = self.callRemote_safe('authenticate', secret = self.secret, identity = self.identity, subscribe = self.subscribe)
        d.addCallback(self.authenticate_finish)
    def authenticate_finish(self, result):
        if self.verbose: print 'authenticate_finish', result
        assert self.chat_state == self.AUTHENTICATING
        self.chat_state = self.CONNECTED
        sem = self.connect_sem
        self.connect_sem = None
        if sem: sem.callback(self)
        if self.catchup > 0:
            self.callRemote_safe('chat_catchup', num=self.catchup)
            self.catchup = 0

    def chat_send(self, json_data, log = True):
        str_data = json_dumps_compact(json_data)
        if self.verbose: print 'chat_send', str_data
        return self.callRemote_safe('chat_send', data=str_data, log=log)

    def do_chat_recv(self, json_data):
        if self.verbose: print 'do_chat_recv', json_data
        if self.listener:
            self.listener(json_data)
    def chat_recv(self, str_data):
        json_data = SpinJSON.loads(str_data)
        do_timing = self.latency_func and json_data['channel'] != 'CONTROL'

        if do_timing:
            start_time = time.time()

        self.do_chat_recv(json_data)

        if do_timing:
            if json_data['channel'] == 'CONTROL':
                kind = json_data['sender']['method']
            else:
                kind = 'chat'
            self.latency_func('ChatClient:%s' % kind, time.time()-start_time)

    def chat_recv_batch(self, str_data):
        json_data = SpinJSON.loads(str_data)
        for item in json_data:
            self.do_chat_recv(item)

if __name__ == '__main__':
    import sys, getopt, SpinConfig

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])
    if len(args) < 1:
        print 'usage: SpinChatClient "my message"'
        sys.exit(1)

    message_channel = 'BROADCAST'
    message_sender = {
        'chat_name': 'System',
        'type': 'system',
        'time': time_now,
        'facebook_id': -1,
        'user_id': -1
        }
    message_text = str(args[0])

    client = Client(SpinConfig.config['chatserver']['chat_host'],
                    SpinConfig.config['chatserver']['chat_port'],
                    SpinConfig.config['chatserver'].get('secret_full', SpinChatProtocol.default_secret_full),
                    lambda x: sys.stdout.write(x+'\n'),
                    subscribe = False,
                    verbose = True)

    def after_connect(client):
        client.chat_send({'channel':message_channel, 'sender':message_sender, 'text':message_text})
        reactor.callLater(0, lambda: reactor.stop())

    client.connect_sem.addCallback(after_connect)

    reactor.run()
