goog.provide('World');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('AStar');
goog.require('Base');
goog.require('Citizens');
goog.require('CombatEngine');
goog.require('GameTypes');
goog.require('GameObjectCollection');
goog.require('WallManager');

/** Encapsulates the renderable/simulatable "world"
    XXXXXX remove non-base version and replace with a "blank" world type
    @constructor
    @param {Base.Base|null} base
    @param {GameObjectCollection.GameObjectCollection|null} objects
*/
World.World = function(base, objects) {
    /** @type {Base.Base|null} */
    this.base = base;

    /** @type {GameObjectCollection.GameObjectCollection|null} */
    this.objects = objects;

    /** @type {?AStar.AStarRectMap} current A* map for playfield movement queries */
    this.astar_map = (base ? new AStar.AStarRectMap(base.ncells(), null, ('allow_diagonal_passage' in gamedata['map'] ? gamedata['map']['allow_diagonal_passage'] : true)) : null);

    /** @type {?AStar.CachedAStarContext} current A* context for playfield movement queries */
    this.astar_context = (base ? new AStar.CachedAStarContext(this.astar_map,
                                                              {heuristic_name:gamedata['client']['astar_heuristic'],
                                                               iter_limit:gamedata['client']['astar_iter_limit'][is_ai_user_id_range(base.base_landlord_id) ? 'pve':'pvp'],
                                                               use_connectivity:(!!gamedata['client']['astar_use_connectivity'])}) : null);

    // note: astar_map is used for A* pathing and building placement queries ("is this cell blocked?")
    // combat-engine targeting queries ("list all objects near this point") are done using MapAccelerator
    this.voxel_map_accel = new VoxelMapAccelerator.VoxelMapAccelerator((base ? base.ncells() : [0,0]), (base ? gamedata['client']['map_accel_chunk'] : 1));
    this.team_map_accel = new TeamMapAccelerator.TeamMapAccelerator();

    this.MAP_DEBUG = 0;

    /** @type {Object<string, number>} stats tracking for map queries */
    this.map_queries_by_tag = {'ticks': 0};

    /** @type {WallManager.WallManager|null} */
    this.wall_mgr = null;
    if(base) { // note: gamedata is not available on first load
        var wall_spec = gamedata['buildings']['barrier'];
        if(wall_spec && (wall_spec['collide_as_wall'] || player.get_any_abtest_value('enable_wall_manager', gamedata['client']['enable_wall_manager']))) {
            this.wall_mgr = new WallManager.WallManager(base.ncells(), wall_spec);
        }
    }

    /** @type {CombatEngine.CombatEngine|null} */
    this.combat_engine = (base ? new CombatEngine.CombatEngine(this) : null);

    /** @type {Citizens.Context|null} */
    this.citizens = null; // army units walking around the base
    this.citizens_dirty = false;
};

World.World.prototype.dispose = function() {
    if(this.citizens) {
        this.citizens.dispose();
        this.citizens = null;
    }
};

World.World.prototype.lazy_update_citizens = function() { this.citizens_dirty = true; };
World.World.prototype.do_update_citizens = function(player) {
    if(this.citizens) {
        var data_list;
        if(this.citizens_dirty) { // need to tell Citizens about changes to army contents
            this.citizens_dirty = false;
            data_list = [];
            goog.object.forEach(player.my_army, function(obj) {
                if((obj['squad_id']||0) == SQUAD_IDS.BASE_DEFENDERS) {
                    data_list.push(new Citizens.UnitData(obj['obj_id'], obj['spec'], obj['level']||1, ('hp_ratio' in obj ? obj['hp_ratio'] : 1)));
                }
            }, this);
        } else {
            data_list = null; // no update to army contents
        }
        this.citizens.update(data_list);
    }
};

World.World.prototype.map_query_stats = function() {
    console.log("MAP QUERIES:");
    for(var k in this.map_queries_by_tag) {
        if(k == 'ticks') { continue; }
        var msec = 1000.0*this.map_queries_by_tag[k]/(1.0*this.map_queries_by_tag['ticks']);
        if(msec >= 0.1) {
            console.log(k + ' ' + msec.toFixed(1) + 'ms per tick');
        }
    }
};


/** NEW object query function
    param meanings:
    ignore_object = ignore this single object
    exlude_barriers = do not return any barrier objects
    include_collidable_inerts = include objects that are inert
    only_team = only return objects on this team
    mobile_only = only return mobile units
    exclude_flying = exclude flying mobile units
    flying_only = only return flying mobile units
    exclude_invisible_to = ignore objects that are not visible to this team

    @param {!Array.<number>} loc
    @param {number} dist
    @param {{nearest_only:(boolean|undefined),
             tag:(string|undefined),
             only_team:(string|null|undefined),
             ignore_object:(Object|undefined),
             exclude_barriers:(boolean|undefined),
             exclude_invul:(boolean|undefined),
             include_collidable_inerts:(boolean|undefined),
             include_destroyed:(boolean|undefined),
             exclude_full_health:(boolean|undefined),
             mobile_only:(boolean|undefined),
             exclude_flying:(boolean|undefined),
             flying_only:(boolean|undefined),
             exclude_invisible_to:(string|null|undefined)}} params
    @return {!Array.<!GameTypes.GameObjectQueryResult>}
*/
World.World.prototype.query_objects_within_distance = function(loc, dist, params) {
    if(dist <= 0) {
        return [];
    }
    if(params.include_destroyed) {
        throw Error('include_destroyed not supported'); // since they are not added to the accelerators
    }

    /** @type {!Array.<!GameTypes.GameObjectQueryResult>} */
    var ret = [];
    var neardist = 99999999;
    var nearest = null; // obj/dist/pos tuple representing nearest object

    // log it
    var debug_tag = 'tag:' + (params.tag || 'UNKNOWN');
    if(params.nearest_only) { debug_tag += '_nearest_only'; }
    if(params.only_team) { debug_tag += '_one_team'; } else { debug_tag += '_any_team'; }
    var start_time;
    if(this.MAP_DEBUG) {
        start_time = (new Date()).getTime();
    }

    var use_accel = gamedata['client']['use_map_accel'];

    if(use_accel && params.only_team && !this.voxel_map_accel.has_any_of_team(params.only_team)) {
        // no objects exist
        debug_tag += ':EMPTY';
    } else if(use_accel && (dist < gamedata['client']['map_accel_limit'])) {
        // do not use map accelerator for very large query radii, since it results in lots of unnecessary extra work
        // due to big objects overlapping many cells
        var filter = (params.only_team || 'ALL');
        debug_tag += ':LOCAL';
        // TEMPORARY - duplicated code
        var bounds = this.voxel_map_accel.get_circle_bounds_xy_st(loc, dist);
        if(this.MAP_DEBUG >= 2) {
            var area_s = (bounds[1][1]-bounds[1][0]);
            var area_t = (bounds[0][1]-bounds[0][0]);
            debug_tag += '('+area_s.toString()+','+area_t.toString()+')';
        }
        var seen_ids = {};
        //console.log(" Y "+bounds[1][0]+"-"+bounds[1][1]+" X "+bounds[0][0]+"-"+bounds[0][1]);
        for(var t = bounds[1][0]; t < bounds[1][1]; t++) {
            for(var s = bounds[0][0]; s < bounds[0][1]; s++) {
                var objlist = this.voxel_map_accel.objects_at_st([s,t], filter);
                if(!objlist) { continue; }
                for(var i = 0, len = objlist.length; i < len; i++) {
                    var temp = objlist[i];

                    if(temp.id in seen_ids) { continue; }
                    seen_ids[temp.id] = 1;

                    if(params.ignore_object && temp === params.ignore_object) { continue; }
                    if(params.exclude_barriers && temp.spec['name'] === 'barrier') { continue; }
                    if(params.exclude_invul && temp.is_invul()) { continue; }
                    if(temp.is_inert() && (!params.include_collidable_inerts || !temp.spec['unit_collision_gridsize'][0])) { continue; }
                    if(params.only_team && params.only_team !== temp.team) { continue; }
                    if(!params.include_destroyed && temp.is_destroyed()) { continue; }
                    if(params.exclude_full_health && !temp.is_damaged()) { continue; }
                    if(params.mobile_only && !temp.is_mobile()) { continue; }
                    if(params.exclude_flying && temp.is_flying()) { continue; }
                    if(params.flying_only &&!temp.is_flying()) { continue; }
                    if(params.exclude_invisible_to && temp.is_invisible() && (temp.team !== params.exclude_invisible_to)) { continue; }



                    // note: it is OK to use the quantized combat-sim position of the unit here, as long as this is only called
                    // from combat-sim step functions
                    var xy = temp.raw_pos();
                    var temp_dist = vec_distance(loc, xy) - temp.hit_radius();
                    if(temp_dist < dist) {
                        var r = new GameTypes.GameObjectQueryResult(temp, temp_dist, xy);
                        ret.push(r);
                        if(temp_dist < neardist) {
                            nearest = r;
                            neardist = temp_dist;
                        }
                    }
                }
            }
        }
    } else {
        // big O(N) query
        debug_tag += ':GLOBAL';
        var filter = (params.only_team || 'ALL');
        var objlist = this.team_map_accel.objects_on_team(filter);
        if(objlist) {
            for(var i = 0, len = objlist.length; i < len; i++) {
                temp = objlist[i];
                if(params.ignore_object && temp === params.ignore_object) { continue; }
                if(params.only_team && params.only_team !== temp.team) { continue; }
                if(params.exclude_barriers && temp.spec['name'] === 'barrier') { continue; }
                if(params.exclude_invul && temp.is_invul()) { continue; }
                if(temp.is_inert() && (!params.include_collidable_inerts || !temp.spec['unit_collision_gridsize'][0])) { continue; }
                if(!params.include_destroyed && temp.is_destroyed()) { continue; }
                if(params.exclude_full_health && !temp.is_damaged()) { continue; }
                if(params.mobile_only && !temp.is_mobile()) { continue; }
                if(params.exclude_flying && temp.is_flying()) { continue; }
                if(params.flying_only &&!temp.is_flying()) { continue; }
                if(params.exclude_invisible_to && temp.is_invisible() && (temp.team !== params.exclude_invisible_to)) { continue; }

                // note: it is OK to use the "retarded" combat-sim position of the unit here, as long as this is only called
                // from combat-sim step functions
                var xy = temp.raw_pos(); // temp.interpolate_pos();
                var temp_dist = vec_distance(loc, xy) - temp.hit_radius();
                if(temp_dist < dist) {
                    var r2 = new GameTypes.GameObjectQueryResult(temp, temp_dist, xy);
                    ret.push(r2);
                    if(temp_dist < neardist) {
                        nearest = r2;
                        neardist = temp_dist;
                    }
                }
            }
        }
    }

    if(this.MAP_DEBUG) {
        var end_time = (new Date()).getTime();
        var secs = (end_time - start_time)/1000;
        this.map_queries_by_tag[debug_tag] = (this.map_queries_by_tag[debug_tag] || 0) + secs;
    }

    if(params.nearest_only) {
        return (!!nearest ? [/** @type {!GameTypes.GameObjectQueryResult} */ (nearest)] : []);
    } else {
        return ret;
    }
};
