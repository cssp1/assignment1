goog.provide('SProbe');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('goog.net.XhrIo');
goog.require('goog.net.ErrorCode');
goog.require('goog.events');

// client network capabilities probe
SProbe.TestState = {INIT:0, PENDING:1, DONE:2};

/** @constructor @struct */
SProbe.Test = function() {
    this.state = SProbe.TestState.INIT;
    this.result = null;
    this.target = new goog.events.EventTarget();
};
SProbe.Test.prototype.listen = function(cb) {
    goog.events.listen(this.target, 'done', cb);
};

/** @constructor @struct
    @extends SProbe.Test */
SProbe.GraphicsTest = function(framerate, canvas_width, canvas_height, canvas_oversample, devicePixelRatio) {
    // doesn't really probe anything, just reports the numbers given
    goog.base(this);
    this.state = SProbe.TestState.DONE;
    this.result = {'result': 'ok', 'framerate': framerate, 'canvas_width':canvas_width, 'canvas_height':canvas_height,
                   'canvas_oversample':canvas_oversample, 'devicePixelRatio':devicePixelRatio};
};
goog.inherits(SProbe.GraphicsTest, SProbe.Test);

/** @constructor @struct
    @extends SProbe.Test */
SProbe.ConnectionTest = function() {
    // doesn't really probe anything, just reports the session connection method used
    goog.base(this);
    this.state = SProbe.TestState.DONE;
    this.result = {'result': 'ok', 'method': gameapi_connection_method()};
};
goog.inherits(SProbe.ConnectionTest, SProbe.Test);

/** @constructor @struct
    @extends SProbe.Test*/
SProbe.AJAXPing = function(url, args) {
    goog.base(this);
    this.launch_time = -1;
    this.url = url;
    this.args = args;
};
goog.inherits(SProbe.AJAXPing, SProbe.Test);
SProbe.AJAXPing.prototype.launch = function() {
    var timeout_sec = 8;
    this.state = SProbe.TestState.PENDING;
    console.log('SProbe.AJAXPing launch '+this.url);
    try {
        goog.net.XhrIo.send(this.url,
                            (function (_this) { return function(event) { _this.response(event); }; })(this),
                            'POST', this.args, {}, 1000*timeout_sec, true);
        this.launch_time = (new Date()).getTime()/1000;
    } catch(e) {
        this.result = {'error': 'exception'};
        this.state = SProbe.TestState.DONE;
        console.log('SProbe.AJAXPing result '+this.url+': exception on launch');
        // cannot go synchronous
        window.setTimeout((function (_this) { return function() { _this.target.dispatchEvent({type: 'done'}); }; })(this), 1);
    }
};

SProbe.AJAXPing.prototype.response = function(event) {
    var end_time = (new Date()).getTime()/1000;
    this.result = {};

    if(!event.target.isSuccess() || (event.target.getResponseText() != 'ok\n' && event.target.getResponseText().indexOf('alive') < 0)) {
        var code = event.target.getLastErrorCode();
        var err;
        if(code === goog.net.ErrorCode.HTTP_ERROR) {
            // we failed to send the request, or got a bad HTTP response code back
            // '0630_client_died_from_ajax_xmit_failure';
            err = 'http_error';
        } else if(code === goog.net.ErrorCode.TIMEOUT) {
            // request was sent but we didn't get an answer within the timeout period
            // '0635_client_died_from_ajax_xmit_timeout';
            err = 'timeout';
        } else {
            // '0639_client_died_from_ajax_unknown_failure';
            err = 'unknown_'+code.toString();
        }
        this.result['error'] = err;
    } else {
        this.result['result'] = 'ok';
        this.result['ping'] = end_time - this.launch_time;
    }
    this.state = SProbe.TestState.DONE;
    console.log('SProbe.AJAXPing result '+this.url+': '+(this.result['result']=='ok' ? 'OK '+(1000.0*this.result['ping']).toFixed(1) +'ms' : this.result['error']));
    this.target.dispatchEvent({type: 'done'});
};


/** @constructor @struct
    @extends SProbe.Test*/
SProbe.WSPing = function(url) {
    goog.base(this);
    this.start_time = -1;
    this.end_time = -1;
    this.url = url;
    this.socket = null;
    this.socket_state = null;
};
goog.inherits(SProbe.WSPing, SProbe.Test);

SProbe.WSPing.SocketState = {CONNECTING:0, SENT:1, CLOSING:2, CLOSED:3, TIMEOUT:4, FAILED:99};

SProbe.WSPing.prototype.launch = function() {
    var timeout_sec = 8;
    this.socket = new WebSocket(this.url);
    this.socket_state = SProbe.WSPing.SocketState.CONNECTING;
    this.socket.onopen = (function (_this) { return function() {
        if(!_this.socket || _this.socket_state != SProbe.WSPing.SocketState.CONNECTING) { return; }
        _this.socket_state = SProbe.WSPing.SocketState.SENT;
        _this.socket.send('{"ping_only":1}');
        _this.start_time = (new Date()).getTime()/1000;
    }; })(this);
    this.socket.onmessage = (function (_this) { return function(event) {
        if(!_this.socket || _this.socket_state != SProbe.WSPing.SocketState.SENT) { return; }
        _this.end_time = (new Date()).getTime()/1000;
        _this.socket.close();
        _this.socket_state = SProbe.WSPing.SocketState.CLOSING;
        if(event.data != 'ok\n') {
            _this.socket_state = SProbe.WSPing.SocketState.FAILED;
            _this.response();
        }
    }; })(this);
    this.socket.onclose = (function (_this) { return function() {
        if(!_this.socket || _this.socket_state != SProbe.WSPing.SocketState.CLOSING) { return; }
        _this.socket_state = SProbe.WSPing.SocketState.CLOSED;
        _this.socket = null;
        _this.response();
    }; })(this);
    this.socket.onerror = (function (_this) { return function(event) {
        //console.log('onerror'); console.log(event);
        _this.socket_state = SProbe.WSPing.SocketState.FAILED;
        _this.socket = null;
        _this.response();
    }; })(this);
    window.setTimeout( (function (_this) { return function() {
        if(!_this.socket || _this.socket_state == SProbe.WSPing.SocketState.CLOSED) { return; }
        _this.socket_state = SProbe.WSPing.SocketState.TIMEOUT;
        _this.response();
    }; })(this), 1000*timeout_sec);

    this.state = SProbe.TestState.PENDING;
    console.log('SProbe.WSPing launch '+this.url);
};

SProbe.WSPing.prototype.response = function() {
    this.result = {};
    if(this.socket_state == SProbe.WSPing.SocketState.CLOSED && (this.end_time > 0) && (this.start_time > 0)) {
        this.result['result'] = 'ok';
        this.result['ping'] = this.end_time - this.start_time;
    } else {
        var err = 'unknown';
        if(this.socket_state == SProbe.WSPing.SocketState.FAILED) {
            err = 'failed';
        } else if(this.socket_state == SProbe.WSPing.SocketState.TIMEOUT) {
            err = 'timeout';
        }
        this.result['error'] = err;
    }
    this.state = SProbe.TestState.DONE;
    console.log('SProbe.WSPing result '+this.url+': '+(this.result['result']=='ok' ? 'OK '+(1000.0*this.result['ping']).toFixed(1) +'ms' : this.result['error']));
    this.target.dispatchEvent({type: 'done'});
};


/** @constructor @struct */
SProbe.ProbeRun = function(cb, proxy_host, proxy_http_port, proxy_ssl_port,
                           game_host, game_snam, game_http_port, game_ssl_port, game_ws_port, game_wss_port,
                           framerate, canvas_width, canvas_height, canvas_oversample, devicePixelRatio) {
    this.cb = cb;
    this.tests = {};

    var snam_param = game_snam ? '&spin_game_server_snam='+game_snam : '';

    var direct_http_must_be_ssl = false;
    // most modern browsers now disallow pages hosted via HTTPS from making non-HTTPS AJAX requests :(
    // so use ONLY HTTPS, if available
    if(spin_server_protocol === 'https://') {
        direct_http_must_be_ssl = true;
    }

    var direct_ws_must_be_ssl = false;
    if(spin_server_protocol === 'https://') {
        // it looks like most browsers are not going to allow non-SSL WebSocket connections when the host page is SSL
        direct_ws_must_be_ssl = true;
    }

    if(framerate > 0) {
        this.tests['graphics'] = new SProbe.GraphicsTest(framerate, canvas_width, canvas_height, canvas_oversample, devicePixelRatio);
    }
    this.tests['connection'] = new SProbe.ConnectionTest();
    /* no browsers allow this in the HTTPS facebook frame
    if(parseInt(proxy_http_port,10) > 0) {
        this.tests['proxy_http'] = new SProbe.AJAXPing("http://"+proxy_host+":"+proxy_http_port+"/PING", "");
    }
    */
    if(parseInt(proxy_ssl_port,10) > 0 && spin_server_protocol === 'https://') {
        // this will fail if main page is loaded via HTTP because of origin mismatch
        this.tests['proxy_ssl'] = new SProbe.AJAXPing("https://"+proxy_host+":"+proxy_ssl_port+"/PING", "");
    }
    if(!spin_game_direct_multiplex && !direct_http_must_be_ssl && parseInt(game_http_port,10) > 0) {
        this.tests['direct_http'] = new SProbe.AJAXPing("http://"+game_host+":"+game_http_port+"/GAMEAPI", "ping_only=1");
    }
    if(parseInt(game_ssl_port,10) > 0) {
        this.tests['direct_ssl'] = new SProbe.AJAXPing(spin_game_direct_multiplex ?
                                                       "https://"+proxy_host+":"+proxy_ssl_port+"/GAMEAPI?spin_game_server_port="+game_ssl_port.toString()+snam_param :
                                                       "https://"+game_host+":"+game_ssl_port+"/GAMEAPI",
                                                       "ping_only=1");
    }
    if(typeof(WebSocket) != 'undefined') {
        if(!direct_ws_must_be_ssl && parseInt(game_ws_port,10) > 0 && (!spin_game_direct_multiplex || parseInt(game_wss_port,10) > 0)) {
            // note: game_wss_port MUST be used for the multiplex case, not game_ws_port, even if connecting via plain HTTP!
            this.tests['direct_ws'] = new SProbe.WSPing(spin_game_direct_multiplex ?
                                                        "ws://"+proxy_host+":"+proxy_http_port+"/WS_GAMEAPI?spin_game_server_port="+game_wss_port.toString()+snam_param :
                                                        "ws://"+game_host+":"+game_ws_port+"/WS_GAMEAPI");
        }
        if(parseInt(game_wss_port,10) > 0) {
            this.tests['direct_wss'] = new SProbe.WSPing(spin_game_direct_multiplex ?
                                                         "wss://"+proxy_host+":"+proxy_ssl_port+"/WS_GAMEAPI?spin_game_server_port="+game_wss_port.toString()+snam_param :
                                                         "wss://"+game_host+":"+game_wss_port+"/WS_GAMEAPI");
        }
    }
};

SProbe.ProbeRun.prototype.go = function() {
    var total = 0, done = 0, launched = false;
    for(var name in this.tests) {
        var test = this.tests[name];
        total += 1;
        if(test.state == SProbe.TestState.DONE) {
            done += 1;
            continue;
        } else if(test.state == SProbe.TestState.PENDING) {
            continue;
        } else if(test.state == SProbe.TestState.INIT) {
            if(!launched) {
                test.listen((function (_this, _name) { return function(event) { _this.go(); }; })(this, name));
                test.launch();
                launched = true;
            }
        }
    }

    if(done >= total) {
        console.log('SProbe tests DONE');
        this.cb(this);
    } else {
        console.log('SProbe tests progress '+done.toString()+'/'+total.toString());
    }
};

SProbe.ProbeRun.prototype.report = function() {
    var ret = {'tests':{}};
    goog.object.forEach(this.tests, function(test, name) {
        if(test.state == SProbe.TestState.DONE) {
            ret['tests'][name] = goog.object.clone(test.result);
        }
    });
    return ret;
};
