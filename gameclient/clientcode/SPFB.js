goog.provide('SPFB');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// this is a wrapper around the Facebook SDK's "FB" function that
// detects cases where Facebook's JavaScript code failed to load asynchronously

// depends on client_time from main.js

goog.require('goog.array');
goog.require('goog.object');

/** Timer to show an informative error message in case the SDK fails to load when it should.
    @type {number|null} */
SPFB.watchdog = null;

SPFB.init_watchdog = function() {
    if(!SPFB.watchdog) {
        SPFB.watchdog = window.setTimeout(SPFB.watchdog_func, 1000*gamedata['client']['facebook_sdk_load_timeout']);
        spin_facebook_sdk_on_init_callbacks.push(SPFB.run_queue);
    }
};

/** @type {!Array<function()>} */
SPFB.queue = [];

/** If the SDK hasn't finished loading, queue up calls we want to make when it finishes.
    @private
    @param {function()} cb */
SPFB.queue_call = function(cb) {
    if(typeof FB !== 'undefined') {
        // SDK is loaded. Just call now.
        cb();
        return;
    }

    // SDK isn't loaded yet, queue it
    SPFB.init_watchdog();
    SPFB.queue.push(cb);
};

/** @private */
SPFB.run_queue = function() {
    if(SPFB.watchdog) {
        window.clearTimeout(SPFB.watchdog);
        // but don't set it to null, to avoid starting it again
    }

    for(var i = 0; i < SPFB.queue.length; i++) {
        var cb = SPFB.queue[i];
        try {
            cb();
        } catch (e) {
            log_exception(e, 'SPFB.run_queue');
        }
    }
};

/** @private */
SPFB.watchdog_func = function() {
    if(typeof FB !== 'undefined') {
        // SDK loaded okay
        return;
    }
    metric_event('0653_facebook_api_failed_to_load', add_demographics({'method':'watchdog'}));

    // show a GUI message, but don't crash the client
    notification_queue.push(function() {
        var msg = gamedata['errors']['FACEBOOK_SDK_FAILED_TO_LOAD'];
        invoke_child_message_dialog(msg['ui_title'], msg['ui_name'],
                                    {'dialog': msg['dialog']});
    });
};

/** @param {Object} props
    @param {function(Object)|null=} callback */
SPFB.ui = function(props, callback) {

    // for critical UIs like payments, show error immediately
    if(typeof FB === 'undefined' && goog.array.contains(['pay','fbpromotion'], props['method'])) {
        metric_event('0653_facebook_api_failed_to_load', add_demographics({'method':props['method']}));

        var msg = gamedata['errors']['FACEBOOK_SDK_FAILED_TO_LOAD'];
        invoke_child_message_dialog(msg['ui_title'], msg['ui_name'],
                                    {'dialog': msg['dialog']});
        return;
    }

    SPFB.queue_call((function(_props, _callback) { return function() {
        // FB dialogs don't work when true full screen is engaged
        if(canvas_is_fullscreen) {
            document['SPINcancelFullScreen']();
        }
        try {
            FB.ui(_props, _callback);
        } catch(e) {
            log_exception(e, 'SPFB.ui('+_props['method']+')');
        }
    }; })(props, callback));
};

/** Facebook wants (url, method, properties, callback) arguments,
    but you can omit method or properties, "shifting" the other ones earlier. Ugly.
   @param {string} url
   @param {?} arg1
   @param {?=} arg2
   @param {?=} arg3 */
SPFB.api = function(url, arg1, arg2, arg3) {
    SPFB.queue_call((function(_url, _arg1, _arg2, _arg3) { return function() {
        try {
            FB.api(_url, _arg1, _arg2, _arg3);
        } catch(e) {
            log_exception(e, 'SPFB.api('+_url+')');
        }
    }; })(url, arg1, arg2, arg3));
};

/** @param {string} url
    @param {string} method
    @param {Object|null} props
    @param {?} callback */
SPFB.api_paged = function(url, method, props, callback) {
    if(!props) { props = {}; }
    var accumulator = {'data': []};
    SPFB.api(url, method, props, goog.partial(SPFB._api_paged_handle_response, url, method, props, callback, accumulator));
};
/** @private
    @param {string} url
    @param {string} method
    @param {Object} props
    @param {function(Object)} callback
    @param {Object.<string,?>} accumulator
    @param {Object.<string,?>} response */
SPFB._api_paged_handle_response = function(url, method, props, callback, accumulator, response) {
    if(!response || response['error'] || !response['data']) {
        throw Error(url+' returned invalid response');
    }
    accumulator['data'] = accumulator['data'].concat(response['data']);
    if('paging' in response && ('next' in response['paging']) && ('cursors' in response['paging']) && ('after' in response['paging']['cursors'])) {
        var new_props = goog.object.clone(props);
        new_props['after'] = response['paging']['cursors']['after'];
        SPFB.api(url, method, new_props, goog.partial(SPFB._api_paged_handle_response, url, method, props, callback, accumulator));
    } else {
        callback(accumulator);
    }
};

/** @param {Function} cb
    @param {boolean=} force */
SPFB.getLoginStatus = function(cb, force) {
    SPFB.queue_call((function (_cb, _force) { return function() {
        try {
            FB.getLoginStatus(_cb, _force);
        } catch(e) {
            log_exception(e, 'SPFB.getLoginStatus');
        }
    }; })(cb, force));
};

// App Events API
// see https://developers.facebook.com/docs/canvas/appevents
// these functions are designed to be safe to call unconditionally; they check spin_frame_platform and enable_fb_app_events internally

SPFB.AppEvents = {};
SPFB.AppEvents.activateApp = function() {
    return; // no longer necessary as of July 2015

    // (Facebook: "App Launches and App Installs are now logged
    // automatically for canvas app users. Calls to the JavaScript
    // SDK's 'activateApp' method are now ignored as they're no longer
    // needed.")

    /*
    console.log('SPFB.AppEvents.activateApp()');
    if(spin_frame_platform != 'fb' || !spin_facebook_enabled || !gamedata['enable_fb_app_events']) { return; }
    if(typeof FB === 'undefined' || typeof FB.AppEvents == 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error', {'method':'AppEvents.activateApp'}, {});
        return;
    }
    return FB.AppEvents.activateApp();
    */
};

/** @param {string} name
    @param {number|null=} value
    @param {Object=} params */
SPFB.AppEvents.logEvent = function(name, value, params) {
    console.log('SPFB.AppEvents.logEvent("'+name+'", '+(value ? value.toString() : 'null')+', '+(params ? JSON.stringify(params) : 'null')+')');
    if(spin_frame_platform != 'fb' || !spin_facebook_enabled || !gamedata['enable_fb_app_events']) { return; }

    SPFB.queue_call((function(_name, _value, _params) { return function() {
        var n;
        if(_name.indexOf('SP_') == 0) { // custom events
            n = _name;
        }  else {
            if(!(_name in FB.AppEvents.EventNames)) { throw Error('FB.AppEvents.EventNames missing '+_name); }
            n = FB.AppEvents.EventNames[_name];
        }

        var props = {};
        if(_params) {
            for(var key in _params) {
                var k;
                if(key.indexOf('SP_') == 0) { // custom parameters
                    k = key;
                } else {
                    if(!(key in FB.AppEvents.ParameterNames)) { throw Error('FB.AppEvents.ParameterNames missing '+key); }
                    k = FB.AppEvents.ParameterNames[key];
                }
                props[k] = _params[key];
            }
        }
        FB.AppEvents.logEvent(n, _value, props);
    }; })(name, value, params));
};

/** Call this to go through the DOM (a specific element's children or the whole DOM)
    and apply any "fb-like" div elements
    @param {HTMLElement=} element */
SPFB.XFBML_parse = function(element) {
    if((spin_frame_platform == 'fb' && spin_facebook_enabled) ||
       (spin_frame_platform == 'bh' && spin_battlehouse_fb_app_id)) {
        SPFB.queue_call((function(_element) { return function() {
            try {
                FB.XFBML.parse(_element || null);
            } catch(e) {
                log_exception(e, 'SPFB.XFBML_parse');
            }
        }; })(element));
    }
};


// All URL calls to graph.facebook.com should use these functions in order to support version configuration:
// please keep in sync with gameserver/SpinFacebook.py

// return the string to put after graph.facebook.com/ and before the endpoint path
// (may be empty, for explicitly un-versioned endpoints)
SPFB.api_version_string = function(feature) {
    var sver;
    if(spin_facebook_api_versions && feature in spin_facebook_api_versions) {
        sver = spin_facebook_api_versions[feature];
    } else if(spin_facebook_api_versions && ('default' in spin_facebook_api_versions)) {
        sver = spin_facebook_api_versions['default'];
    } else {
        sver = 'v2.4'; // fallback default (sync with: FacebookSDK.js, fb_guest.html, gameserver/SpinFacebook.py, gameclient/clientcode/SPFB.js)
    }
    return (sver ? sver+'/' : '');
};

// return the floating-point representation of the version in use
// (may not be empty, always returns fallback default)
SPFB.api_version_number = function(feature) {
    var s = SPFB.api_version_string(feature);
    if(s) {
        return parseFloat(s.slice(1, s.length-1));
    } else {
        return 2.4; // fallback default (sync with: FacebookSDK.js, fb_guest.html, gameserver/SpinFacebook.py, gameclient/clientcode/SPFB.js)
    }
};

/** @param {string} feature
    @param {string} path
    @return {string} */
SPFB.versioned_graph_endpoint = function(feature, path) {
    return 'https://graph.facebook.com/'+SPFB.api_version_string(feature)+path;
};

/** @constructor @struct
    @param {string} id
    @param {string=} init_state */
SPFB.CachedLike = function(id, init_state) {
    this.id = id;
    this.state = init_state || 'unknown';
    this.time = client_time;
};

/** @type {Object<string, !SPFB.CachedLike>} */
SPFB.likes_cache = {};
SPFB.on_likes_cache_update = null;

/** @type {boolean} whether we think we're likely to have accurate "likes" data for this player */
SPFB.likes_are_reliable = false;

/** Initialize the cache with data provided by the server on login
    @param {Object<string,number>} data|null} */
SPFB.preload_likes = function(data) {
    if(data === null) {
        // user privacy setting makes "like" status unreliable
        return;
    } else {
        SPFB.likes_are_reliable = true;
        for(var id in data) {
            SPFB.likes_cache[id] = new SPFB.CachedLike(id, data[id] ? 'likes' : 'does_not_like');
        }
    }
};

SPFB.invalidate_likes_cache = function(on_update) {
    SPFB.on_likes_cache_update = on_update;
    for(var id in SPFB.likes_cache) {
        var entry = SPFB.likes_cache[id];
        if(entry.state == 'does_not_like') {
            entry.state = 'unknown';
        }
    }
};

/** @param {string} id of the Facebook object
    @return {{likes_it: boolean,
              reliable: boolean}} */
SPFB.likes = function(id) {
    var entry;
    if(id in SPFB.likes_cache) {
        entry = SPFB.likes_cache[id];
    } else {
        entry = new SPFB.CachedLike(id);
        SPFB.likes_cache[id] = entry;
    }

    if(entry.state == 'likes') {
        // positives are always reliable
        return {likes_it: true, reliable: true};
    } else if(entry.state == 'does_not_like') {
        // negatives might be reliable, if we've seen other likes from this person
        return {likes_it: false, reliable: SPFB.likes_are_reliable};
    } else if(entry.state == 'pending') {
        return {likes_it: false, reliable: false};
    } else /* if(entry.state == 'unknown') */ {
        entry.state = 'pending';
        //console.log('LIKE REQUEST '+id);
        SPFB.api('/me/likes/'+id, (function (_entry) { return function(response) {
            _entry.time = client_time;
            if(('data' in response) && response['data'].length >= 1 && response['data'][0]['id'] == _entry.id) {
                _entry.state = 'likes';
            } else {
                _entry.state = 'does_not_like';
            }
            //console.log('LIKE RESPONSE '+_entry.id+' = '+_entry.state);
            if(SPFB.on_likes_cache_update) { SPFB.on_likes_cache_update(); }
        }; })(entry));
        return {likes_it: false, reliable: false};
    }
};

goog.exportSymbol('SPFB.likes_cache', SPFB.likes_cache);
