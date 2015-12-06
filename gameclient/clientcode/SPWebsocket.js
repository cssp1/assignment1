goog.provide('SPWebsocket');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    WebSocket state management for the game client
*/

goog.require('goog.events');

/** @enum {number} */
SPWebsocket.SocketState = {CONNECTING:0, CONNECTED:1, CLOSING:2, CLOSED:3, TIMEOUT:4, FAILED:99};

/** @return {boolean} */
SPWebsocket.is_supported = function() { return (typeof(WebSocket) != 'undefined'); };

/** @constructor
    @struct
    @param {string} url
    @param {number} connect_timeout
    @param {number} msg_timeout */
SPWebsocket.SPWebsocket = function(url, connect_timeout, msg_timeout) {
    this.url = url;
    this.connect_timeout = connect_timeout;
    this.msg_timeout = msg_timeout;
    this.socket = null;
    this.socket_state = SPWebsocket.SocketState.CLOSED;
    this.target = new goog.events.EventTarget();
    this.connect_watchdog = null;
    this.connect_time = -1;
    this.msg_watchdog = null;
    this.msg_time = -1;
    this.to_send = [];
};
SPWebsocket.SPWebsocket.prototype.connect = function() {
    if(this.socket) { throw Error('invalid state for connect()'); }
    this.socket = new WebSocket(this.url);
    this.socket_state = SPWebsocket.SocketState.CONNECTING;
    this.socket.onopen = goog.bind(this.on_open, this);
    this.socket.onclose = goog.bind(this.on_close, this);
    this.socket.onmessage = goog.bind(this.on_message, this);
    this.socket.onerror = goog.bind(this.on_error, this);
    this.connect_watchdog = window.setTimeout(goog.bind(this.on_open_timeout, this), 1000*this.connect_timeout);
    this.connect_time = (new Date()).getTime()/1000;
};
SPWebsocket.SPWebsocket.prototype.close = function() {
    if(this.socket) {
        if(this.socket_state != SPWebsocket.SocketState.CLOSING) {
            this.socket.close();
            this.socket_state = SPWebsocket.SocketState.CLOSING;
        }
    }
    if(this.connect_watchdog) {
        window.clearTimeout(this.connect_watchdog);
        this.connect_watchdog = null;
    }
    if(this.msg_watchdog) {
        window.clearTimeout(this.msg_watchdog);
        this.msg_watchdog = null;
    }
};

SPWebsocket.SPWebsocket.prototype._flush_to_send = function() {
    while(this.to_send.length > 0) {
        this.socket.send(this.to_send[0]);
        this.to_send.splice(0,1);
    }
};

/** @param {string} data */
SPWebsocket.SPWebsocket.prototype.send = function(data) {
    this.to_send.push(data);
    if(this.socket && this.socket_state == SPWebsocket.SocketState.CONNECTED) {
        this._flush_to_send();
    } else if(this.socket && this.socket_state == SPWebsocket.SocketState.CONNECTING) {
        // waiting to connect
    } else if(this.socket_state == SPWebsocket.SocketState.FAILED) {
        this.target.dispatchEvent({type: 'error', data: 'xmit_error'});
    } else {
        throw Error('invalid state for send()');
    }

    if(this.msg_watchdog) {
        window.clearTimeout(this.msg_watchdog);
        this.msg_watchdog = null;
    }
};

SPWebsocket.SPWebsocket.prototype.on_open = function() {
    if(!this.socket || this.socket_state != SPWebsocket.SocketState.CONNECTING) { throw Error('invalid state'); }
    this.socket_state = SPWebsocket.SocketState.CONNECTED;
    if(this.connect_watchdog) {
        window.clearTimeout(this.connect_watchdog);
        this.connect_watchdog = null;
    }
    this._flush_to_send();
};
SPWebsocket.SPWebsocket.prototype.on_open_timeout = function() {
    this.socket_state = SPWebsocket.SocketState.FAILED;
    this.socket = null;
    this.target.dispatchEvent({type: 'error', data: 'connect_timeout'});
};

/** @param {!MessageEvent} event
    @suppress {reportUnknownTypes} Closure don't like the ambiguous type of event.data - maybe outdated externs */
SPWebsocket.SPWebsocket.prototype.on_message = function(event) {
    if(!this.socket || this.socket_state != SPWebsocket.SocketState.CONNECTED) { throw Error('invalid state for onmessage()'); }
    var event_data = /** @type {string} */ (event.data);
    this.target.dispatchEvent({type: 'message', data: event_data});
};

SPWebsocket.SPWebsocket.prototype.on_close = function() {
    if(this.socket) {
        // if it wasn't us closing the connection, then this represents some kind of failure (server-side close)
        if(this.socket_state != SPWebsocket.SocketState.CLOSING) {
            this.socket_state = SPWebsocket.SocketState.CLOSED;
            this.target.dispatchEvent({type: 'shutdown', data: 'server_initiated'});
        }

        // leave it in FAILED state if it's failed previously
        if(this.socket_state != SPWebsocket.SocketState.FAILED) {
            this.socket_state = SPWebsocket.SocketState.CLOSED;
        }
        this.socket = null;

        // kill watchdog timers etc. Won't recurse since this.socket is null now
        this.close();
    }
};
/** @param {!Event} event */
SPWebsocket.SPWebsocket.prototype.on_error = function(event) {
    this.socket_state = SPWebsocket.SocketState.FAILED;
    this.socket = null;
    this.target.dispatchEvent({type: 'error', data: 'error'});
};
