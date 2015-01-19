# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AMP command protocol for client/server chat connection

default_secret_read_only = 'asdfchat'
default_secret_full = 'fdsachat'

# maximum byte length of individual requests or responses, set by AMP protocol
MSG_LIMIT = 60000

# although these are just Twisted AMP Commands, we must define them
# generically because they are used by both the server side (under
# twisted.protocols.amp) and client side - under the ampy module, which
# is not compatible with Twisted's objects.

commands = {
    'authenticate': { 'arguments': [['secret', 'string'],
                                    ['identity', 'string'],
                                    ['subscribe', 'boolean']],
                      'response': [['state', 'integer']]
                      },

    # client -> server
    'chat_send': { 'arguments': [['data', 'string'], ['log', 'boolean']],
                   'response': [['success', 'integer']],
                   'requiresAnswer': False
                   },
    # server -> client
    'chat_recv': { 'arguments': [['data', 'string']],
                   'response': [['success', 'integer']],
                   'requiresAnswer': False
                   },
    'chat_recv_batch': { 'arguments': [['data', 'string']],
                         'response': [['success', 'integer']],
                         'requiresAnswer': False
                         },

    # client -> server
    # requests pull of last 'num' messages sent by other clients
    'chat_catchup': { 'arguments': [['num', 'integer']],
                      'response': [['success', 'integer']],
                      'requiresAnswer': False
                      },
}
