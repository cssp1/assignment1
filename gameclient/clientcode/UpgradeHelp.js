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
        this.help_requested = !!state['help_requested'];
        this.help_request_expire_time = ('help_request_expire_time' in state ? /** @type {number} */ (state['help_request_expire_time']) : -1);
        this.help_completed = !!state['help_completed'];
        this.time_saved = ('time_saved' in state ? /** @type {number} */ (state['time_saved']) : -1);
    } else {
        throw Error('unhandled state '+JSON.stringify(state));
    }
};

/** @param {number} time_now
    @return {boolean} */
UpgradeHelp.UpgradeHelp.prototype.can_request_now = function(time_now) {
    if(this.help_completed) {
        return false; // already got help
    }
    if(!this.help_requested) {
        return true; // not requested yet
    }
    if(this.help_request_expire_time < 0) {
        return false; // unknown expire time
    }
    if(time_now < this.help_request_expire_time) {
        return false; // not timed out yet
    }
    return true;
};
