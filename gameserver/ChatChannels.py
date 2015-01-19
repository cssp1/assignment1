# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# manage listeners and broadcasts for individual chat channels

class ChatChannel(object):
    def __init__(self, name):
        self.name = name
        self.listeners = []

    def join(self, member):
        self.listeners.append(member)
    def leave(self, member):
        if member in self.listeners:
            self.listeners.remove(member)
    def send(self, sender_info, text, exclude_listener = None):
        for member in self.listeners:
            if member is exclude_listener: continue
            member.chat_recv(self.name, sender_info, text)

# note: "relay" is optionally an instance of SpinChatClient.Client,
# to perform relaying to/from the global chat server

class ChatChannelMgr(object):
    def __init__(self, relay = None):
        self.relay = relay
        if self.relay:
            self.relay.listener = self.relay_recv
        self.channels = {}

    def join(self, session, channame):
        if channame not in self.channels:
            self.channels[channame] = ChatChannel(channame)
        self.channels[channame].join(session)
        return channame
    def leave(self, session, channame):
        assert channame
        if channame in self.channels:
            self.channels[channame].leave(session)

    def send(self, channame, sender, text, log = True, exclude_listener = None):
        if channame in self.channels:
            self.channels[channame].send(sender, text, exclude_listener = exclude_listener)
        if self.relay:
            self.relay.chat_send({'channel':channame, 'sender':sender, 'text': text}, log = log)

    def relay_recv(self, data):
        channel = data['channel']
        sender = data['sender']
        text = data.get('text','')
        if channel not in self.channels:
            self.channels[channel] = ChatChannel(channel)
        self.channels[channel].send(sender, text)

