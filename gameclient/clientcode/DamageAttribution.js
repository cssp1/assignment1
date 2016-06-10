goog.provide('DamageAttribution');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    During battle, keep track of damage done and received by each unit/item spec/level.
*/

/** @constructor @struct */
DamageAttribution.DamageAttribution = function() {
    /** @type {!Object<string,!Object<string,number>>} */
    this.damage_done = {};
    /** @type {!Object<string,!Object<string,number>>} */
    this.damage_taken = {};
    this.is_empty = true;
};

/** @param {string} key
    @param {Object<string,number>|null} done
    @param {Object<string,number>|null} taken */
DamageAttribution.DamageAttribution.prototype.add = function(key, done, taken) {
    if(done) {
        this._add(key, this.damage_done, done);
    }
    if(taken) {
        this._add(key, this.damage_taken, taken);
    }
};

/** @private
    @param {string} key
    @param {!Object<string,!Object<string,number>>} accum
    @param {!Object<string,number>} dmg */
DamageAttribution.DamageAttribution.prototype._add = function(key, accum, dmg) {
    for(var k in dmg) {
        if(dmg[k]) {
            if(!(key in accum)) {
                accum[key] = /** @type {!Object<string,number>} */ ({});
            }
            accum[key][k] = (accum[key][k] || 0) + dmg[k];
            this.is_empty = false;
        }
    }
};

/** @return {boolean} */
DamageAttribution.DamageAttribution.prototype.empty = function() { return this.is_empty; };

/** @private
    @param {!Object<string,?>} d
    @return {!Object<string,?>} */
DamageAttribution.DamageAttribution.prototype.serialize_dict = function(d) {
    var ret = {};
    for(var parent in d) {
        ret[parent] = {}
        for(var child in d[parent]) {
            ret[parent][child] = serialize_number(d[parent][child], 2);
        }
    }
    return ret;
};

/** @return {!Object<string,?>} */
DamageAttribution.DamageAttribution.prototype.serialize = function() {
    return {
        'damage_done': this.serialize_dict(this.damage_done),
        'damage_taken': this.serialize_dict(this.damage_taken)
    };
};
