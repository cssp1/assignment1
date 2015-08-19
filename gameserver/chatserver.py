#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Twisted AMP server that relays chat messages between game servers (and performs chat logging)

import os, sys
import time
import signal
import traceback
import collections

from twisted.internet import reactor
from twisted.protocols import amp
from twisted.internet.protocol import Factory
from twisted.python import log

import Daemonize
import SpinChatProtocol
import SpinAmp
import SpinLog
import SpinConfig
import SpinJSON
import SpinNoSQL

SpinChat_CMDs = SpinAmp.init_for_twisted_amp(SpinChatProtocol.commands)

daemonize = ('-n' not in sys.argv)
pidfile = 'chatserver.pid'
verbose = SpinConfig.config['chatserver'].get('verbose', True)
log_dir = SpinConfig.config.get('log_dir', 'logs')

# globals
server_time = int(time.time())
nosql_client = None
raw_log = None
exception_log = None
chat_log = None
g_subscribers = set()
g_buffer = collections.deque([], 1024) # store history of this many messages, globally (games get about 1 chat message per day per DAU)

def reload_spin_config():
    # reload config file
    global verbose
    SpinConfig.reload()
    verbose = SpinConfig.config['chatserver'].get('verbose', True)

# compact JSON dump method
def json_dumps_compact(x):
    return SpinJSON.dumps(x, pretty = False, newline = False, double_precision = 5)

class ChatProtocolHandlers (amp.AMP):
    AUTH_NONE = 0
    AUTH_READ = 1
    AUTH_WRITE = 2

    def same_peer_as(self, other):
        return (other and self.peer_identity and other.peer_identity and self.peer_identity == other.peer_identity)

    def __repr__(self):
        return str(self.peer_identity) + ' ' + str(self.peer)
    def __str__(self):
        return str(self.peer_identity) + ' ' + str(self.peer)

    def __init__(self, *args):
        amp.AMP.__init__(self, *args)
        self.auth_state = self.AUTH_NONE
        self.peer_identity = None
        self.long_result = None
        self.last_command = 'unknown'

    def locateResponder(self, name):
        # use this entry point to update server_time
        global server_time
        server_time = int(time.time())
        nosql_client.set_time(server_time)
        self.last_command = name
        return super(ChatProtocolHandlers,self).locateResponder(name)

    def makeConnection(self, transport):
        super(ChatProtocolHandlers,self).makeConnection(transport)
        self.peer = self.transport.getPeer()
        if verbose: print self.peer, 'connection made'

    def connectionLost(self, reason):
        super(ChatProtocolHandlers,self).connectionLost(reason)
        if verbose: print self.peer, 'connection lost'
        if self in g_subscribers: g_subscribers.remove(self)

    # catch protocol encoding errors here
    def _safeEmit(self, aBox):
        try:
            return amp.AMP._safeEmit(self, aBox)
        except amp.TooLong:
            exception_log.event(server_time, 'CHATSERVER RESPONSE IS TOO LONG! Last command was %s, result was %s' % \
                                (self.last_command, repr(aBox)))
            raise

    def check_readable(self):
        if not (self.auth_state & self.AUTH_READ):
            raise Exception('no read privileges')
    def check_writable(self):
        if not (self.auth_state & self.AUTH_WRITE):
            raise Exception('no write privileges')

    def get_long_result(self, start, end, finish):
        assert self.long_result is not None
        ret = self.long_result[start:end]
        if finish:
            self.long_result = None
        if verbose:
            print 'get_long_result(%d,%d,%d) = "%s"' % (start, end, finish, ret)
        return {'substr': ret}

    def authenticate(self, secret, identity, subscribe):
        if secret == SpinConfig.config['chatserver'].get('secret_read_only', SpinChatProtocol.default_secret_read_only):
            self.auth_state = self.AUTH_READ
        elif secret == SpinConfig.config['chatserver'].get('secret_full', SpinChatProtocol.default_secret_full):
            self.auth_state = self.AUTH_READ | self.AUTH_WRITE
        else:
            raise Exception('invalid authentication secret')
        identity = str(identity)
        assert identity
        self.peer_identity = identity
        if subscribe and (self not in g_subscribers): g_subscribers.add(self)
        return {'state': self.auth_state}
    SpinChat_CMDs['authenticate'].responder(authenticate)

    def chat_send(self, data, log):
        self.check_writable()
        if verbose: print 'got chat_send', data

        if log:
            json_data = SpinJSON.loads(data)
            chat_log.event(server_time, json_data)

            nosql_client.chat_record(json_data['channel'], json_data['sender'], json_data.get('text',None))

            # store so that clients who connect in the future can catch up
            g_buffer.append((json_data, len(data)))

        for conn in g_subscribers:
            if conn is not self:
                conn.callRemote(SpinChat_CMDs['chat_recv'], data = data)

        return {'success': 1}
    SpinChat_CMDs['chat_send'].responder(chat_send)

    def chat_catchup(self, num):
        self.check_readable()
        if verbose: print 'got chat_catchup', num

        to_send = []
        to_send_len = 0

        start = max(0, len(g_buffer)-num)
        for i in xrange(start, min(len(g_buffer), start+num)):
            # send in batch chunks
            json_data, slength = g_buffer[i]
            if to_send_len + slength + 5 >= SpinChatProtocol.MSG_LIMIT-1000:
                self.callRemote(SpinChat_CMDs['chat_recv_batch'], data = SpinJSON.dumps(to_send, pretty=False))
                to_send = []
                to_send_len = 0
            to_send.append(json_data)
            to_send_len += slength + 5

        if to_send:
            self.callRemote(SpinChat_CMDs['chat_recv_batch'], data = SpinJSON.dumps(to_send, pretty=False))
        return {'success': 1}

    SpinChat_CMDs['chat_catchup'].responder(chat_catchup)


def do_main():
    if not os.path.exists(log_dir):
        os.mkdir(log_dir)

    global exception_log
    exception_log = SpinLog.DailyRawLog(log_dir+'/', '-exceptions.txt')
    global raw_log
    raw_log = exception_log # SpinLog.DailyRawLog(log_dir+'/', '-chatserver.txt', buffer = (not verbose))
    global chat_log
    chat_log = SpinLog.DailyJSONLog(log_dir+'/','-chat.json')

    global nosql_client
    nosql_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']),
                                         identity = 'chatserver', max_retries = -1, # never give up
                                         log_exception_func = lambda x: exception_log.event(server_time, x))

    pf = Factory()
    pf.protocol = ChatProtocolHandlers
    myhost = SpinConfig.config['chatserver'].get('chat_listen_host','localhost')
    myport = SpinConfig.config['chatserver']['chat_port']
    reactor.listenTCP(myport, pf, interface=myhost)

    # SIGHUP forces a full flush and spin_config reload
    def handle_SIGHUP():
        global server_time
        server_time = int(time.time())
        try:
            reload_spin_config()
        except:
            exception_log.event(server_time, 'chatserver SIGHUP Exception: ' + traceback.format_exc())
    signal.signal(signal.SIGHUP, lambda signum, frm: handle_SIGHUP())

    print 'Chat server up and running on %s:%d' % (myhost, myport)

    if daemonize:
        Daemonize.daemonize()

        # update PID file with new PID
        open(pidfile, 'w').write('%d\n' % os.getpid())

        # turn on Twisted logging
        def log_exceptions(eventDict):
            if eventDict['isError']:
                if 'failure' in eventDict:
                    text = ((eventDict.get('why') or 'Unhandled Error')
                            + '\n' + eventDict['failure'].getTraceback().strip())
                else:
                    text = ' '.join([str(m) for m in eventDict['message']])
                exception_log.event(server_time, ('chatserver (%d): ' % os.getpid()) + text)
        def log_raw(eventDict):
            text = log.textFromEventDict(eventDict)
            if text is None or ('connection established' in text) or ('connection lost' in text):
                return
            raw_log.event(server_time, ('chatserver (%d): ' % os.getpid()) + text)

        log.startLoggingWithObserver(log_raw)
        log.addObserver(log_exceptions)

    reactor.run()

def main():
    if os.path.exists(pidfile):
        print 'Chat server is already running (%s).' % pidfile
        sys.exit(1)

    # create PID file
    open(pidfile, 'w').write('%d\n' % os.getpid())
    try:
        do_main()
    finally:
        # remove PID file
        os.unlink(pidfile)

if __name__ == '__main__':
    main()
