goog.provide('TeamMapAccelerator');

// Copyright (c) 2014 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// Very simple acceleration data structure for map queries that just groups objects by team.

/** @constructor
 */
TeamMapAccelerator.TeamMapAccelerator = function() {
    this.teams = {'ALL':[]}; // list of objects by team, with 'ALL' as well
};

/** reset to blank state */
TeamMapAccelerator.TeamMapAccelerator.prototype.clear = function() {
    this.teams = {'ALL':[]}; // list of objects by team, with 'ALL' as well
};

/** add object to the accelerator
 * @param {GameObject} obj to add
 */
TeamMapAccelerator.TeamMapAccelerator.prototype.add_object = function(obj) {
    this.teams['ALL'].push(obj);
    if(!(obj.team in this.teams)) {
        this.teams[obj.team] = [];
    }
    this.teams[obj.team].push(obj);
};

/** return list of objects belonging to a team, or null if none found
 * @param {string=} team
 */
TeamMapAccelerator.TeamMapAccelerator.prototype.objects_on_team = function(team) {
    if(!team) { team = 'ALL'; }
    if(!(team in this.teams)) { return null; }
    return this.teams[team];
};

/** quick test if the accelerator has any objects belonging to this team
 * @param {string} team */
TeamMapAccelerator.TeamMapAccelerator.prototype.has_any_of_team = function(team) {
    return !!(this.teams[team]);
};
