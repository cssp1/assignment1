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

/** @constructor @struct
    @param {string} url
    @param {number} connect_timeout
    @param {number} msg_timeout
    @param {number} enable_reconnect
        (0: disable, 1: reconnect for errors we are certain are transient,
         2: reconnect even for "clean" shutdowns)
    @param {number} min_delay
*/
SPWebsocket.SPWebsocket = function(url, connect_timeout, msg_timeout, enable_reconnect, min_delay) {
    this.url = url;
    this.connect_timeout = connect_timeout;
    this.msg_timeout = msg_timeout;
    this.enable_reconnect = enable_reconnect;
    this.min_delay = min_delay;
    this.socket = null;
    this.socket_state = SPWebsocket.SocketState.CLOSED;
    this.target = new goog.events.EventTarget();
    this.connect_watchdog = null;
    this.connect_time = -1;
    this.delay_timer = null;
    this.msg_watchdog = null;
    this.msg_time = -1;
    this.to_send = [];
    this.retry_count = 0; // count reconnection attempts
    this.recv_count = 0; // count received packets
    /** @type {string|null} */
    this.last_close_ui_method = null; // debug info about last close event, for use after reconnect
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

/** @return {boolean} */
SPWebsocket.SPWebsocket.prototype.is_reconnecting = function() {
    return this.socket_state === SPWebsocket.SocketState.CONNECTING && this.retry_count > 0;
};

SPWebsocket.SPWebsocket.prototype.close = function() {
    if(this.socket) {
        if(this.socket_state != SPWebsocket.SocketState.CLOSING) {
            this.socket_state = SPWebsocket.SocketState.CLOSING;
            this.socket.close();
        }
    }
    this.clear_socket();
};

/** @private */
SPWebsocket.SPWebsocket.prototype.clear_socket = function() {
    if(this.socket) {
        this.socket.onopen =
            this.socket.onclose =
            this.socket.onmessage =
            this.socket.onerror = null;
        this.socket = null;
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

/** @private */
SPWebsocket.SPWebsocket.prototype._flush_to_send = function() {
    if(this.delay_timer) { return; }

    while(this.to_send.length > 0) {
        this.socket.send(this.to_send[0]);
        this.to_send.splice(0,1);

        if(this.min_delay > 0) {
            // for Safari 10.1 work-around: wait before sending again
            this.delay_timer = window.setTimeout(goog.bind(this._flush_to_send_timeout, this), 1000*this.min_delay);
            break;
        }
    }
};

/** @private */
SPWebsocket.SPWebsocket.prototype._flush_to_send_timeout = function() {
    this.delay_timer = null;
    if(this.socket_state == SPWebsocket.SocketState.CONNECTED) {
        this._flush_to_send();
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
    if(this.retry_count > 0) {
        this.target.dispatchEvent({type: 'reconnect', data: null});
    }
    this._flush_to_send();
};
SPWebsocket.SPWebsocket.prototype.on_open_timeout = function() {
    this.socket_state = SPWebsocket.SocketState.FAILED;
    this.clear_socket();
    this.target.dispatchEvent({type: 'error', data: 'connect_timeout'});
};

/** @param {!MessageEvent} event
    @suppress {reportUnknownTypes} Closure don't like the ambiguous type of event.data - maybe outdated externs */
SPWebsocket.SPWebsocket.prototype.on_message = function(event) {
    if(!this.socket || this.socket_state != SPWebsocket.SocketState.CONNECTED) { throw Error('invalid state for onmessage()'); }
    this.recv_count += 1;
    var event_data = /** @type {string} */ (event.data);
    this.target.dispatchEvent({type: 'message', data: event_data});
};

/** @private
    @param {!CloseEvent} event
    @return {boolean} if we should attempt to reconnect */
SPWebsocket.SPWebsocket.prototype.close_event_is_recoverable = function(event) {
    if(this.recv_count < 1) {
        // if we never successfully got any data from the server,
        // then this is probably a client-side issue, like the browser
        // denying the connection. Let it fail immediately instead of retrying.
        return false;
    }

    if(event.code == 1001) {
        // proxy needs to restart (sometimes sent by CloudFlare)
        return true;
    } else if(event.code === 1005 || event.code === 1006) {
        if(event.wasClean !== undefined && !event.wasClean) {
            // non-clean shutdown
            return true;

        }

        // sometimes CloudFlare uses code 1005 instead of 1001 for a proxy restart
        if(event.reason && typeof(event.reason) === 'string') {
            /** @type {string} */
            var s_reason = /** @type {string} */ (event.reason.toString());
            if(s_reason.indexOf('CloudFlare') != -1) {
                return true;
            }
        }

        // should we always classify codes 1005/1006 as recoverable, even if clean?
        if(this.enable_reconnect >= 2) {
            return true;
        }
    }
    return false;
};

/** @param {!Event} _event */
SPWebsocket.SPWebsocket.prototype.on_close = function(_event) {
    var event = /** @type {!CloseEvent} */ (_event);
    if(this.socket) {
        // if it wasn't us closing the connection, then this represents some kind of failure (server-side close)
        if(this.socket_state != SPWebsocket.SocketState.CLOSING) {
            this.socket_state = SPWebsocket.SocketState.CLOSED;

            // gather info about the event
            var ui_code = (event.code || 0).toString();
            var ui_reason = event.reason || 'unknown';
            var was_clean = event.wasClean;
            var ui_was_clean = (was_clean !== undefined ? (was_clean ? 'clean': 'not_clean') : 'unknown');
            var ui_method = ui_code+':'+ui_reason+':'+ui_was_clean+':'+this.recv_count.toString();
            this.last_close_ui_method = ui_method;

            if(this.enable_reconnect >= 1 && this.close_event_is_recoverable(event)) {
                this.retry_count += 1;
                this.clear_socket();
                this.connect();
                return;
            }

            this.target.dispatchEvent({type: 'shutdown', data: ui_method});
        }

        // leave it in FAILED state if it's failed previously
        if(this.socket_state != SPWebsocket.SocketState.FAILED) {
            this.socket_state = SPWebsocket.SocketState.CLOSED;
        }
        this.clear_socket();
    }
};
/** @param {!Event} event */
SPWebsocket.SPWebsocket.prototype.on_error = function(event) {
    this.socket_state = SPWebsocket.SocketState.FAILED;
    this.clear_socket();
    this.target.dispatchEvent({type: 'error', data: 'error'});
};

/** For testing, pretend that the socket went down unexpectedly */
SPWebsocket.SPWebsocket.prototype.inject_failure = function(event) {
    var e = new Event('test');
    e.code = 1001;
    e.reason = 0;
    e.wasClean = false;
    this.on_close(e);
};
