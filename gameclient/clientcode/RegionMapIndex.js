goog.provide('RegionMapIndex');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Data structure for speeding up queries for region map features
    by indexing by base ID as well as x,y coordinates.
*/

goog.require('MapFeature');
goog.require('goog.array');

/** @constructor @struct
    @param {!Array.<number>} dims */
RegionMapIndex.RegionMapIndex = function(dims) {
    this.dims = dims;
    /** @type {!Object<string,!MapFeature.MapFeature>} */
    this.base_id_index = {};
    /** @type {Array<Array<Array<!MapFeature.MapFeature>>>|null} */
    this.lines = null;
    this.clear();
}
RegionMapIndex.RegionMapIndex.prototype.clear = function() {
    // index by base_id
    this.base_id_index = {};

    // 2D location index
    this.lines = Array(this.dims[1]);
    for(var y = 0; y < this.dims[1]; y++) {
        this.lines[y] = null;
    }
}
/** @param {string} base_id
    @param {!Array<number>} xy
    @param {!MapFeature.MapFeature} obj */
RegionMapIndex.RegionMapIndex.prototype.insert = function(base_id, xy, obj) {
    this.base_id_index[base_id] = obj;
    if(xy !== null) {
        if(this.lines[xy[1]] === null) {
            this.lines[xy[1]] = Array(this.dims[0]);
            for(var x = 0; x < this.dims[0]; x++) {
                this.lines[xy[1]][x] = null;
            }
        }
        if(this.lines[xy[1]][xy[0]] === null) {
            this.lines[xy[1]][xy[0]] = [];
        }
        this.lines[xy[1]][xy[0]].push(obj);
    }
}

/** @param {string} base_id
    @param {!Array<number>} xy
    @param {!MapFeature.MapFeature} obj */
RegionMapIndex.RegionMapIndex.prototype.remove = function(base_id, xy, obj) {
    if(base_id in this.base_id_index) { delete this.base_id_index[base_id]; }
    if(xy !== null) {
        if(this.lines[xy[1]] !== null) {
            if(this.lines[xy[1]][xy[0]] !== null) {
                goog.array.remove(this.lines[xy[1]][xy[0]], obj);
            }
        }
    }
}

/** @param {string} id
    @return {MapFeature.MapFeature|null} note: returns a SINGLE feature */
RegionMapIndex.RegionMapIndex.prototype.get_by_base_id = function(id) {
    return this.base_id_index[id] || null;
}

/** @param {!Array<number>} xy
    @return {Array<!MapFeature.MapFeature>} note: returns LIST OF MULTIPLE features */
RegionMapIndex.RegionMapIndex.prototype.get_by_loc = function(xy) {
    if(this.lines[xy[1]] !== null) {
        if(this.lines[xy[1]][xy[0]] !== null) {
            return this.lines[xy[1]][xy[0]];
        }
    }
    return [];
}
