goog.provide('SPDiscord');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Discord localhost API
    loosely based on https://github.com/discordjs/RPC
*/

goog.require('SPWebsocket');
goog.require('goog.events');

function uuid4122() {
    var uuid = '';
    for (var i = 0; i < 32; i += 1) {
        if (i === 8 || i === 12 || i === 16 || i === 20) {
            uuid += '-';
        }
        var n;
        if (i === 12) {
            n = 4;
        } else {
            var random = Math.random() * 16 | 0;
            if (i === 16) {
                n = (random & 3) | 0;
            } else {
                n = random;
            }
        }
        uuid += n.toString(16);
    }
    return uuid;
};

/** @return {boolean} */
SPDiscord.is_supported = function() {
    return SPWebsocket.is_supported() && !!spin_discord_client_id;
};

/** @constructor @struct
 */
SPDiscord.WebSocketTransport = function() {
    this.target = new goog.events.EventTarget();
    this.ws = null;
    this.tries = 0;
    this.connected = false;
};

SPDiscord.WebSocketTransport.prototype.connect = function() {
    if(this.connected) { return; }
    var port = 6463 + (this.tries % 10);
    this.host_and_port = 'localhost:'+port.toString();
    var url = 'ws://'+this.host_and_port+'/?v=1&client_id='+spin_discord_client_id;
    //url = 'ws://localhost:7992/WS_GAMEAPI';
    this.ws = new WebSocket(url);
    this.ws.onopen = goog.bind(this.on_open, this);
    this.ws.onclose = this.ws.onerror = goog.bind(this.on_close, this);
    this.ws.onmessage = goog.bind(this.on_message, this);

};

SPDiscord.WebSocketTransport.prototype.retry = function(e) {
    if(e.code === 1006) {
        this.tries += 1;
    }
    this.connect();
};

SPDiscord.WebSocketTransport.prototype.send = function(data) {
    if(!this.ws) { return; }
    this.ws.send(JSON.stringify(data));
};

SPDiscord.WebSocketTransport.prototype.close = function() {
    if(!this.ws) { return; }
    this.ws.close();
};

SPDiscord.WebSocketTransport.prototype.on_message = function(event) {
    this.target.dispatchEvent({type: 'message', data: JSON.parse(event.data)});
};

SPDiscord.WebSocketTransport.prototype.on_error = function(event) {
    console.log('SPDiscord.WebSocketTransport.on_error', event);
};

SPDiscord.WebSocketTransport.prototype.on_open = function(event) {
    console.log('SPDiscord.WebSocketTransport.on_open');
    this.target.dispatchEvent({type: 'open'});
    return false;
};
SPDiscord.WebSocketTransport.prototype.on_close = function(e) {
    console.log('SPDiscord.WebSocketTransport.on_close', e);
    try {
        this.ws.close();
        this.ws = null;
    } catch (err) {}

    var derr = e.code >= 4000 && e.code < 5000;
    if(!e.code || derr) {
        this.target.dispatchEvent({type: 'close', data: e});
    }
    if(!derr) {
       // setTimeout(goog.bind(this.retry, this, e), 250); // XXXXXX
    }
};


/** @constructor @struct
 */
SPDiscord.RPCClient = function() {
    this.accessToken = null;
    this.clientId = null;
    this.expecting = {};
    this.subscriptions = {};
    this.transport = new SPDiscord.WebSocketTransport();
    goog.events.listen(this.transport.target, 'message', goog.bind(this.on_rpc_message, this));
};

SPDiscord.RPCClient.prototype.on_rpc_message = function(event) {
    var message = event.data;
    if(message['cmd'] === 'DISPATCH' && message['evt'] === 'READY') {
        if(message['data']['user']) {
            this.user = message['data']['user']
        }
        this.target.dispatchEvent({type: 'connected'});
    } else if(message['nonce'] in this.expecting) {
        var resolve_reject = this.expecting[message['nonce']];
        if(message['evt'] === 'ERROR') {
            var e = new Error(message['data']['message']);
            e.code = message['data']['code'];
            e.data = message['data'];
            resolve_reject[1](e);
        } else {
            resolve_reject[0](message['data']);
        }
        delete this.expecting[message['nonce']];
    } else {
        var subid = subKey(message['evt'], message['args']);
        if(!(subid in this.subscriptions)) {
            return;
        }
        this.subscriptions[subid](message['data']);
    }
};

/** @param {string} cmd
    @param {Object} args
    @param {string} evt */
SPDiscord.RPCClient.prototype.request = function(cmd, args, evt) {
    return new Promise((function (_this) { return function(resolve, reject) {
        var nonce = uuid4122();
        _this.transport.send({'cmd': cmd, 'args': args, 'evt': evt, 'nonce': nonce});
        _this.expecting[nonce] = [resolve, reject];
    };})(this));
}

 /**
   * Sets the presence for the logged in user.
   * @param {Object} args The rich presence to pass.
   */
SPDiscord.RPCClient.prototype.set_activity = function(args) {
    this.request('SET_ACTIVITY', {'pid': null,
                                  'activity': {
                                      'state': 'playing',
                                      'details': 'abcdefg',
                                      'timestamps': {
                                          'start': server_time,
                                          'end': -1
                                      },
                                      'assets': {
                                          'large_image': 'asdf',
                                          'large_text': 'fdsa',
                                          'small_image': 'FSDFSDF',
                                          'small_text': 'SDFSDF'
                                      }
                                  }
                                 });
};
