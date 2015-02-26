goog.provide('GameTypes');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// The following is a temporary band-aid to help with the refactoring of main.js.
// It "forward declares" some things for cases where typesafe libraries
// are still relying on definitions from main.js (which is read in after
// them, so they don't know about types defined there).

/** @constructor
    @struct
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
