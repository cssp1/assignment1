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
    @constructor
    @struct
    @param {!Base.Base} base
    @param {!GameObjectCollection.GameObjectCollection} objects
    @param {boolean} enable_citizens
*/
World.World = function(base, objects, enable_citizens) {
    /** @type {!Base.Base} */
    this.base = base;

    /** @type {!GameObjectCollection.GameObjectCollection} */
    this.objects = objects;
    objects.for_each(function(obj) { obj.world = this; }, this);

    /** @type {!AStar.AStarRectMap} current A* map for playfield movement queries */
    this.astar_map = new AStar.AStarRectMap(base.ncells(), null, ('allow_diagonal_passage' in gamedata['map'] ? gamedata['map']['allow_diagonal_passage'] : true));

    /** @type {!AStar.CachedAStarContext} current A* context for playfield movement queries */
    this.astar_context = new AStar.CachedAStarContext(this.astar_map,
                                                      {heuristic_name:gamedata['client']['astar_heuristic'],
                                                       iter_limit:gamedata['client']['astar_iter_limit'][is_ai_user_id_range(base.base_landlord_id) ? 'pve':'pvp'],
                                                       use_connectivity:(!!gamedata['client']['astar_use_connectivity'])});

    // note: astar_map is used for A* pathing and building placement queries ("is this cell blocked?")
    // combat-engine targeting queries ("list all objects near this point") are done using MapAccelerator
    this.voxel_map_accel = new VoxelMapAccelerator.VoxelMapAccelerator(base.ncells(), gamedata['client']['map_accel_chunk']);
    this.team_map_accel = new TeamMapAccelerator.TeamMapAccelerator();

    this.MAP_DEBUG = 0;

    /** @type {Object<string, number>} stats tracking for map queries */
    this.map_queries_by_tag = {'ticks': 0};

    /** @type {WallManager.WallManager|null} */
    this.wall_mgr = null;
    var wall_spec = gamedata['buildings']['barrier'];
    if(wall_spec && (wall_spec['collide_as_wall'] || player.get_any_abtest_value('enable_wall_manager', gamedata['client']['enable_wall_manager']))) {
        this.wall_mgr = new WallManager.WallManager(base.ncells(), wall_spec);
    }

    /** @type {!CombatEngine.CombatEngine} */
    this.combat_engine = new CombatEngine.CombatEngine(this);

    /** @type {number} client_time at which last unit simulation tick was run */
    this.last_tick_time = 0;

    /** @type {!SPFX.FXWorld} special effects world, with physics properties */
    this.fxworld = new SPFX.FXWorld((('gravity' in base.base_climate_data) ? base.base_climate_data['gravity'] : 1),
                                    (('ground_plane' in base.base_climate_data) ? base.base_climate_data['ground_plane'] : 0));

    /** @type {Citizens.Context|null} army units walking around the base */
    this.citizens = null;
    this.citizens_dirty = false;
    if(enable_citizens) {
        this.citizens = new Citizens.Context(this.base, this.astar_context, this.fxworld);
        this.lazy_update_citizens();
    }
};

World.World.prototype.dispose = function() {
    if(this.fxworld) {
        this.fxworld.clear();
    }
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

World.World.prototype.run_unit_ticks = function() {
    if(client_time - this.last_tick_time > TICK_INTERVAL/combat_time_scale()) {
        // record time at which this tick was computed
        this.last_tick_time = client_time;

        if(this.wall_mgr && this.objects) { this.wall_mgr.refresh(this.objects); }

        ai_pick_target_classic_cache_gen = -1; // clear the targeting cache

        if(astar_map) {
            astar_map.cleanup();
        }

        // Limit the number of A* path queries that can be run per
        // unit tick. Massive numbers of units re-targeting at the same time often
        // causes performance glitches
        tick_astar_queries_left = gamedata['client']['astar_max_queries_per_tick'];

        // randomly permute the order of objects each tick, so we don't starve
        // out objects waiting for A*
        // http://en.wikipedia.org/wiki/Fisher%E2%80%93Yates_shuffle
        // (note: will need to be deterministically seeded if we want deterministic combat)

        var obj_list = [null];
        var i = 0;
        for(var id in session.cur_objects.objects) {
            var obj = session.cur_objects.objects[id];
            // ignore inerts with no auras or contiuously-casting spells on them
            if(obj.is_inert() && obj.auras.length === 0 && !('continuous_cast' in obj.spec)) { continue; }

            var j = Math.floor(Math.random()*(i+1));
            obj_list[i] = obj_list[j];
            obj_list[j] = obj;
            i++;
        }

        // rebuild map query acceleration data structure
        this.voxel_map_accel.clear();
        this.team_map_accel.clear();
        this.map_queries_by_tag['ticks'] += 1;
        if(obj_list[0] !== null) {
            for(i = 0; i < obj_list.length; i++) {
                var obj = obj_list[i];

                // check for any objects in blocked areas
                if(PLAYFIELD_DEBUG && obj.is_mobile() && !obj.is_destroyed()) {
                    playfield_check_path([obj.pos, obj.next_pos], 'pos->next_pos at beginning of tick');
                }

                if(!obj.is_destroyed()) {
                    // don't bother adding destroyed objects, since no users of query_objects_within_distance() look for destroyed things
                    this.team_map_accel.add_object(obj);
                    this.voxel_map_accel.add_object(obj);
                }
            }
            for(i = 0; i < obj_list.length; i++) {
                obj_list[i].run_tick();
            }
        }

        // run phantom unit controllers
        tick_astar_queries_left = -1; // should not disturb actual unit control
        goog.array.forEach(this.fxworld.get_phantom_objects(this), function(obj) {
            obj.run_control();
            obj.update_facing();
        }, this);

        apply_queued_damage_effects();
        flush_dirty_objects({urgent_only:true, skip_check:true});
        this.combat_engine.cur_tick = new GameTypes.TickCount(this.combat_engine.cur_tick.get()+1);
    }
};

/** @return {!Object<string,?>} */
World.World.prototype.serialize = function() {
    return {'base': this.base.serialize(),
            'combat_engine': this.combat_engine.serialize(),
            'objects': this.objects.serialize()
           };
};

World.World.prototype.persist_debris = function() {
    if(('show_debris' in this.base.base_climate_data) && !this.base.base_climate_data['show_debris']) { return; }
    for(var id in this.fxworld.current_under) {
        var effect = this.fxworld.current_under[id];
        if(effect.user_data && effect.user_data['persist'] === 'debris') {
            send_to_server.func(["CREATE_INERT", effect.user_data['spec'], effect.user_data['pos'], effect.user_data['metadata']]);
            effect.user_data = null;
            this.fxworld.remove(effect);
        }
    }
};
