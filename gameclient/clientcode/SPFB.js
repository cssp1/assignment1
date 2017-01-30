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

goog.require('goog.object');

/** @param {Object} props
    @param {function(Object)|null=} callback */
SPFB.ui = function(props, callback) {
    if(typeof FB === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error',
                               {'method':props['method']}, {});
        return null;
    }

    // FB dialogs don't work when true full screen is engaged
    if(canvas_is_fullscreen) {
        document['SPINcancelFullScreen']();
    }

    return FB.ui(props, callback);
};

/** Facebook wants (url, method, properties, callback) arguments,
    but you can omit method or properties, "shifting" the other ones earlier. Ugly.
   @param {string} url
   @param {?} arg1
   @param {?=} arg2
   @param {?=} arg3 */
SPFB.api = function(url, arg1, arg2, arg3) {
    if(typeof FB === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error',
                               {'method':'api:'+url}, {});
        return null;
    }
    return FB.api(url, arg1, arg2, arg3);
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
    if(typeof FB === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error',
                               {'method':'getLoginStatus'}, {});
        return;
    }
    FB.getLoginStatus(cb, force);
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
    if(typeof FB === 'undefined' || typeof FB.AppEvents == 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error', {'method':'AppEvents.logEvent('+name+')'}, {});
        return;
    }

    var n;
    if(name.indexOf('SP_') == 0) { // custom events
        n = name;
    }  else {
        if(!(name in FB.AppEvents.EventNames)) { throw Error('FB.AppEvents.EventNames missing '+name); }
        n = FB.AppEvents.EventNames[name];
    }

    var props = {};
    if(params) {
        for(var key in params) {
            var k;
            if(key.indexOf('SP_') == 0) { // custom parameters
                k = key;
            } else {
                if(!(key in FB.AppEvents.ParameterNames)) { throw Error('FB.AppEvents.ParameterNames missing '+key); }
                k = FB.AppEvents.ParameterNames[key];
            }
            props[k] = params[key];
        }
    }
    return FB.AppEvents.logEvent(n, value, props);
};

/** Call this to go through the DOM (a specific element's children or the whole DOM)
    and apply any "fb-like" div elements
    @param {HTMLElement=} element */
SPFB.XFBML_parse = function(element) {
    if((spin_frame_platform == 'fb' && spin_facebook_enabled) ||
       (spin_frame_platform == 'bh' && spin_battlehouse_fb_app_id)) {
        if(typeof FB === 'undefined' || typeof FB.XFBML == 'undefined') {
            // note: calls back into main.js
            invoke_timeout_message('0650_client_died_from_facebook_api_error', {'method':'XFBML_parse'}, {});
            return;
        }
        return FB.XFBML.parse(element || null);
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

SPFB.likes_cache = {};
SPFB.on_likes_cache_update = null;

/** @constructor @struct
    @param {string} id
    @param {string=} init_state */
SPFB.CachedLike = function(id, init_state) {
    this.id = id;
    this.state = init_state || 'unknown';
    this.time = client_time;
};

/** Initialize the cache with data provided by the server on login
    @param {Object<string,number>} data} */
SPFB.preload_likes = function(data) {
    for(var id in data) {
        SPFB.likes_cache[id] = new SPFB.CachedLike(id, data[id] ? 'likes' : 'does_not_like');
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

SPFB.likes = function(id) {
    var entry;
    if(id in SPFB.likes_cache) {
        entry = SPFB.likes_cache[id];
    } else {
        entry = new SPFB.CachedLike(id);
        SPFB.likes_cache[id] = entry;
    }

    if(entry.state == 'likes') {
        return true;
    } else if(entry.state == 'pending') {
        return false;
    } else if(entry.state == 'unknown') {
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
        return false; // for now
    }
};

goog.exportSymbol('SPFB.likes_cache', SPFB.likes_cache);
