goog.provide('WallManager');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('GameTypes');

/** The "Wall Manager" adjusts the neighbor values of Buildings representing linkable walls
    to create or close collision gaps as necessary. Updated lazily at the beginning of the
    next combat tick after any change to neighbor state.
    @constructor
    @param {!Array.<number>} size - map size, in grid cells
    @param {!Object} spec - for the barrier object
*/
WallManager.WallManager = function(size, spec) {
    this.spec = spec; // of the barrier object
    this.gs = spec['unit_collision_gridsize'];
    this.size = size; // xy dimensions in map cell units
    for(var axis = 0; axis < 2; axis++) {
        if(this.size[axis] % this.gs[axis] !== 0) {
            throw Error('size is not a multiple of '+this.spec['name']+' unit_collision_gridsize');
        }
    }
    this.chunk = [this.size[0]/this.gs[0], this.size[1]/this.gs[1]]; // xy dimensions of the bitmap (coarseness is the collision gridsize)
    this.bitmap = new Array(this.chunk[0]*this.chunk[1]);
    this.dirty = true;
};

/** Update neighbor states
    @param {!GameObjectCollection.GameObjectCollection} obj_dict - the current objects in the session */
WallManager.WallManager.prototype.refresh = function(obj_dict) {
    if(!this.dirty) { return; }
    this.dirty = false;

    // clear bitmap
    for(var i = 0; i < this.chunk[0]*this.chunk[1]; i++) {
        this.bitmap[i] = 0;
    }

    // pass 1: find barriers and build bitmap
    var obj_list = [];
    obj_dict.for_each(function(obj) {
        if(obj.spec !== this.spec || obj.is_destroyed()) { return; }
        obj_list.push(obj);

        // add to bitmap
        var y = Math.floor(obj.y / this.gs[1]);
        var x = Math.floor(obj.x / this.gs[0]);
        this.bitmap[this.chunk[0]*y + x] = 1;
    }, this);

    // pass 2: set up new neighbor states
    var DIRECTIONS = [[0,-1],[1,0],[0,1],[-1,0]]; // NESW offsets
    goog.array.forEach(obj_list, function(obj) {
        var neighbors = [-1,-1,-1,-1]; // shrink inward by 1 unit, unless a neighbor is found
        for(var i = 0; i < DIRECTIONS.length; i++) {
            var xy = vec_add([Math.floor(obj.x/this.gs[0]), Math.floor(obj.y/this.gs[1])], DIRECTIONS[i]);
            if(xy[0] >= 0 && xy[0] < this.chunk[0] && xy[1] >= 0 && xy[1] < this.chunk[1]) {
                if(this.bitmap[this.chunk[0]*xy[1] + xy[0]]) {
                    neighbors[i] = 0;
                }
            }
        }
        obj.set_neighbors(neighbors);
    }, this);
};

