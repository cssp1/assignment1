goog.provide('SPArmorGames');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// this is a wrapper around Armor Gamess SDK that
// detects cases whereit failed to load asynchronously

// depends on client_time from main.js

// global namespace
SPArmorGames = {};

SPArmorGames.ping = function() {
    if(typeof agi === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0652_client_died_from_armorgames_api_error', {'method':'ping'}, {});
        return;
    }
    agi.ping();
};

SPArmorGames.setIframeDimensions = function(arg) {
    if(typeof agi === 'undefined') {
        // note: calls back into main.js
        invoke_timeout_message('0652_client_died_from_armorgames_api_error', {'method':'setIframeDimensions'}, {});
        return;
    }
    agi.setIframeDimensions(arg);
};
