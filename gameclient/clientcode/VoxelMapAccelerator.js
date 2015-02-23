goog.provide('VoxelMapAccelerator');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// Sparse 2D voxel grid data structure for accelerating the common case of map queries for unit combat AI.
// i.e. querying for other units within a circle of a certain radius.
// This gets rebuilt each combat sim step in run_unit_ticks().

// note: in the following code, "xy" refers to input map grid coordinates, "st" refers to voxel bucket coordinates

VoxelMapAccelerator.clamp = function(x,a,b) {
    if(x < a)
        return a;
    if(x > b)
        return b;
    return x;
};

/** @constructor
    @struct
    @param {Array.<number>} wh Input map grid size
    @param {number} chunk Size of each voxel bucket, in gridcell units */
VoxelMapAccelerator.VoxelMapAccelerator = function(wh, chunk) {
    this.wh = wh; // input map grid dimensions
    this.chunk = chunk; // coarseness
    // voxel bucket dimensions
    this.size = [Math.floor((wh[0] + this.chunk - 1)/this.chunk),
                 Math.floor((wh[1] + this.chunk - 1)/this.chunk)];

    // there are actually multiple voxel grids, indexed by obj.team
    // plus an 'ALL' grid for all objects
    this.spaces = {}; // dictionary of filter name -> array along Y axis -> array along X axis -> list of units
};

/** reset to blank state */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.clear = function() {
    this.spaces = {};
};

/** @param {Array.<number>} xy coordinate to convert to st grid coordinates */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.xy_to_st = function(xy) {
    if(xy[0] < 0 || xy[0] >= this.wh[0] || xy[1] < 0 || xy[1] >= this.wh[1]) { throw Error('out-of-bounds coordinates '+JSON.stringify(xy)); }
    return [Math.floor(xy[0]/this.chunk),
            Math.floor(xy[1]/this.chunk)];
};

/** for debugging only - print stats to console */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.dump = function() {
    console.log('VoxelMapAccelerator wh '+this.wh[0].toString()+'x'+this.wh[1].toString() + ' chunk '+this.chunk.toString()+' size '+this.size[0].toString()+'x'+this.size[1].toString());
    for(var space in this.spaces) {
        var grid = this.spaces[space];
        var lines = 0, cells = 0, total_objs = 0;
        for(var t = 0; t < this.size[1]; t++) {
            if(grid[t]) {
                lines += 1;
                for(var s = 0; s < this.size[0]; s++) {
                    if(grid[t][s]) {
                        cells += 1;
                        total_objs += grid[t][s].length;
                    }
                }
            }
        }
        console.log('space '+space+': '+lines+' lines, '+cells+' cells, '+(total_objs/cells).toFixed(2)+' objs per cell');
    }
};

/** add object to one voxel bucket
 * @param {Array.<(Array.<(Array.<GameObject>)|null>)|null>} grid
 * @param {GameObject} obj to add
 * @param {Array.<number>} st coordinates
 */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.add_to_grid_space_st = function(grid, obj, st) {
    var s = st[0], t = st[1];
    if(grid[t] === null) {
        grid[t] = Array(this.size[0]);
        for(var j = 0; j < this.size[0]; j++) {
            grid[t][j] = null;
        }
    }
    if(grid[t][s] === null) {
        grid[t][s] = [];
    }
    grid[t][s].push(obj);
};

/** add object to all voxel buckets within its hit radius
 * @param {string} grid_name
 * @param {GameObject} obj to add
 * @param {Array.<number>} xy coordinates
 * @param {number} rad radius of the object, 0 if it's just a point
 */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.add_to_grid_xy = function(grid_name, obj, xy, rad) {
    if(!(grid_name in this.spaces)) {
        this.spaces[grid_name] = Array(this.size[1]);
        for(var t = 0; t < this.size[1]; t++) {
            this.spaces[grid_name][t] = null;
        }
    }
    var grid = this.spaces[grid_name];

    if(rad > 0) {
        // object with a radius - need to put it into all covered cells
        var bounds = this.get_circle_bounds_xy_st(xy, rad);
        for(var t = bounds[1][0]; t < bounds[1][1]; t++) {
            for(var s = bounds[0][0]; s < bounds[0][1]; s++) {
                this.add_to_grid_space_st(grid, obj, [s,t]);
            }
        }
    } else {
        // point object
        var x = VoxelMapAccelerator.clamp(Math.floor(xy[0]), 0, this.wh[0]-1);
        var y = VoxelMapAccelerator.clamp(Math.floor(xy[1]), 0, this.wh[1]-1);
        this.add_to_grid_space_st(grid, obj, this.xy_to_st(xy));
    }
};

/** add object to the accelerator
 * @param {GameObject} obj to add
 */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.add_object = function(obj) {
    var xy = obj.raw_pos();
    var rad = obj.hit_radius();
    this.add_to_grid_xy('ALL', obj, xy, rad);
    if(obj.team) {
        this.add_to_grid_xy(obj.team, obj, xy, rad);
    }
};

/** return the bounding s,t coordinates of all voxels inside a circle centered at "loc" with radius "dist"
 * @param {Array.<number>} loc xy coordinates
 * @param {number} dist
 */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.get_circle_bounds_xy_st = function(loc, dist) {
    var ret = [[0,0],[0,0]];
    for(var axis = 0; axis < 2; axis++) {
        // note: upper bound is the next cell BEYOND the end of the iteration, so clamp to end, not end-1
        var lo = VoxelMapAccelerator.clamp(Math.floor(loc[axis]-dist), 0, this.wh[axis]);
        var hi = VoxelMapAccelerator.clamp(Math.ceil(loc[axis]+dist), 0, this.wh[axis]);
        ret[axis][0] = VoxelMapAccelerator.clamp(Math.floor(lo/this.chunk), 0, this.size[axis]);
        ret[axis][1] = VoxelMapAccelerator.clamp(Math.floor((hi + this.chunk - 1)/this.chunk), 0, this.size[axis]);
    }
    return ret;
};

/** Return list of objects in the voxel bucket that contains xy
    Note that this is conservative: it may return objects that are near, but don't actually cover xy!
 * @param {Array.<number>} xy coordinates
 * @param {string} team filter
 */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.objects_near_xy = function(xy, team) {
    // silently ignore out-of-bounds queries
    var x = xy[0], y = xy[1];
    if(x < 0 || x >= this.wh[0] || y < 0 || y >= this.wh[1]) { return null; }
    return this.objects_at_st(this.xy_to_st(xy), team);
};

/** return list of objects in one voxel bucket
 * @param {Array.<number>} st coordinates
 * @param {string} team filter
 */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.objects_at_st = function(st, team) {
    if(!team) { team = 'ALL'; }
    if(!(team in this.spaces)) { return null; }
    var s = st[0], t = st[1];
    if(this.spaces[team][t] === null) { return null; }
    return this.spaces[team][t][s];
};

/** quick test if the accelerator has any objects belonging to this team
 * @param {string} team */
VoxelMapAccelerator.VoxelMapAccelerator.prototype.has_any_of_team = function(team) {
    return !!(this.spaces[team]);
};
