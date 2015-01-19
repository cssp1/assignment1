#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# client side of chatserver connection
# synchronous ampy version, for offline tools

import SpinJSON
import ampy
import SpinChatProtocol
import SpinAmp
SpinChat_CMDs = SpinAmp.init_for_ampy(SpinChatProtocol.commands)
import traceback
import socket

# compact JSON dump method
def json_dumps_compact(x):
    return SpinJSON.dumps(x, pretty = False, newline = False, double_precision = 5)

class SyncChatClient:
    def __init__(self, host, port, secret, log_exception_func, identity = 'unknown', catchup = -1, latency_func = None, verbose = False):
        self.log_exception_func = log_exception_func
        self.secret = secret
        self.identity = identity
        self.verbose = verbose
        self.proxy = ampy.Proxy(host, int(port), socketTimeout=60)
        self._connect()
    def _connect(self):
        self.proxy.connect()
        self.callRemote_safe('authenticate', '_connect', secret = self.secret, identity = self.identity, subscribe = False)['state']

    def callRemote_safe(self, cmd_name, reason, **kw):
        cmd = SpinChat_CMDs[cmd_name]

        # sanitize string arguments from unicode so that AMP doesn't freak out :|
        for key, argtype in SpinChatProtocol.commands[cmd_name]['arguments']:
            if argtype == 'string' or argtype == 'unicode':
                kw[key] = str(kw[key])

        while True:
            try:
                ret = self.proxy.callRemote(cmd, **kw)
                return ret
            except (TypeError, ValueError):
                # something went wrong before request was transmitted
                raise
            except ampy.AMPError:
                # request got to DB server, but encountered an error in processing
                raise
            except socket.error:
                self.log_exception_func('SpinSyncChatClient socket error: ' + traceback.format_exc() + '\nReconnecting...')
                # don't spam errors
                time.sleep(1)
            self.reconnect()
    def reconnect(self):
        while True:
            print 'SpinSyncChatClient connection error, attempting to reconnect!'
            self.proxy.close()
            try:
                self._connect()
                print 'SpinSyncChatClient connection restored'
                return
            except socket.error:
                # don't spam the server
                time.sleep(10)

    def disconnect(self):
        self.proxy.close()

    def chat_send(self, json_data, log = True, reason=''):
        str_data = json_dumps_compact(json_data)
        return self.callRemote_safe('chat_send', reason, data=str_data, log=log)


if __name__ == '__main__':
    import sys, getopt, SpinConfig, time

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', [])
    if len(args) < 1:
        print 'usage: SpinSyncChatClient "my message"'
        sys.exit(1)

    message_channel = 'BROADCAST'
    message_sender = {
        'chat_name': 'System',
        'type': 'system',
        'time': int(time.time()),
        'facebook_id': '-1',
        'user_id': -1
        }
    message_text = str(args[0])

    client = SyncChatClient(SpinConfig.config['chatserver']['chat_host'],
                            SpinConfig.config['chatserver']['chat_port'],
                            SpinConfig.config['chatserver'].get('secret_full', SpinChatProtocol.default_secret_full),
                            lambda x: sys.stdout.write(x+'\n'),
                            verbose = True)

    client.chat_send({'channel':message_channel, 'sender':message_sender, 'text':message_text})
    client.disconnect()
