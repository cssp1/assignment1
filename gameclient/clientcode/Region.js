goog.provide('Region');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    References a lot of stuff from main.js :(
*/

/** @constructor @struct */
Region.Region = function(data) {
    this.data = data;
    this.dirty = true;
    this.refresh_time = -1;
    this.features = [];

    var terrain_func = (function (_this) { return function(xy) { return _this.obstructs_squads(xy); }; })(this);

    /** @type {?AStar.AStarHexMap} used for pathfinding and collision detection */
    this.occupancy = (data ? new AStar.AStarHexMap(data['dimensions'], terrain_func) : null);
    /** @type {?AStar.AStarContext} used for pathfinding and collision detection */
    this.hstar_context = (data ? new AStar.AStarContext(this.occupancy, {heuristic_name:'manhattan'}) : null);

    /** @type {?RegionMapIndex.RegionMapIndex} used for feature queries */
    this.map_index = (data ? new RegionMapIndex.RegionMapIndex(data['dimensions']) : null);

    this.fresh_cbs = [];
    /** @type {?AJAXMessageQueue} for last server query */
    this.refresh_msg = null;
    this.terrain = (data ? gamedata['region_terrain'][data['terrain']] : null);
    this.contest_rank = null;
}

Region.Region.prototype.map_enabled = function() {
    return this.data && (!('enable_map' in this.data) || this.data['enable_map']);
};

Region.Region.prototype.pvp_level_gap_enabled = function() {
    if(this.data && ('enable_pvp_level_gap' in this.data) && !this.data['enable_pvp_level_gap']) { return false; }
    return true;
};

Region.Region.prototype.turf_points_to_win = function() {
    var total_turf_points = 0;
    this.for_each_feature(function(feature) {
        if(feature['base_type'] == 'quarry') {
            var template = gamedata['quarries_client']['templates'][feature['base_template']];
            if(template && template['turf_points']) {
                total_turf_points += template['turf_points'];
            }
        }
    }, this);
    if(total_turf_points < 1) { // no strongpoints
        return -1;
    }
    return Math.floor(total_turf_points/2.0)+1;
};

Region.Region.prototype.display_turf_standings = function(ui_data) {
    var total_turf_points = 0;
    var points_by_alliance = {};
    var has_all_alliances = true;
    this.for_each_feature(function(feature) {
        if(feature['base_type'] == 'quarry') {
            var template = gamedata['quarries_client']['templates'][feature['base_template']];
            if(template && template['turf_points']) {
                total_turf_points += template['turf_points'];
                if(feature['base_landlord_id'] > 0 && !is_ai_user_id_range(feature['base_landlord_id'])) {
                    var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
                    if(info) {
                        if (('alliance_id' in info) && info['alliance_id'] >= 0) {
                            points_by_alliance[info['alliance_id']] = (points_by_alliance[info['alliance_id']]||0) + template['turf_points'];
                        }
                    } else {
                        has_all_alliances = false; // still querying players
                    }
                }
            }
        }
    }, this);
    if(total_turf_points < 1) { return null; }
    if(!has_all_alliances) {
        return ui_data['ui_name_loading'];
    }

    // Google Closure is too smart for its own good, and assumes the return value from getKeys() is always an array of strings
    var alliance_id_list = /** @type {Array.<number>} */ (goog.object.getKeys(points_by_alliance));

    alliance_id_list.sort(function(a,b) {
        var a_rank = points_by_alliance[a], b_rank = points_by_alliance[b];
        if(a_rank > b_rank) {
            return -1;
        } else if(a_rank < b_rank) {
            return 1;
        } else {
            return 0;
        }
    });

    var my_alliance_seen = false;
    var display_list = [];
    var cur_rank = -1, last_points = -1;
    for(var i = 0; i < Math.min(3, alliance_id_list.length); i++) {
        var alliance_id = alliance_id_list[i];
        var points = points_by_alliance[alliance_id];
        var tied = false;
        if(points != last_points) {
            cur_rank += 1;
        } else {
            tied = true;
        }
        if(i < (Math.min(3, alliance_id_list.length) - 1) && points_by_alliance[alliance_id_list[i+1]] == points) {
            tied = true;
        }
        if(alliance_id == session.alliance_id) { my_alliance_seen = true; }
        var alliance_info = AllianceCache.query_info(alliance_id, null);
        if(!alliance_info) { return ui_data['ui_name_loading']; }
        display_list.push(ui_data['ui_name'].replace('%rank', (cur_rank+1).toString()).replace('%tied', (tied ? ui_data['ui_name_tie'] : '')).replace('%alliance', alliance_display_name(alliance_info)).replace('%cur', points.toString()).replace('%max', total_turf_points.toString()));
        last_points = points;
    }

    if(!my_alliance_seen && session.is_in_alliance()) {
        var my_points = points_by_alliance[session.alliance_id] || 0;
        var alliance_info = AllianceCache.query_info_sync(session.alliance_id);
        if(alliance_info) {
            display_list.push(ui_data['ui_name_separator']);
            display_list.push(ui_data['ui_name'].replace('%rank','-').replace('%tied','').replace('%alliance', alliance_display_name(alliance_info)).replace('%cur',my_points.toString()).replace('%max', total_turf_points.toString()));
        }
    }
    return display_list.join('\n');
};

Region.Region.prototype.ping_contest_rank = function() {
    if(!this.data) { return; }
    if(!player.get_event_time('current_event', 'event_quarry_contest', 'inprogress')) { return; }

    query_player_scores([session.user_id], [['quarry_resources','week']],
                        (function (_region) { return function(ids, results) {
                            var result = results[0];
                            if(result) {
                                _region.contest_rank = result[0];
                            }
                        }; })(this), {get_rank:1});
};

Region.Region.prototype.read_terrain = function(xy) {
    var index = xy[1]*this.data['dimensions'][0] + xy[0];
    var enc = this.terrain.charCodeAt(index);
    var raw = enc - 65;
    return raw;
};
Region.Region.prototype.read_climate = function(xy) {
    return gamedata['climates'][gamedata['territory']['tiles'][this.read_terrain(xy)]['climate']];
};
Region.Region.prototype.obstructs_squads = function(xy) {
    return !!this.read_climate(xy)['obstructs_squads'];
};

Region.Region.prototype.in_bounds = function(xy) {
    var dimensions = this.data['dimensions'];
    return (xy[0] >= 0 && xy[0] < dimensions[0] &&
            xy[1] >= 0 && xy[1] < dimensions[1]);
};
Region.Region.prototype.get_neighbors = function(xy) {
    var odd = (xy[1]%2) > 0;
    var ret = [];
    goog.array.forEach([[xy[0]-1,xy[1]], // left
                        [xy[0]+1,xy[1]], // right
                        [xy[0]+odd-1,xy[1]-1], // upper-left
                        [xy[0]+odd,xy[1]-1], // upper-right
                        [xy[0]+odd-1,xy[1]+1], // lower-left
                        [xy[0]+odd,xy[1]+1]],
                       function(loc) {
                           if(this.in_bounds(loc)) {
                               ret.push(loc);
                           }
                       }, this);
    return ret;
};

/** @param {function(Object)} cb
    @param {?=} cb_this */
Region.Region.prototype.for_each_feature = function(cb, cb_this) {
    if(!this.features) { return; }
    goog.array.forEach(this.features, cb, cb_this);
};

Region.Region.prototype.feature_shown = function(feature) {
    if(!('base_map_loc' in feature)) { return false; }
    if(feature['base_type'] == 'hive' && ('base_template' in feature) && (feature['base_template'] in gamedata['hives_client']['templates']) &&
       ('show_if' in gamedata['hives_client']['templates'][feature['base_template']]) &&
       !read_predicate(gamedata['hives_client']['templates'][feature['base_template']]['show_if']).is_satisfied(player,null)) {
        return false;
    }
    return true;
};

/** @return {boolean} */
Region.Region.prototype.feature_blocks_map = function(feature) {
    return (feature['base_type'] !== 'squad' || (!feature['raid'] && player.squad_block_mode() !== 'never'));
};

/** note: just checking for presence of base_map_path is not correct, because sometimes squads
    get to where they're going, and the base_map_path on the server side disappears, but that
    deletion does not make it out to the client, so we may see a stale value.
    @param {!Object} feature
    @param {number=} t */
Region.Region.prototype.feature_is_moving = function(feature, t) {
    if(!t) { t = server_time; }
    return (('base_map_path' in feature) && feature['base_map_path'] &&
            (feature['base_map_path'][0]['eta'] < t) &&
            (feature['base_map_path'][feature['base_map_path'].length-1]['eta'] > t));
};

/** returns [last_pos, next_pos, alpha] where "alpha" is the fraction of the way from last_pos to next_pos you've traveled
    @param {!Object} feature
    @param {number=} t */
Region.Region.prototype.feature_interpolate_pos = function(feature, t) {
    if(!t) { t = server_time; }
    if(this.feature_is_moving(feature, t)) {
        var path = feature['base_map_path'];
        var last_waypoint = path[0];
        for(var i = 1; i < path.length; i++) {
            var waypoint = path[i];
            if(waypoint['eta'] > t) {
                var delta = vec_sub(waypoint['xy'], last_waypoint['xy']);
                return [last_waypoint['xy'], waypoint['xy'], (t-last_waypoint['eta'])/(waypoint['eta']-last_waypoint['eta'])];
            }
            last_waypoint = waypoint;
        }
    } else {
        if(('base_map_path' in feature) && feature['base_map_path'] &&
           (feature['base_map_path'][0]['eta'] >= t)) {
            // hasn't started moving yet
            return [feature['base_map_path'][0]['xy'], feature['base_map_path'][0]['xy'], 0];
        }
        return [feature['base_map_loc'], feature['base_map_loc'], 0];
    }
};

Region.Region.prototype.find_own_features_by_type = function(want_type) {
    var ret = [];
    goog.array.forEach(this.features, function(feature) {
        if(feature['base_landlord_id'] == session.user_id && feature['base_type'] == want_type) {
            ret.push(feature);
        }
    }, this);
    return ret;
};

Region.Region.prototype.find_feature_by_id = function(base_id) {
    return this.map_index.get_by_base_id(base_id);
};
Region.Region.prototype.find_home_feature = function() { return this.find_feature_by_id(player.home_base_id); };
Region.Region.prototype.num_quarries_owned = function() {
    return this.find_own_features_by_type('quarry').length;
};

// heuristic only - looks for a feature with same ID and name
Region.Region.prototype.feature_exists = function(base_id, base_ui_name) {
    var feature = this.find_feature_by_id(base_id);
    if(feature && feature['base_ui_name'] == base_ui_name) { return feature; }
    return null;
};
Region.Region.prototype.feature_exists_at = function(base_id, base_ui_name, loc) {
    var feature = this.feature_exists(base_id, base_ui_name);
    if(feature && 'base_map_loc' in feature && feature['base_map_loc'][0] == loc[0] && feature['base_map_loc'][1] == loc[1]) { return feature; }
    return null;
}

/** @param {Array.<number>} cell
  * @param {{include_moving_squads:(boolean|undefined)}} options */
Region.Region.prototype.find_features_at_coords = function(cell, options) {
    var feature_list = [];
    if(cell) {
        /*
        for(var i = 0; i < this.features.length; i++) {
            var f = this.features[i];
            if(!this.feature_shown(f)) { continue; }
            if(!f['base_map_loc']) { continue; }
            if(f['base_map_loc'][0] == cell[0] && f['base_map_loc'][1] == cell[1]) {
                feature_list.push(f);
            }
        }
        */
        feature_list = goog.array.filter(this.map_index.get_by_loc(cell), this.feature_shown, this);
    }

    // special case for player's own moving squads
    if(options && options.include_moving_squads) {
        goog.object.forEach(player.squads, function(squad_data) {
            if(player.squad_is_moving(squad_data['id'])) {
                var feature = this.find_feature_by_id(player.squad_base_id(squad_data['id']));
                if(feature) {
                    var last_next_progress = this.feature_interpolate_pos(feature);
                    // check "last" and "next"
                    for(var i = 0; i < 2; i++) {
                        if(last_next_progress[i][0] == cell[0] && last_next_progress[i][1] == cell[1]) {
                            feature_list.push(feature);
                            break;
                        }
                    }
                }
            }
        }, this);
    }

    return feature_list;
};

// find the "primary" feature at this cell
/** @param {Array.<number>} cell
  * @param {{include_moving_squads:(boolean|undefined)}} options */

Region.Region.prototype.find_feature_at_coords = function(cell, options) {
    var ls = this.find_features_at_coords(cell, options);
    if(ls.length < 1) {
        return null;
    } else if(ls.length == 1) {
        return ls[0];
    } else {
        // prefer anything (quarries) over squads
        var ret = ls[0];
        for(var i = 1; i < ls.length; i++) {
            if(ls[i]['base_type'] != 'squad') {
                ret = ls[i];
            }
        }
        return ret;
    }
};

/** Return list of squads neighboring "cell" that can attack into it
    @param {!Array.<number>} cell
    @return {!Array.<number>} */
Region.Region.prototype.squads_nearby = function(cell) {
    var ls = [];

    // special rules for attacking cell neighboring your home base
    if(hex_distance(player.home_base_loc, cell) == 1) {
        goog.object.forEach(player.squads, function(squad) {
            if(SQUAD_IDS.is_mobile_squad_id(squad['id'])) {
                if(!player.squad_is_deployed(squad['id'])) {
                    ls.push(squad['id']);
                } else if(hex_distance(squad['map_loc'], cell) == 1 &&
                          !player.squad_is_moving(squad['id'])) {
                    ls.push(squad['id']);
                }
            } else if(squad['id'] === SQUAD_IDS.BASE_DEFENDERS && gamedata['territory']['base_defenders_can_attack_neighbors']) {
                ls.push(squad['id']);
            }
        });
    } else {
        goog.object.forEach(player.squads, function(squad) {
            if(SQUAD_IDS.is_mobile_squad_id(squad['id']) &&
               player.squad_is_deployed(squad['id']) &&
               hex_distance(squad['map_loc'], cell) == 1 &&
               !player.squad_is_moving(squad['id'])) {
                ls.push(squad['id']);
            }
        });
    }

    return ls;
};

/** Make sure all features are blocking map properly
 * @param {string} where this was called from */
Region.Region.prototype.check_map_integrity = function(where) {
    var error_count = 0;
    var report_err = function(s, cell, feature) {
        error_count += 1;
        console.log('Map integrity problem ('+where+'): '+s+' : '+
                    ' cell '+(cell ? cell.pos[0].toString()+','+cell.pos[1].toString() : 'null')+
                    ' feature '+(feature ? feature['base_id']+':'+(feature['base_map_loc'] ? feature['base_map_loc'][0].toString()+','+feature['base_map_loc'][1].toString() : 'null') : 'null'));
    };

    this.for_each_feature((function (_this) { return function(feature) {
        if(feature['base_map_loc']) {
            if(_this.feature_is_moving(feature)) {
                var last_waypoint = feature['base_map_path'][feature['base_map_path'].length-1];
                if(!vec_equals(last_waypoint['xy'], feature['base_map_loc'])) {
                    report_err('feature base_map_path endpoint '+last_waypoint['xy'][0].toString()+','+last_waypoint['xy'][1].toString()+' does not match location', null, feature);
                }
            }
            var cell = _this.occupancy.cell(feature['base_map_loc']);
            if(cell.block_count < 1) {
                report_err('feature present but cell.block_count < 1', cell, feature);
            }
            if(!cell.blockers || !goog.array.contains(cell.blockers, feature)) {
                report_err('feature present but cell.blockers does not contain it', cell, feature);
            }
        }
    }; })(this));
    var seen = {};

    this.occupancy.for_each_cell((function (_this) { return function(cell) {
        if(cell.block_count != (cell.blockers ? cell.blockers.length : 0)) {
            report_err('cell block_count '+cell.block_count.toString()+' does not match blockers.length '+cell.blockers.length.toString(), cell, null);
        }
        if(cell.blockers) {
            for(var b = 0; b < cell.blockers.length; b++) {
                var feature = cell.blockers[b];
                if(feature['base_id'] in seen) {
                    var other = seen[feature['base_id']];
                    report_err('feature appears twice in occupancy (also cell '+other.pos[0].toString()+','+other.pos[1].toString()+')', cell, feature);
                    continue;
                }
                seen[feature['base_id']] = cell;
                if(!vec_equals(feature['base_map_loc'], cell.pos)) {
                    report_err('feature listed as blocker but base_map_loc is not here', cell, feature);
                }
                if(feature != _this.map_index.get_by_base_id(feature['base_id'])) {
                    report_err('feature listed as blocker but not found in index!', cell, feature);
                }
                if(!goog.array.contains(_this.features, feature)) {
                    report_err('feature listed as blocker but not found in this.features!', cell, feature);
                }
            }
        }
    }; })(this));

    if(!error_count) { console.log('integrity check OK! ('+where+')'); }
};

/** @param {!Object} res
    @param {boolean=} incremental */
Region.Region.prototype.receive_feature_update = function(res, incremental) {
    if(res['preserve_locks']) {
        incremental = true;
        delete res['preserve_locks'];
    }

    var feature = /** @type {Object|null} */ (this.map_index.get_by_base_id(res['base_id']));

    if(feature) {
        // update or delete feature we already know about
        if(res['DELETED']) {
            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, existing, DELETED, enter'); }

            if(feature['base_map_loc']) {
                // unblock, but do so carefully, because it may never have been blocked in the first place
                this.occupancy.unblock_hex_maybe(feature['base_map_loc'], feature);
            }
            this.map_index.remove(feature['base_id'], feature['base_map_loc']||null, feature);
            goog.array.remove(this.features, feature);

            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, existing, DELETED, exit'); }

        } else {
            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, existing, update, enter'); }
            var do_block = this.feature_blocks_map(feature);

            var cur_loc = feature['base_map_loc'] || null, new_loc = ('base_map_loc' in res ? res['base_map_loc'] : cur_loc);

            if(!incremental) { // full replacement of all properties
                goog.object.clear(feature);
                feature['base_id'] = res['base_id'];
            }

            if((!cur_loc && new_loc) ||
               (cur_loc && (!new_loc || cur_loc[0] != new_loc[0] || cur_loc[1] != new_loc[1]))) {

                // XXXXXX check if block_hex assumed invariant still fails sometimes
                if(cur_loc && do_block) {
                    this.occupancy.unblock_hex_maybe(cur_loc, feature);
                    //this.occupancy.block_hex(cur_loc, -1, feature);
                }
                this.map_index.remove(feature['base_id'], cur_loc||null, feature);

                if(new_loc && do_block) {
                    this.occupancy.block_hex(new_loc, 1, feature);
                }
                this.map_index.insert(feature['base_id'], new_loc||null, feature);
            }

            for(var propname in res) {
                if(res[propname] !== null) {
                    feature[propname] = res[propname];
                } else if(propname in feature) { // delete if null?
                    delete feature[propname];
                }
            }

            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, existing, update, exit'); }
        }
    } else { // no record of this feature yet
        if(res['DELETED']) {
            // could be due to a base that is added and removed before we see it the first time
            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, new, DELETED'); }
        } else {
            if(incremental) { return; }

            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, new, enter'); }
            this.features.push(res);
            if(res['base_map_loc']) {
                if(this.feature_blocks_map(res)) {
                    this.occupancy.block_hex(res['base_map_loc'],1,res);
                }
            } else {
                //throw Error('received a feature update without base_map_loc! region '+(this.data ? this.data['id'] : 'NULL!')+' base_id '+res['base_id'].toString());
            }
            this.map_index.insert(res['base_id'], res['base_map_loc']||null,res);
            if(gamedata['territory']['check_map_integrity'] >= 2) { this.check_map_integrity('receive_feature_update, new, exit'); }
        }
    }
};

// receive QUARRY_QUERY_RESULT
Region.Region.prototype.receive_update = function(db_time, result, last_db_time) {
    this.dirty = false;
    this.refresh_time = db_time;
    this.refresh_msg = null;

    if(last_db_time > 0) { // incremental result
        for(var i = 0; i < result.length; i++) {
            this.receive_feature_update(result[i]);
        }
        if(gamedata['territory']['check_map_integrity'] >= 1) { this.check_map_integrity('receive_update incremental'); }
    } else {
        // make sure there weren't any incremental updates mixed in here
        goog.array.forEach(result, function(feature) {
            if(feature['preserve_locks']) { throw Error('got non-incremental feature with preserve_locks: '+feature['base_id']); }
        });

        this.features = result;
        this.occupancy.clear();
        this.map_index.clear();
        this.for_each_feature((function (_this) { return function(feature) {
            if(feature['base_map_loc']) {
                if(_this.feature_blocks_map(feature)) {
                    _this.occupancy.block_hex(feature['base_map_loc'],1,feature);
                }
            } else {
                throw Error('received a feature without base_map_loc! region '+(_this.data ? _this.data['id'] : 'NULL')+' base_id '+feature['base_id'].toString());
            }
            _this.map_index.insert(feature['base_id'], feature['base_map_loc']||null, feature);
        }; })(this));
        if(gamedata['territory']['check_map_integrity'] >= 1) { this.check_map_integrity('receive_update full'); }
    }

    var cblist = this.fresh_cbs;
    this.fresh_cbs = [];
    for(var i = 0; i < cblist.length; i++) {
        cblist[i](this);
    }
};

Region.Region.prototype.refresh = function() {
    if(!this.dirty) { return; }
    if(!this.data) { return; }
    if(query_quarries(null, this.refresh_time)) {
        this.refresh_msg = message_queue; // store reference to the outgoing AJAX message
    }
};
Region.Region.prototype.refresh_progress = function() {
    if(this.refresh_msg) {
        return this.refresh_msg.recv_progress;
    }
    return -1;
};
Region.Region.prototype.call_when_fresh = function(cb) {
    if(!this.dirty) {
        cb(this);
        return true;
    } else {
        this.fresh_cbs.push(cb);
        this.refresh();
        return false;
    }
};
