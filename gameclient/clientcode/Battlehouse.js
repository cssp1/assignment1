goog.provide('Battlehouse');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Interaction with the battlehouse.com iframe

    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.events');
goog.require('goog.object');

Battlehouse.postMessage_receiver = new goog.events.EventTarget();

/** @private
    @param {string} method_name
    @return {!Promise} */
Battlehouse.remote_method_call = function(method_name) {
    return new Promise(function(resolve, reject) {
        Battlehouse.postMessage_receiver.listenOnce(method_name,
                                                    function(event) { if('result' in event.result) {
                                                        resolve(event.result['result']);
                                                    } else {
                                                        reject(event.result['error']);
                                                    } });
        window.top.postMessage(method_name, '*');
    });
};

/** @return {boolean} */
Battlehouse.web_push_supported = function() {
    // duplicate this code here to avoid needing to load BHSDK
    return ('serviceWorker' in navigator) && ('PushManager' in window);
};

/** @return {!Promise} */
Battlehouse.web_push_subscription_check = function() {
    return Battlehouse.remote_method_call('bh_web_push_subscription_check');
};

/** @return {!Promise} */
Battlehouse.web_push_subscription_ensure = function() {
    return Battlehouse.remote_method_call('bh_web_push_subscription_ensure');
};


Battlehouse.on_postMessage = function(e) {
    if(spin_battlehouse_api_path.indexOf(e.origin) !== 0) {
        console.log('unexpected origin '+e.origin+' for postMessage, ignoring.');
        return;
    }
    var data = /** @type {!Object} */ (JSON.parse(e.data));
    if('bh_access_token' in data) {
        // update the access token
        spin_battlehouse_access_token = /** string */ (data['bh_access_token']);
    } else {
        // it's a reply to an async method call - see battlehouse-login play.html for the other side
        var method_name = goog.object.getAnyKey(data);
        Battlehouse.postMessage_receiver.dispatchEvent({type: method_name, result: data[method_name]});
    }
}


Battlehouse.show_how_to_bookmark = function() {
    if(spin_frame_platform !== 'bh') {
        throw Error('wrong frame_platform');
    }
    BHSDK.bh_popup_show_how_to_bookmark();
};

Battlehouse.invite_code_get = function(game_id, cb) {
    // XXX make this call up to the iframe?
    return BHSDK.bh_invite_code_get(game_id, cb);
};
