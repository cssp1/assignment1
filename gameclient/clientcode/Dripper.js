goog.provide('Dripper');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    This is a little utility for making GUI buttons that you hold down
    and then emit a stream of increasingly-fast events as it continues
    to be held down. Mainly, unit deployment in SG.
*/

Dripper.rate_table = [
    [0, 1],
    [1, 2], // after 1 second, double the event rate
    [2, 4], // after 2 seconds quadruple the event rate
    [3, 8]  // after 3 seconds octuple the event rate
];

/** @typedef {function(?=): boolean} */
Dripper.Callback;

/** @constructor
    @struct
    @param {Dripper.Callback|null} cb
    @param {number} rate
    @param {number} origin_time
*/
Dripper.Dripper = function(cb, rate, origin_time) {
    this.cb = cb;
    this.origin_time = origin_time; // time at which the drip operation begins
    this.last_time = -1; // time at which activate() was last evaluated, -1 if never
    this.resid = 0; // residual fraction of a call accumulated since last_time
    this.rate = rate;
    this.times_fired = 0; // how many times the callback has been run
};

/** @param {Dripper.Callback|null} cb
    @param {number} rate
    @param {number} origin_time
*/
Dripper.Dripper.prototype.reset = function(cb, rate, origin_time) {
    this.cb = cb;
    this.rate = rate;
    this.origin_time = origin_time;
};

/** Just reset the speed-up scaling without changing anything else
    @param {number} current_time
*/
Dripper.Dripper.prototype.reset_speed = function(current_time) {
    this.origin_time = current_time;
};

/** @param {boolean=} call_cb whether to call the callback
    @param {?=} param parameter to pass the callback
    @suppress {reportUnknownTypes} - Closure doesn't deal with the callback param being typeless
*/
Dripper.Dripper.prototype.stop = function(call_cb, param) {
    if(!this.is_active()) return;

    // fire the dripper at least once in case the user just clicked their mouse button
    if(call_cb && this.times_fired <= 0 && this.cb) {
        this.cb(param);
    }

    this.origin_time = -1;
    this.last_time = -1;
    this.times_fired = 0;
    this.resid = 0;
};

/** @param {number} t
    @param {?=} param to call the function with
    @suppress {reportUnknownTypes} - Closure doesn't deal with the callback param being typeless
*/
Dripper.Dripper.prototype.activate = function(t, param) {
    if(!this.is_active() || t < this.origin_time) { return 0; } // not begun yet

    if(this.times_fired <= 0) {
        // first press
        this.last_time = t;
        this.times_fired += 1;
        if(this.cb(param)) {
            this.stop();
        }
        return 1;
    }
    // not first press
    var delta = t - this.last_time;

    // figure out rate scale to use
    var r_scale = 1;
    for(var i = Dripper.rate_table.length-1; i >= 0; i -= 1) {
        if(t - this.origin_time >= Dripper.rate_table[i][0]) {
            r_scale = /** @type {number} */ (Dripper.rate_table[i][1]);
            break;
        }
    }
    var r = this.rate * r_scale;
    var count = r * delta + this.resid;
    while(count >= 1) {
        count -= 1;
        this.times_fired += 1;
        if(this.cb(param)) {
            this.stop();
            return count;
        }
    }
    this.resid = count; // record residual fraction
    this.last_time = t;
    return count;
};

/** @return {boolean} */
Dripper.Dripper.prototype.is_active = function() {
    return this.origin_time >= 0;
};
