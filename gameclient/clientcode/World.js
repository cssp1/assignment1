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
goog.require('goog.events');
goog.require('goog.events.EventTarget');
goog.require('goog.events.Event');

/** @constructor @struct
    @extends {goog.events.Event}
    @param {string} type
    @param {Object} target
    @param {!GameObject} obj */
World.ObjectAddedEvent = function(type, target, obj) {
    goog.base(this, type, target);
    this.obj = obj;
};
goog.inherits(World.ObjectAddedEvent, goog.events.Event);

/** @constructor @struct
    @extends {goog.events.Event}
    @param {string} type
    @param {Object} target
    @param {!GameObject} obj */
World.ObjectRemovedEvent = function(type, target, obj) {
    goog.base(this, type, target);
    this.obj = obj;
};
goog.inherits(World.ObjectRemovedEvent, goog.events.Event);

/** Encapsulates the renderable/simulatable "world"
    @constructor @struct
    @implements {GameTypes.ISerializable}
    @param {!Base.Base} base
    @param {!Array<!GameObject>} objects
    @param {boolean} enable_citizens
*/
World.World = function(base, objects, enable_citizens) {
    /** @type {!Base.Base} */
    this.base = base;

    /** @type {!GameObjectCollection.GameObjectCollection} */
    this.objects = new GameObjectCollection.GameObjectCollection();
    this.objects.listen('added', this.on_object_added, false, this);
    this.objects.listen('removed', this.on_object_removed, false, this);
    goog.array.forEach(objects, function(obj) {
        this.objects.add_object(obj);
    }, this);

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

    this.tick_astar_queries_left = 0;

    // to help swarms of identical units find targets faster, cache the results
    this.ai_pick_target_classic_cache = {};
    this.ai_pick_target_classic_cache_gen = -1;
    this.ai_pick_target_classic_cache_hits = 0;
    this.ai_pick_target_classic_cache_misses = 0;

    /** @type {WallManager.WallManager|null} */
    this.wall_mgr = null;
    var wall_spec = gamedata['buildings']['barrier'];
    if(wall_spec && (wall_spec['collide_as_wall'] || player.get_any_abtest_value('enable_wall_manager', gamedata['client']['enable_wall_manager']))) {
        this.wall_mgr = new WallManager.WallManager(base.ncells(), wall_spec);
    }

    /** @type {!CombatEngine.CombatEngine} */
    this.combat_engine = new CombatEngine.CombatEngine();

    /** @type {number} client_time at which last unit simulation tick was run */
    this.last_tick_time = 0;

    /** @type {boolean} */
    this.ai_paused = false;
    this.control_paused = false;

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

    this.notifier = new goog.events.EventTarget();
};

/** @param {string|!goog.events.EventId.<EVENTOBJ>} type The event type id.
    @param {function(this:SCOPE, EVENTOBJ):(boolean|undefined)} listener Callback method.
    @param {boolean=} opt_useCapture Whether to fire in capture phase
    @param {SCOPE=} opt_listenerScope Object in whose scope to call the listener.
    @return {goog.events.ListenableKey} Unique key for the listener.
    @template SCOPE,EVENTOBJ */
World.World.prototype.listen = function(type, listener, opt_useCapture, opt_listenerScope) {
    return this.notifier.listen(type, listener, opt_useCapture, opt_listenerScope);
};
/** @param {!goog.events.ListenableKey} key
    @return {boolean} Whether any listener was removed. */
World.World.prototype.unlistenByKey = function(key) {
    return this.notifier.unlistenByKey(key);
};

World.World.prototype.dispose = function() {
    this.notifier.removeAllListeners();
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

/** @param {!GameObjectCollection.AddedEvent} event */
World.World.prototype.on_object_added = function(event) {
    this.notifier.dispatchEvent(new World.ObjectAddedEvent('object_added', this, event.obj));
    event.obj.on_added_to_world(this);
};
/** @param {!GameObjectCollection.RemovedEvent} event */
World.World.prototype.on_object_removed = function(event) {
    this.notifier.dispatchEvent(new World.ObjectRemovedEvent('object_removed', this, event.obj));
    event.obj.on_removed_from_world(this);
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
                var xy = temp.raw_pos();
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
        this.combat_engine.cur_tick = new GameTypes.TickCount(this.combat_engine.cur_tick.get()+1);
        this.combat_engine.cur_client_time = client_time;

        if(this.wall_mgr && this.objects) { this.wall_mgr.refresh(this.objects); }

        this.ai_pick_target_classic_cache_gen = -1; // clear the targeting cache

        if(this.astar_map) {
            this.astar_map.cleanup();
        }

        // Limit the number of A* path queries that can be run per
        // unit tick. Massive numbers of units re-targeting at the same time often
        // causes performance glitches
        this.tick_astar_queries_left = gamedata['client']['astar_max_queries_per_tick'];

        // randomly permute the order of objects each tick, so we don't starve
        // out objects waiting for A*
        var obj_list = this.objects.get_random_permutation(function(obj) {
            // ignore inerts with no auras or contiuously-casting spells on them
            if(obj.is_inert() && obj.auras.length === 0 && !('continuous_cast' in obj.spec)) { return false; }
            return true;
        }, this);

        // rebuild map query acceleration data structure
        this.voxel_map_accel.clear();
        this.team_map_accel.clear();
        this.map_queries_by_tag['ticks'] += 1;

        goog.array.forEach(obj_list, function(obj) {

            // check for any objects in blocked areas
            if(PLAYFIELD_DEBUG && obj.is_mobile() && !obj.is_destroyed()) {
                this.playfield_check_path([obj.pos, obj.next_pos], 'pos->next_pos at beginning of tick');
            }

            if(!obj.is_destroyed()) {
                // don't bother adding destroyed objects, since no users of query_objects_within_distance() look for destroyed things
                this.team_map_accel.add_object(obj);
                this.voxel_map_accel.add_object(obj);
            }
        }, this);

        goog.array.forEach(obj_list, function(obj) {
            obj.update_stats(this);
        }, this);

        // AI layer
        if(!this.ai_paused) {
            goog.array.forEach(obj_list, function(obj) {
                obj.ai_threatlist_update(this);
                obj.run_ai(this);
            }, this);
        }

        this.notifier.dispatchEvent(new goog.events.Event('before_control', this));

        // Control layer and visual effects
        if(!this.control_paused) {
            goog.array.forEach(obj_list, function(obj) {
                obj.run_control(this);
                obj.update_facing();
                if(obj.is_mobile()) {
                    obj.add_movement_effect(this.fxworld);
                }
                obj.update_aura_effects(this);
            }, this);

            // run phantom unit controllers
            this.tick_astar_queries_left = -1; // should not disturb actual unit control
            goog.array.forEach(this.fxworld.get_phantom_objects(), function(obj) {
                obj.run_control(this);
                obj.update_facing();
                obj.add_movement_effect(this.fxworld);
            }, this);

            this.notifier.dispatchEvent(new goog.events.Event('before_damage_effects', this));

            this.combat_engine.apply_queued_damage_effects(this, COMBAT_ENGINE_USE_TICKS);

            this.notifier.dispatchEvent(new goog.events.Event('after_damage_effects', this));
        }
    }
};

/** @override */
World.World.prototype.serialize = function() {
    return {'base': this.base.serialize(),
            'combat_engine': this.combat_engine.serialize(),
            'objects': this.objects.serialize()
           };
};

/** @override */
World.World.prototype.apply_snapshot = function(snap) {
    this.base.apply_snapshot(snap['base']);
    this.combat_engine.apply_snapshot(snap['combat_engine']);
    this.objects.apply_snapshot(snap['objects']);
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

/** Main object removal function
    @param {!GameObject} obj */
World.World.prototype.remove_object = function(obj) {
    // update map
    if(obj.is_blocker() && !obj.is_destroyed()) {
        obj.block_map(-1, 'remove_object');
    }

    obj.remove_permanent_effect(this);

    obj.dispose(); // call this before rem_object() so obj.id is still valid

    this.objects.rem_object(obj);
};

/** For level-editing only!
    @param {!GameObject} obj */
World.World.prototype.send_and_remove_object = function(obj) {
    if(obj.id && obj.id !== GameObject.DEAD_ID) {
        send_to_server.func(["REMOVE_OBJECT", obj.id]);
        this.remove_object(obj);
    }
};
/** @param {!GameObject} victim
    @param {GameObject|null} killer */
World.World.prototype.send_and_destroy_object = function(victim, killer) {
    if(this === session.get_real_world()) { // XXXXXX ugly
        send_to_server.func(["DSTROY_OBJECT",
                             victim.id,
                             victim.raw_pos(),
                             get_killer_info(killer)
                            ]);
    }
    this.remove_object(victim);
    if(this === session.get_real_world()) {
        session.set_battle_outcome_dirty();
    }
};


World.World.prototype.remove_all_barriers = function() {
    this.objects.for_each(function(obj) {
        if(obj.spec['name'] === 'barrier') {
            this.send_and_remove_object(obj);
        }
    }, this);
};
World.World.prototype.upgrade_all_barriers = function() {
    this.objects.for_each(function(obj) {
        if(obj.spec['name'] === 'barrier') {
            Store.place_user_currency_order(obj.id, 'UPGRADE_FOR_MONEY', null, null, null);
        }
    }, this);
};

World.World.prototype.destroy_all_enemies = function() {
    this.objects.for_each(function(obj) {
        if(obj.team === 'enemy' && !obj.is_destroyed()) {
            if(obj.is_mobile()) {
                this.send_and_destroy_object(obj, null);
            } else if(obj.is_building()) {
                obj.hp = 0;
                obj.state_dirty |= obj_state_flags.HP;
            }
        }
    }, this);
    flush_dirty_objects({});
};

/** @param {!GameObject} target
    @param {!Array<number>} pos */
World.World.prototype.create_debris = function(target, pos) {
    // add client-side debris effect
    var inert_specname;
    if('destroyed_inert' in target.spec) {
        inert_specname = target.spec['destroyed_inert']; // can be null
    } else {
        inert_specname = gamedata['default_debris_inert'];
    }

    if(!inert_specname) { return; }

    var inertspec = gamedata['inert'][inert_specname];

    var debris = new SPFX.Debris(pos, inertspec['art_asset'], target.interpolate_facing(this));
    debris.show = (!('show_debris' in this.base.base_climate_data) || this.base.base_climate_data['show_debris']);
    this.fxworld.add_under(debris);

    var tooltip = target.spec['ui_name'] + ' ' + inertspec['ui_name'];
    if(target.team === 'player') {
        tooltip += ' ('+player.get_ui_name()+')';
    } else if(target.team === 'enemy') {
        if(session.home_base) {
            if(session.incoming_attacker_name) {
                tooltip += ' ('+session.incoming_attacker_name+')';
            }
        } else {
            tooltip += ' ('+session.ui_name.split(' ')[0]+')';
        }
    }
    // add user_data that persist_debris() will reference at end of combat
    debris.user_data = { 'persist': 'debris',
                         'spec': inertspec['name'],
                         'pos': vec_floor(pos),
                         'metadata': {'facing':target.interpolate_facing(this), 'tooltip': tooltip} };
};


/** @param {!GameObject} target
    @param {number} damage
    @param {Object<string,number>|null} vs_table
    @param {GameObject|null} source */
World.World.prototype.hurt_object = function(target, damage, vs_table, source) {
    if(target.id === GameObject.DEAD_ID) {
        throw Error('hurt_object called on dead object');
    }
    //console.log('hurt_object '+target.spec['name']+' from '+(source?source.spec['name']:'null'));

    // save for metrics use, because id goes to -1 when the target dies
    var original_target_id = target.id;

    if(target.max_hp === 0) { return; } // can't hurt indestructible objects

    var pos = target.interpolate_pos(this);

    // offset time to de-synchronize visual effects
    var time_offset = Math.random()*TICK_INTERVAL/combat_time_scale();

    damage *= get_damage_modifier(vs_table, target);


    if(damage > 0) {

        if(!vs_table || !vs_table['ignores_armor']) {
            // reduce damage (not healing) by target's armor, down to a minimum of 1
            var armor = target.get_leveled_quantity(target.spec['armor'] || 0);
            armor += target.combat_stats.extra_armor;

            if(armor > 0) {
                damage -= armor;
            }
        }

        // modify by damage_taken combat stat
        damage *= target.combat_stats.damage_taken;

        if(damage < 1) { damage = 1; }
    }

    damage = Math.floor(damage);

    if(COMBAT_DEBUG) {
        // Damage text
        this.fxworld.add(new SPFX.CombatText(pos,
                                             target.is_flying() ? target.altitude : 0,
                                             pretty_print_number(Math.abs(damage)),
                                             (damage >= 0 ? [1, 1, 0.1, 1] : [0,1,0,1]),
                                             (COMBAT_ENGINE_USE_TICKS ? new SPFX.When(null, this.combat_engine.cur_tick, time_offset) : new SPFX.When(client_time + time_offset, null)),
                                             1.0, {drop_shadow:true}));
    }

    // make player units invincible during the tutorial
    if(player.tutorial_state != "COMPLETE") {
        if(target.team === 'player') {
            var health_limit;
            if(target.is_building() && target.is_shooter()) {
                health_limit = target.max_hp;
            } else {
                health_limit = Math.floor(0.2 * target.max_hp);
            }
            if(target.hp - damage < health_limit) {
                damage = target.hp - health_limit;
            }
        }
    }

    var was_destroyed = target.is_destroyed(); // always going be false unless we implement building repair

    var original_target_hp = target.hp;

    target.hp -= damage;
    target.last_attacker = source;
    target.state_dirty |= obj_state_flags.HP;

    if(target.is_building()) {
        // immediately show that repair/research/upgrade/production stops in the UI. Subsequent OBJECT_STATE_UPDATE will return correct HP value and start/stop times.
        target.repair_finish_time = -1;
        if(target.research_start_time > 0) {
            target.research_done_time += server_time - target.research_start_time;
            target.research_start_time = -1;
            target.state_dirty |= obj_state_flags.URGENT;
        }
        if(target.build_start_time > 0) {
            target.build_done_time += server_time - target.build_start_time;
            target.build_start_time = -1;
            target.state_dirty |= obj_state_flags.URGENT;
        }
        if(target.upgrade_start_time > 0) {
            target.upgrade_done_time += server_time - target.upgrade_start_time;
            target.upgrade_start_time = -1;
            target.state_dirty |= obj_state_flags.URGENT;
        }
        if(target.manuf_start_time > 0) {
            target.manuf_done_time += server_time - target.manuf_start_time;
            target.manuf_start_time = -1;
            target.state_dirty |= obj_state_flags.URGENT;
        }
        if(target.is_crafting()) {
            var cat = gamedata['crafting']['categories'][gamedata['crafting']['recipes'][target.is_crafting()]['crafting_category']];
            if(('haltable' in cat) && !cat['haltable']) {
                // not haltable
            } else {
                // client-side predict what will happen

                // first check if we're going to modify anything,
                // since we do not want start_client_prediction() to
                // fire a sync request if there is no actual mutation.
                var need_to_halt = false;
                goog.array.forEach(target.get_crafting_queue(), function(bus) {
                    if(bus['start_time'] > 0) {
                        need_to_halt = true;
                    }
                });
                if(need_to_halt) {
                    // XXX the request_sync here might need to be reordered after OBJECT_COMBAT_UPDATES
                    var craft_queue = target.start_client_prediction('crafting.queue', target.crafting['queue']);
                    goog.array.forEach(craft_queue, function(bus) {
                        if(bus['start_time'] > 0) {
                            bus['done_time'] += Math.max(0, server_time - bus['start_time']);
                            bus['start_time'] = -1;
                            target.state_dirty |= obj_state_flags.URGENT;
                        }
                    });
                }
            }
        }
    }

    if(target.hp <= 0) {
        // object is destroyed
        target.hp = 0;

        if(target.is_building() && target.killer_info === null) {
            target.killer_info = get_killer_info(source);
        }

        // visual explosion and debris effects
        var fx_data = null;
        if(target === source && ('suicide_explosion_effect' in target.spec)) {
            fx_data = target.spec['suicide_explosion_effect'];
        } else if(target.is_mobile()) {
            this.create_debris(target, pos);
            if('explosion_effect' in target.spec) {
                fx_data = target.spec['explosion_effect'];
            } else {
                fx_data = player.get_any_abtest_value('unit_explosion_effect', gamedata['client']['vfx']['unit_explosion']);
            }
        } else {
            // buildings
            if('explosion_effect' in target.spec) {
                fx_data = target.spec['explosion_effect'];
            } else if(target.spec['gridsize'][0] > 2) {
                // big buildings
                fx_data = player.get_any_abtest_value('building_explosion_normal_effect', gamedata['client']['vfx']['building_explosion_normal']);
            } else {
                fx_data = player.get_any_abtest_value('building_explosion_small_effect', gamedata['client']['vfx']['building_explosion_small']);
            }
        }

        if(fx_data) {
            this.fxworld.add_visual_effect_at_time(pos, (target.is_mobile() && target.is_flying() ? target.altitude : 0), [0,1,0], client_time+time_offset, fx_data, true, null);
        }

        target.update_permanent_effect(this);

        // destruction of mobile units and buildings is handled differently
        if(target.is_mobile()) {
            if(('on_death_spell' in target.spec) && !target.combat_stats.disarmed) {
                var death_spell_name = target.spec['on_death_spell'];
                target.cast_client_spell(this, death_spell_name, gamedata['spells'][death_spell_name], target, null);
            } else {
                this.send_and_destroy_object(target, source);
            }
        } else if(target.is_building() || target.is_inert()) {
            target.state_dirty |= obj_state_flags.URGENT;

            // mark the tracked quest as dirty so we can update any quest tips
            player.quest_tracked_dirty = true;
            if(target.is_building()) {
                session.set_battle_outcome_dirty();
            }
        }

    } else if(damage < 0) {
        // healing
        if(target.hp > target.max_hp) { target.hp = target.max_hp; }
    } else {
        // took damage but was not destroyed
        if(target.is_mobile() && target.ai_state === ai_states.AI_DEFEND_MOVE) {
            // switch to attack-move-aggro
            for(var i = 0; i < target.orders.length; i++) {
                var order = target.orders[i];
                order['state'] = ai_states.AI_ATTACK_MOVE_AGGRO;
            }
            target.apply_orders(this);
        }

        // check for gradual looting
        if(target.is_building() && (target.is_storage() || target.is_producer())) {
            // "ticks" here refer to the chunks of loot given out as certain hitpoint thresholds are crossed
            // see gameserver/ResLoot.py for the details.
            var tick_size = ('gradual_loot' in gamedata ? gamedata['gradual_loot'] : -1);
            if(tick_size > 0) {
                var last_tick = Math.floor((original_target_hp-1)/tick_size) + 1;
                var this_tick = Math.floor((target.hp-1)/tick_size) + 1;
                if(this_tick < last_tick) {
                    target.state_dirty |= obj_state_flags.URGENT; // transmit the new hp value at the end of this tick
                }
            }
        }

        if('damaged_effect' in target.spec) {
            this.fxworld.add_visual_effect_at_time(pos, (target.is_mobile() && target.is_flying() ? target.altitude : 0), [0,1,0], client_time+time_offset, target.spec['damaged_effect'], true, null);
        }
    }

    if(target.is_blocker()) {
        if(!was_destroyed && target.is_destroyed()) {
            target.block_map(-1, 'hurt_object(destroyed)');
        }
        if(was_destroyed && !target.is_destroyed()) {
            target.block_map(1, 'hurt_object(undestroyed)');
        }
    }

    if(player.is_suspicious) {
        metric_event('3950_object_hurt', {'attack_event': true,
                                          'shooter_id': source ? source.id : -1,
                                          'shooter_type': (source && source.spec && source.spec['name']) ? source.spec['name'] : 'unknown',
                                          'shooter_team': source ? source.team : 'none',
                                          'target_id': original_target_id,
                                          'target_type': target.spec['name'],
                                          'target_team': target.team,
                                          'target_pos': pos,
                                          'damage': damage,
                                          'hp_before': original_target_hp,
                                          'hp_left': target.hp,
                                          'client_time': client_time
                                        });
    }
};


/** @param {!Array<number>} xy
    @return {boolean} whether combat units can be deployed (by the player) at this location */
World.World.prototype.is_deployment_location_valid = function(xy) {
    var ncells = this.base.ncells();

    // check against play area bounds
    if(xy[0] < 0 || xy[0] >= ncells[0] || xy[1] < 0 || xy[1] >= ncells[1]) {
        return false;
    }

    if(this.base.base_landlord_id === session.user_id) {
        return true; // landlord can deploy anywhere
    }

    // check against base perimeter or deployment zone
    if(this.base.has_deployment_zone()) {
        // Gangnam style
        if(this.base.deployment_buffer['type'] != 'polygon') { throw Error('unhandled deployment buffer type'+this.base.deployment_buffer['type'].toString()); }
        // point-in-polygon test via winding order
        var sign = 0;
        for(var i = 0; i < this.base.deployment_buffer['vertices'].length; i++) {
            var iend = ((i+1) % this.base.deployment_buffer['vertices'].length);
            var start = this.base.deployment_buffer['vertices'][i];
            var end = this.base.deployment_buffer['vertices'][iend];
            var seg = vec_sub(end, start);
            var point = vec_sub(xy, start);
            var k = seg[0]*point[1] - seg[1]*point[0];
            var sign_k = (k >= 0 ? 1 : -1);
            if(sign == 0) {
                sign = sign_k;
            } else if(sign_k != sign) {
                return false;
            }
        }
    } else if(gamedata['map']['deployment_buffer'] >= 0) {
        // old style
        var mid = this.base.midcell();
        var rad = [this.base.get_base_radius(), this.base.get_base_radius()];

        if(this.base.deployment_buffer) { rad[0] += gamedata['map']['deployment_buffer']; rad[1] += gamedata['map']['deployment_buffer']; }
        rad[0] += Math.max(0, (ncells[0] - gamedata['map']['default_ncells'][0])/2);
        rad[1] += Math.max(0, (ncells[1] - gamedata['map']['default_ncells'][1])/2);
        if(xy[0] >= mid[0]-rad[0] && xy[0] <= mid[0]+rad[0] && xy[1] >= mid[1]-rad[1] && xy[1] <= mid[1]+rad[1]) {
            return false;
        }
    }

    // check against blockage from buildings
    if(this.astar_map.is_blocked(vec_floor(xy))) {
        return false;
    }

    // check building deployment buffer
    if((gamedata['map']['building_deployment_buffer']||0) > 0) {
        var buf = gamedata['map']['building_deployment_buffer'];
        var blocked = false;
        this.objects.for_each(function(obj) {
            if(obj.is_building() && obj.team != 'player') {
                var hisbound = get_grid_bounds([obj.x,obj.y], obj.spec['gridsize']);
                if(xy[0] >= hisbound[0][0]-buf && xy[0] < hisbound[0][1]+buf &&
                   xy[1] >= hisbound[1][0]-buf && xy[1] < hisbound[1][1]+buf) {
                    blocked = true;
                }
            }
        }, this);
        if(blocked) {
            return false;
        }
    }
    return true;
};


// The playfield_check_*() functions check for violations of
// invariants where a certain cell or Bresenham path between two cells
// are supposed to be free of obstacles.

/** @param {!Array<number>} pos
    @param {string} reason
    check for invalid blocked cell */
World.World.prototype.playfield_check_pos = function(pos, reason) {
    if(!PLAYFIELD_DEBUG) { return; }
    if(this.astar_map.is_blocked(vec_floor(pos))) {
        console.log(reason+': invalid blocked cell! '+pos[0].toString()+','+pos[1].toString());
    }
}

/** check for invalid path (containing blocked cells)
    @param {!Array<!Array<number>>} path
    @param {string} reason */
World.World.prototype.playfield_check_path = function(path, reason) {
    if(!PLAYFIELD_DEBUG) { return; }
    for(var i = 0; i < path.length; i++) {
        var error = null;
        if(this.astar_map.is_blocked(vec_floor(path[i]))) {
            error = 'blocked cell in path! cell i='+i.toString()+': '+path[i][0].toString()+','+path[i][1].toString();
        } else if(i >= 1 && vec_distance(vec_floor(path[i-1]), vec_floor(path[i])) > 1 && !this.astar_map.linear_path_is_clear(vec_floor(path[i-1]), vec_floor(path[i]))) {
            error ='blocked jump in path! cell i='+(i-1).toString()+'-'+i.toString()+': '+path[i-1][0].toString()+','+path[i-1][1].toString()+'-'+path[i][0].toString()+','+path[i][1].toString();
        }
        if(error) {
            console.log(reason+': '+error);
            console.log(path);
            return;
        }
    }
};
