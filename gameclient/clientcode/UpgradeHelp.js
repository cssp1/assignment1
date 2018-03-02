goog.provide('UpgradeHelp');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Track state for GameObject upgrade_help
*/

/** @constructor @struct */
UpgradeHelp.UpgradeHelp = function() {
    this.help_requested = false;
    this.help_request_expire_time = -1;
    this.help_completed = false;
    this.time_saved = -1;
};

/** @param {null|number|Object<string,?>} state */
UpgradeHelp.UpgradeHelp.prototype.receive_state = function(state) {
    if(state === null || state === -1) {
        return; // blank
    }
    if(typeof(state) === 'number') {
        // legacy format
        if(state === 0) {
            this.help_requested = true;
        } else if(state > 0) {
            this.help_completed = true;
            this.time_saved = state;
        }
    } else if(typeof(state) === 'object') {
        // new format
        self.help_requested = !!state['help_requested'];
        self.help_request_expire_time = ('help_request_expire_time' in state ? /** @type {number} */ (state['help_request_expire_time']) : -1);
        self.help_completed = !!state['help_completed'];
        self.time_saved = ('time_saved' in state ? /** @type {number} */ (state['time_saved']) : -1);
    } else {
        throw Error('unhandled state '+JSON.stringify(state));
    }
};
