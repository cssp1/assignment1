goog.provide('SPKongregate');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    This is a wrapper around Kongregate's SDK that
    detects cases where it failed to load asynchronously.
*/


/** @param {string} arg0
    @param {function(?)} arg1 */
SPKongregate.purchaseItemsRemote = function(arg0, arg1) {
    var err = '0651_client_died_from_kongregate_api_error';
    var props = {'method':'purchaseItemsRemote'};

    if(typeof kongregate === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message(err, props, {});
        return null;
    }

    // dialogs don't work when true full screen is engaged
    if(canvas_is_fullscreen) {
        document['SPINcancelFullScreen']();
    }

    kongregate['mtx']['purchaseItemsRemote'](arg0, arg1);
};


/** @param {!Object} arg0 */
SPKongregate.showInvitationBox = function(arg0) {
    var err = '0651_client_died_from_kongregate_api_error';
    var props = {'method':'showInvitationBox'};

    if(typeof kongregate === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message(err, props, {});
        return null;
    }

    // dialogs don't work when true full screen is engaged
    if(canvas_is_fullscreen) {
        document['SPINcancelFullScreen']();
    }

    kongregate['services']['showInvitationBox'](arg0);
};
