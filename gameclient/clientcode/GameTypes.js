goog.provide('GameTypes');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @param {number} num */
GameTypes.assert_integer = function(num) { if(num != (num|0)) { throw Error('non-integer '+num.toString()); } };

/** @typedef {number} */
GameTypes.Integer;

/** @constructor @struct
    @param {number} count */
GameTypes.TickCount = function(count) {
    GameTypes.assert_integer(count);
    /** @const {number} */
    this.count = count;
};

/** @const */
GameTypes.TickCount.infinity = new GameTypes.TickCount(-1);

/** @return {number} */
GameTypes.TickCount.prototype.get = function() { return this.count; };
/** @return {boolean} */
GameTypes.TickCount.prototype.is_infinite = function() { return this.count < 0; };
/** @return {boolean} */
GameTypes.TickCount.prototype.is_nonzero = function() { return this.count != 0; };

/** @return {!GameTypes.TickCount} */
GameTypes.TickCount.prototype.copy = function() { return new GameTypes.TickCount(this.count); }; // XXXXXX remove this

/** @param {!CombatEngine.Coeff} s
    @param {!GameTypes.TickCount} a
    @return {!GameTypes.TickCount} */
GameTypes.TickCount.scale = function(s, a) { return new GameTypes.TickCount(Math.floor(s*a.count+0.5)); };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {boolean} */
GameTypes.TickCount.equal = function(a, b) { return a.count === b.count; };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {boolean} */
GameTypes.TickCount.gte = function(a, b) { return a.count >= b.count; };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {boolean} */
GameTypes.TickCount.gt = function(a, b) { return a.count > b.count; };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {boolean} */
GameTypes.TickCount.lt = function(a, b) { return a.count < b.count; };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {boolean} */
GameTypes.TickCount.lte = function(a, b) { return a.count <= b.count; };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {!GameTypes.TickCount} */
GameTypes.TickCount.add = function(a, b) { return new GameTypes.TickCount(a.count+b.count); };

/** @param {!GameTypes.TickCount} a
    @param {!GameTypes.TickCount} b
    @return {!GameTypes.TickCount} */
GameTypes.TickCount.max = function(a, b) { return new GameTypes.TickCount(Math.max(a.count, b.count)); };


// The following is a temporary band-aid to help with the refactoring of main.js.
// It "forward declares" some things for cases where typesafe libraries
// are still relying on definitions from main.js (which is read in after
// them, so they don't know about types defined there).

/** @constructor @struct
    @param {!GameObject} obj
    @param {!CombatEngine.Pos} dist
    @param {!Array.<number>} pos
    @param {number=} override_priority
    @param {(!Array.<number>|undefined)=} override_path_end
    @param {GameObject|null=} debug_orig_target
    note: the last three fields are only for the convenience of the target-picking code, which uses them to track info about blockers.
*/
GameTypes.GameObjectQueryResult = function(obj, dist, pos, override_priority, override_path_end, debug_orig_target) {
    this.obj = obj; this.dist = dist; this.pos = pos;
    this.override_priority = override_priority;
    this.override_path_end = override_path_end;
    this.debug_orig_target = debug_orig_target;
};
