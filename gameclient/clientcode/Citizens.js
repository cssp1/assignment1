goog.provide('Citizens');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// generates nicely-formatted SPText for upgrade congraulations M&Ms
// uses pretty_print_number from main.js

// Random army units walking around your base

// This is intended to couple only loosely with the GameObjects in
// main.js. It monitors changes to the army via the Context.update()
// method, which is fast and should be called every frame or tick (but
// if the army contents have not changed, pass null so that it doesn't
// waste time looking for changes).

goog.require('SPFX');
goog.require('AStar');
goog.require('GameData');
goog.require('Base');
goog.require('goog.array');
goog.require('goog.object');

/** State for one displayed citizen
    @constructor @struct
    @param {Citizens.Context} context
    @param {string} obj_id
    @param {GameData.UnitSpec} spec
    @param {number} level
    @param {number} time_offset */
Citizens.Citizen = function(context, obj_id, spec, level, time_offset) {
    this.context = context;
    this.obj_id = obj_id;
    this.spec = spec;
    this.level = level;
    this.time_offset = time_offset;
    this.next_update_time = client_time + time_offset;

    /** @type {SPFX.PhantomUnit} */
    this.fx = null; // generated in update()

    this.update();
};

Citizens.Citizen.prototype.dispose = function() {
    if(this.fx) {
        this.fx.end_time = client_time + gamedata['client']['unit_fade_time']; // fade out
    }
    this.next_update_time = -1; // stop updating the motion path
};

// XXX the "citizens_astar" option is work-in-progress. May consume excessive CPU and get units stuck inside things.

Citizens.Citizen.prototype.update = function() {
    if(this.next_update_time < 0 || client_time < this.next_update_time) { return; }
    this.next_update_time = client_time + (gamedata['client']['citizens_update_interval'] || 5.0);
    var path = this.get_new_path();
    if(!this.fx) {
        var instance_data = {'spec': this.spec.name, 'level': this.level};
        if(gamedata['client']['citizens_astar']) {
            instance_data['dest'] = path[path.length-1];
        } else {
            instance_data['path'] = path;
        }
        this.fx = new SPFX.PhantomUnit(path[0], this.spec.flying ? this.spec.altitude : 0, [1, 0, 1],
                                       new SPFX.When(this.context.fxworld.time, null),
                                       {'duration': -1, 'end_at_dest': false,
                                        'maxvel':0.5 // move more slowly than normal to look less "hurried"
                                       }, instance_data);

        this.context.fxworld.add_phantom(this.fx);
        if(gamedata['client']['citizens_astar']) {
            this.fx.set_dest(path[path.length-1]);
        }
    } else {
        if(gamedata['client']['citizens_astar']) {
            this.fx.set_dest(path[path.length-1]);
        } else {
            this.fx.set_path(path);
        }
    }
};

/** make up a new motion path
 * @return {!Array.<!Array.<number>>} */
Citizens.Citizen.prototype.get_new_path = function() {
    var start_pos, end_pos;
    if(this.fx) {
        start_pos = vec_floor(this.fx.obj.interpolate_pos());
    } else {
        start_pos = this.get_random_pos_from(null);
    }
    var is_lazy = Math.random() < (gamedata['client']['citizens_lazy_chance'] || 0.05);
    if(is_lazy) {
        end_pos = start_pos;
    } else {
        end_pos = this.get_random_pos_from(start_pos);
    }
    //console.log('Citizen PATH '+this.obj_id+' '+start_pos[0].toString()+','+start_pos[1].toString()+' '+end_pos[0].toString()+','+end_pos[1].toString());
    return [start_pos, end_pos];
};

/** Pick random position for motion. If src is null, pick anywhere,
 * otherwise pick somewhere reasonably reachable from src.
 * @param{?Array.<number>} src position to start from, arbitrary if null
 */
Citizens.Citizen.prototype.get_random_pos_from = function(src) {
    var ret = [0,0];
    var ncells = this.context.base.ncells();
    var mid = this.context.base.midcell();
    var rad = this.context.base.get_base_radius();
    var found = false;

    // optional constraints to keep src and new random point on the same side of the base perimeter
    var sides = [0,0]; // -1 if left of base, 1 if right of base, 0 if unconstrained on this axis

    if(gamedata['client']['citizens_astar']) {
        // if A* is enabled, no constraints on source/dest
        sides = [0,0];
    } else if(src) {
        // match constraints of "src"
        if(src[0] >= mid[0]-rad && src[0] < mid[0]+rad) {
            sides = [0, (src[1] < mid[1] ? -1 : 1)];
        } else {
            sides = [(src[0] < mid[0] ? -1 : 1), 0];
        }
    } else {
        // randomly constrain to one of the four sides
        var r = Math.random();
        if(r < 0.5) {
            sides = [0, (r < 0.25 ? -1 : 1)];
        } else {
            sides = [(r < 0.75 ? -1 : 1), 0];
        }
    }

    // generate random point according to sides constraints
    for(var iter = 0; iter < 50 && !found; iter++) {
        for(var axis = 0; axis < 2; axis++) {
            if(sides[axis] === 0) {
                ret[axis] = mid[axis] - rad + Math.floor((2*rad) * Math.random());
            } else if(sides[axis] < 0) {
                ret[axis] = Math.floor((mid[axis]-rad)*Math.random());
            } else {
                ret[axis] = Math.floor(mid[axis] + rad + ((ncells[axis] - (mid[axis]+rad))*Math.random()));
            }
        }
        if(gamedata['client']['citizens_astar']) {
            // reject blocked locations
            if(this.context.astar_context.map.is_blocked(ret)) {
                continue;
            } else if(src && this.context.astar_context.connectivity &&
                      (this.context.astar_context.connectivity.region_num(vec_floor(src)) !=
                       this.context.astar_context.connectivity.region_num(vec_floor(ret)))) {
                continue; // not connected
            } else {
                found = true;
            }
        } else {
            found = true;
        }
    }
    return ret;
};

//
// CITIZEN CONTEXT
//

/** @constructor @struct
    @param {Base.Base} base is the session.viewing_base
    @param {AStar.CachedAStarContext} astar_context is the map for pathfinding
    @param {!SPFX.FXWorld} fxworld in which to put the phantom units */
Citizens.Context = function(base, astar_context, fxworld) {
    this.base = base;
    this.astar_context = astar_context;
    this.fxworld = fxworld;

    /** @type {Object.<string, Citizens.Citizen>} */
    this.by_id = {}; // to keep track of our citizens
};

/** Just a data structure for passing input to Context.update()
    @constructor @struct
    @param {string} obj_id
    @param {string} specname
    @param {number} level
    @param {number} hp_ratio */
Citizens.UnitData = function(obj_id, specname, level, hp_ratio) {
    this.obj_id = obj_id; this.specname = specname; this.level = level; this.hp_ratio = hp_ratio;
};

/** Main update function. Call frequently (every tick or frame). If army contents
 * have changed since last call, pass a UnitData array for the army. Otherwise pass null.
 * @param {?Array.<Citizens.UnitData>} army contents - if null, just update existing display in place
 */
Citizens.Context.prototype.update = function(army) {
    if(army === null) {
        goog.object.forEach(this.by_id, function(cit) { cit.update(); });
        return;
    }

    // deal with additions and deletions
    var spawn_time_offset = 0;
    var seen = {};
    goog.array.forEach(army, function(data) {
        var spec = new GameData.UnitSpec(gamedata['units'][data.specname]);
        if(GameData.get_leveled_number(spec.max_hp, data.level) <= 0 || data.hp_ratio > 0) {
            // unit is alive
            seen[data.obj_id] = true;
            if(data.obj_id in this.by_id) {
                // already exists
                this.by_id[data.obj_id].update();
                return;
            }
            var cit = new Citizens.Citizen(this, data.obj_id, spec, data.level, spawn_time_offset);
            this.by_id[data.obj_id] = cit;
            spawn_time_offset += (gamedata['client']['citizen_spawn_time_offset'] || 0.05);
        } else {
            // unit is dead
            if(data.obj_id in this.by_id) {
                var cit = this.by_id[data.obj_id];
                delete this.by_id[data.obj_id];
                cit.dispose();
            }
        }
    }, this);
    goog.object.forEach(this.by_id, function(cit) {
        if(!(cit.obj_id in seen)) {
            // unit is dead
            delete this.by_id[cit.obj_id];
            cit.dispose();
        }
    }, this);
};

Citizens.Context.prototype.dispose = function() {
    goog.object.forEach(this.by_id, function(cit) { cit.dispose(); });
};
