goog.provide('GameData');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// experimental - wrap parts of gamedata in type-safe wrappers

/** @typedef {Object.<string,*>} */
GameData.RawSpec;

// templates don't really work with reportUnknownTypes, so we can't use them here.

/** @param {*} qty
    @param {number} level
    @return {*} */
GameData.get_leveled_quantity = function(qty, level) {
    if((typeof qty) == 'undefined') {
        throw Error('get_leveled_quantity of undefined');
    }
    if(qty === null ||
       (typeof qty) === 'number' ||
       (typeof qty) === 'string' ||
       (typeof qty) === 'boolean') {
        return qty;
    } else if(0 in qty) {
        // hope it's an array
        return qty[level-1];
    } else {
        // anything else
        return qty;
    }
};

/** @param {number|Array.<number>} qty
    @param {number} level
    @return {number} */
GameData.get_leveled_number = function(qty, level) {
    var x = GameData.get_leveled_quantity(qty, level);
    if(typeof x !== 'number') { throw Error('expected number but got '+qty); }
    return x;
};

/** @constructor @struct
    @param {GameData.RawSpec} spec */
GameData.UnitSpec = function(spec) {
    /** @private */
    this.spec = spec;
};

/** @struct */
GameData.UnitSpec.prototype = {
    /** @this {GameData.UnitSpec} @return {string} */
    get name() { return /** @type {string} */ (this.spec['name']); },

    /** @this {GameData.UnitSpec} @return {boolean} */
    get flying() { return /** @type {boolean} */ (this.spec['flying'] || false); },

    /** @this {GameData.UnitSpec} @return {number} */
    get altitude() { return /** @type {number} */ (this.spec['altitude'] || 0); },

    /** @this {GameData.UnitSpec} @return {number|Array.<number>} */
    get max_hp() { return /** @type {number|Array.<number>} */ (this.spec['max_hp'] || 0); }
};

/** @constructor @struct
    @param {GameData.RawSpec} spec */
GameData.WeaponSpell = function(spec) {
    /** @private */
    this.spec = spec;
};

/** @struct */
GameData.WeaponSpell.prototype = {
    /** @this {GameData.WeaponSpell} @return {string|null} */
    get applies_aura() { return /** @type {string|null} */ (this.spec['applies_aura'] || null); },

    /** @this {GameData.WeaponSpell} @return {number|Array.<number>} */
    get damage() { return /** @type {number|Array.<number>} */ (this.spec['damage'] || 0); }
};

/** @param {string} spellname */
GameData.TestFunc = function(spellname) {
    var ws = new GameData.WeaponSpell(/** @type {GameData.RawSpec} */ (gamedata['spells'][spellname]));
    console.log(ws.damage);
    console.log(ws.applies_aura);
};
goog.exportSymbol('GameData.TestFunc', GameData.TestFunc);

