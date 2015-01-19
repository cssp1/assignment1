goog.provide('SPWebsocket');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.events');
goog.require('goog.array');

SPWebsocket.SocketState = {CONNECTING:0, CONNECTED:1, CLOSING:2, CLOSED:3, TIMEOUT:4, FAILED:99};

SPWebsocket.is_supported = function() {
    try {
        if(typeof(WebSocket) != 'undefined') {
            return true;
        }
    } catch(e) {};
    return false;
};

/** @constructor */
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
    this.socket.onopen = (function (_this) { return function() { _this.on_open(); }; })(this);
    this.socket.onclose = (function (_this) { return function() { _this.on_close(); }; })(this);
    this.socket.onmessage = (function (_this) { return function(event) { _this.on_message(event); }; })(this);
    this.socket.onerror = (function (_this) { return function(event) { _this.on_error(event); }; })(this);
    this.connect_watchdog = window.setTimeout((function (_this) { return function() { _this.on_open_timeout(); }; })(this), 1000*this.connect_timeout);
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
SPWebsocket.SPWebsocket.prototype.on_message = function(event) {
    if(!this.socket || this.socket_state != SPWebsocket.SocketState.CONNECTED) { throw Error('invalid state for onmessage()'); }
    this.target.dispatchEvent({type: 'message', data: event.data});
};

SPWebsocket.SPWebsocket.prototype.on_close = function() {
    if(this.socket) {
        // if it wasn't us closing the connection, then this represents some kind of failure (server-side close)
        if(this.socket_state != SPWebsocket.SocketState.CLOSING) {
            this.socket_state = SPWebsocket.SocketState.FAILED;
        }

        // leave it in FAILED state if it's failed previously
        if(this.socket_state != SPWebsocket.SocketState.FAILED) {
            this.socket_state = SPWebsocket.SocketState.CLOSED;
        }
        this.socket = null;
    }
};
SPWebsocket.SPWebsocket.prototype.on_error = function(event) {
    this.socket_state = SPWebsocket.SocketState.FAILED;
    this.socket = null;
    this.target.dispatchEvent({type: 'error', data: 'error'});
};
