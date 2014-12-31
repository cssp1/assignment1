goog.provide('SPFB');

// Copyright (c) 2014 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// this is a wrapper around the Facebook SDK's "FB" function that
// detects cases where Facebook's JavaScript code failed to load asynchronously

// depends on client_time from main.js

// global namespace
SPFB = {};

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

SPFB.api = function(url, method, props) {
    if(typeof FB === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error',
                               {'method':'api:'+url}, {});
        return null;
    }
    return FB.api(url, method, props);
};

// App Events API
// see https://developers.facebook.com/docs/canvas/appevents
// these functions are designed to be safe to call unconditionally; they check spin_frame_platform and enable_fb_app_events internally

SPFB.AppEvents = {};
SPFB.AppEvents.activateApp = function() {
    console.log('SPFB.AppEvents.activateApp()');
    if(spin_frame_platform != 'fb' || !spin_facebook_enabled || !gamedata['enable_fb_app_events']) { return; }
    if(typeof FB === 'undefined' || typeof FB.AppEvents == 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0650_client_died_from_facebook_api_error', {'method':'AppEvents.activateApp'}, {});
        return;
    }
    return FB.AppEvents.activateApp();
};
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
        sver = 'v2.1'; // fallback default (sync with: FacebookSDK.js, fb_guest.html, gameserver/SpinFacebook.py, gameclient/clientcode/SPFB.js)
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
        return 2.1; // fallback default (sync with: FacebookSDK.js, fb_guest.html, gameserver/SpinFacebook.py, gameclient/clientcode/SPFB.js)
    }
};

SPFB.versioned_graph_endpoint = function(feature, path) {
    return 'https://graph.facebook.com/'+SPFB.api_version_string(feature)+path;
};

SPFB.likes_cache = {};
SPFB.on_likes_cache_update = null;

/** @constructor */
SPFB.CachedLike = function(id) {
    this.id = id;
    this.state = 'unknown';
    this.time = client_time;
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
    }
};

goog.exportSymbol('SPFB.likes_cache', SPFB.likes_cache);
