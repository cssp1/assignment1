goog.provide('SPArmorGames');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    This is a wrapper around the Armor Gamess SDK that
    detects cases where it failed to load asynchronously.
*/

SPArmorGames.ping = function() {
    if(typeof agi === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0652_client_died_from_armorgames_api_error', {'method':'ping'}, {});
        return;
    }
    agi.ping();
};

/** @param {!Object} arg */
SPArmorGames.setIframeDimensions = function(arg) {
    if(typeof agi === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0652_client_died_from_armorgames_api_error', {'method':'setIframeDimensions'}, {});
        return;
    }
    agi.setIframeDimensions(arg);
};
