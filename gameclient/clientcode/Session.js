goog.provide('Session');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('GameTypes');
goog.require('GameObjectCollection');
goog.require('BattleReplay');
goog.require('Region');
goog.require('World');
goog.require('LootTable');
goog.require('goog.object');
goog.require('goog.array');

/** Game client/server session.
    Somewhat parallel to server's Session class (same-named members have same behavior).

    However, currently this has a bunch of global state
    that should be refactored out into World and CombatEngine.

    @constructor @struct */
Session.Session = function() {
    this.connect_time = -1; // set to client_time upon receiving first SERVER_HELLO message
    this.client_hello_packet = null; // keep our CLIENT_HELLO message in case we need to re-transmit it
    this.server_hello_ended = false; // flag is set once we receive END_SERVER_HELLO

    this.user_id = spin_user_id; // player's SpinPunch user ID
    this.session_id = spin_session_id; // unique ID for this connection to the server
    this.alliance_id = -1; // player's current alliance ID, <= 0 is invalid
    this.alliance_membership = null; // player's current alliance membership info (alliance_members row), null for no membership
    /** @type {Region.Region|null} */
    this.region = null; // world map region we are connected to

    this.minefield_tags_by_obj_id = {}; // mapping from obj_id to tag of player minefield buildings, used for GUI purposes only
    this.minefield_tags_by_tag = {}; // mapping from tag to obj_id
    this.factory_tags_by_obj_id = {}; // GUI purposes only - identify unique factories (same as minefield tags above)
    this.factory_tags_by_tag = {};
    this.viewing_user_id = null; // SpinPunch user ID of the person whose base we are looking at
    this.viewing_player_home_base_id = null; // base_id of home base for viewing_player
    this.viewing_player_home_region = null; // home_region for viewing_player
    this.viewing_base = null; // base we are looking at
    this.viewing_ai = false; // whether we are viewing an AI player
    this.viewing_friend = null; // reference to member of player.friends we are looking at (may be null for AI or non-friends)
    this.ui_name = ''; // User-visible name of the person whose base we are looking at
    this.home_base = 1; // true if we are looking at our own base
    this.has_attacked = false; // true if there has been an attack in the current session
    this.has_deployed = false; // true if there has been an attack AND player has deployed at least one unit
    this.deploy_time = -1; // server_time at which has_deployed became 1

    /** @type {BattleReplay.Recorder|null} current recorder in use */
    this.replay_recorder = null;

    this.change_time = -1; // client_time at which last SESSION_CHANGE was received (for debugging only)
    this.enable_combat_resource_bars = true; // used by the tutorial to hide combat resource bars (via ENABLE_COMBAT_RESOURCE_BARS consequent)
    this.enable_dialog_completion_buttons = true; // used by the tutorial to disable completions button when player shouldn't press them (via ENABLE_DIALOG_COMPLETION consequent)
    this.surrender_pending = false; // true if player has pressed Surrender and we are waiting for the session change
    this.retreat_pending = -1; // client_time at which retreat will happen (between clicking "End Attack" and session change request)
    this.no_more_units = false; // true if all of the player's units have been destroyed and we need to check the battle outcome next time the damage effect queue empties
    this.attack_finish_time = -1; // server_time at which attack timer runs out
    this.incoming_attack_time = -1; // server_time at which AI units will spawn
    this.incoming_attack_wave_time = -1; // time at which next wave should be spawned
    this.incoming_attack_wave_pending = false; // whether we sent next_ai_attack_wave yet
    this.incoming_attack_units = []; // list of waves, where each wave is a map (specname->quantity) of AI units that will spawn
    this.incoming_attack_direction = null; // key in gamedata/ai_attacks/directions
    this.incoming_attacker_name = ''; // user-visible name of the attacking AI
    this.incoming_attack_units_total = 0; // number of AI units involved in current attack (including secteam units spawned during battle)
    this.incoming_attack_units_destroyed = 0; // number of AI units destroyed during current attack (including secteam units spawned during battle)
    this.battle_outcome_sync_marker = Synchronizer.INIT; // synchronizer to make sure server is up to date before client tries to end battle
    this.battle_outcome_dirty = false; // whether we need to check for win/loss - always update sync_marker when setting true
    this.deployed_unit_space = 0; // how much "space" worth of units has been deployed into battle
    this.weak_zombie_warned = false; // whether or not we have already shown the "you are about to deploy a zombie unit" warning
    this.manufacture_overflow_warned = false; // whether we have already shown the "base defenders full, new units diverted to reserves" message
    this.buy_gamebucks_sku_highlight_shown = false; // whether we have already shown the SKU highlight upon Buy Gamebucks dialog open
    this.is_alt_account = false; // whether we are viewing a base owned by a known alt account
    this.quarry_harvest_sync_marker = Synchronizer.INIT; // synchronizer used for showing Loading... while harvesting quarries
    this.deployable_squads = [];
    this.defending_squads = [];

    // pre/post_deploy_units are dictionaries of "army_unit" structures, indexed by obj_id
    // {'123456': {'obj_id': '123456', 'spec': 'asdf', 'level': 1},
    //  'DONATED-1234': {'obj_id': 'DONATED-1234', 'source':'DONATED', 'spec': 'asdf', 'stack': 2}}
    this.pre_deploy_units = {}; // units that are "loaded" into the cursor to be deployed
    this.post_deploy_units = {}; // units that are already deployed

    this.loot = {}; // exact copy of server's     this.loot
    this.last_loot = {}; // previous value of     this.loot, for graphical ticker effect only
    this.last_looted_uncapped = {}; // previous value of     this.res_looter['looted_uncapped'], for graphical ticker effect only

    this.res_looter = null; // raw JSON ResLooter state sent from server; drives client GUI display

    this.pvp_balance = null; // which party is favored in PvP
    this.ladder_state = null; // identical to     this.ladder_state in server
    this.home_warehouse_busy = false; // business state of warehouse upon session change
    this.home_equip_items = []; // list of equipped items from home that we can use during combat
    this.last_map_dialog_state = null; // stash state of map dialog when leaving home base, so we can come back to it

    this.viewing_lock_state = 0; // lock state of (foreign) base being viewed
    this.viewing_isolate_pvp = 0; // isolate_pvp flag of base being viewed
    this.repeat_attack_cooldown_expire = 0; // repeat attack cooldown expiration time of base being viewed

    /** @type {!Array<!World.World>}
        Bottom-most element is the "real" world, replays push a "virtual" world on top */
    this.world_stack = [];
};

/** @param {!Base.Base} new_base
    @param {boolean} enable_citizens */
Session.Session.prototype.set_viewing_base = function(new_base, enable_citizens) {
    this.viewing_base = new_base;
    // reinitialize world stack
    goog.array.forEach(this.world_stack, function(world) { world.dispose(); });

    var world = new World.World(this.viewing_base, [], enable_citizens);
    this.world_stack = [world];

    world.listen('after_damage_effects', this.after_real_world_damage_effects, false, this);
    world.listen('object_added', this.on_real_world_object_added, false, this);
    world.listen('object_removed', this.on_real_world_object_removed, false, this);

    this.minefield_tags_by_obj_id = {};
    this.minefield_tags_by_tag = {};
    this.factory_tags_by_obj_id = {};
    this.factory_tags_by_tag = {};
};
/** @param {!World.World} new_world */
Session.Session.prototype.push_world = function(new_world) { return this.world_stack.push(new_world); };
/** Get rid of any worlds pushed on top of the real one */
Session.Session.prototype.pop_to_real_world = function() {
    while(this.world_stack.length > 1) {
        this.world_stack.pop();
    }
};

/** @return {!World.World} world at top of stack that should be drawn */
Session.Session.prototype.get_draw_world = function() {
    if(this.world_stack.length < 1) { throw Error('no world'); }
    return this.world_stack[this.world_stack.length-1];
};

/** @return {!World.World} the "real" world the player is connected to
    @const */
Session.Session.prototype.get_real_world = function() {
    if(this.world_stack.length < 1) { throw Error('no world'); }
    return this.world_stack[0];
};

/** @return {boolean}*/
Session.Session.prototype.has_world = function() { return (this.world_stack.length >= 1); };

/** Checks if we're looking at something other than the real world
    @return {boolean} */
Session.Session.prototype.is_replay = function() { return (this.world_stack.length >= 2); };


Session.Session.prototype.incoming_attack_pending = function() { return (this.incoming_attack_time > server_time); };
Session.Session.prototype.connected = function() { return this.connect_time > 0; };
Session.Session.prototype.is_remote_base = function() { return (this.viewing_player_home_base_id !== this.viewing_base.base_id); };
Session.Session.prototype.is_quarry = function() { return (this.viewing_base.base_type === 'quarry'); };
Session.Session.prototype.is_squad = function() { return (this.viewing_base.base_type === 'squad'); };
Session.Session.prototype.is_ladder_battle = function() { return !!this.ladder_state; };

Session.Session.prototype.is_in_alliance = function() { return (this.alliance_id > 0); };

Session.Session.prototype.get_my_alliance_role_info = function() {
    if(this.alliance_membership) {
        var info = AllianceCache.query_info_sync(this.alliance_membership['alliance_id']);
        if(info) {
            var my_role = this.alliance_membership['role'] || 0;
            return info['roles'][my_role.toString()];
        }
    }
    return null;
};
Session.Session.prototype.check_alliance_perm = function(want_perm) {
    var role_info = this.get_my_alliance_role_info();
    if(role_info) {
        return goog.array.contains(role_info['perms'], want_perm);
    }
    return false;
};

// returns true if using new map/squads deployment, instead of conventional deploy-your-base-defenders method
Session.Session.prototype.using_squad_deployment = function() {
    return (this.deployable_squads.length != 1 || this.deployable_squads[0] != SQUAD_IDS.BASE_DEFENDERS);
};

Session.Session.prototype.foreach_deployable_unit = function(func, opt_this) {
    goog.object.forEach(player.my_army, function(obj) {
        // squad must be in deployable_squads
        if(!goog.array.contains(this.deployable_squads, (obj['squad_id']||0))) { return; }

        // check that the unit is not already deployed
        if(obj['obj_id'] in this.post_deploy_units) { return; }

        // check that the unit is not dead
        var curmax = army_unit_hp(obj);
        if(curmax[0] <= 0) { return; }

        // check that the unit satisfies climate restrictions
        var spec = gamedata['units'][obj['spec']];
        if(!this.viewing_base.climate.can_deploy_unit_of_spec(spec)) { return; }

        func.call(opt_this, obj);
    }, this);
};

// return number of deployable units (optionally, that satisfy filter_func)
/** @param {function(Object): boolean=} filter_func */
Session.Session.prototype.count_deployable_units = function(filter_func) {
    var count = 0;
    this.foreach_deployable_unit(function(obj) {
        if(filter_func && !filter_func(obj)) { return; }
        count += 1;
    }, this);
    return count;
};
Session.Session.prototype.count_deployable_units_of_spec = function(specname) {
    return this.count_deployable_units(function(obj) { return (obj['spec'] === specname); });
};

// note: checking obj['source'] == 'donated' might make sense if we ever start considering donated units as part of space limits again

// count units of this type loaded into the deployment cursor
Session.Session.prototype.count_pre_deploy_units_of_spec = function(specname) {
    return goog.object.getCount(goog.object.filter(this.pre_deploy_units, function(obj) { return obj['spec'] == specname && obj['source'] !== 'donated'; }));
};

Session.Session.prototype.count_pre_deploy_donated_units = function() {
    return goog.object.getCount(goog.object.filter(this.pre_deploy_units, function(obj) { return obj['source'] === 'donated'; }));
};

// count units of this type that have been deployed on the battlefield
Session.Session.prototype.count_post_deploy_units_of_spec = function(specname) {
    return goog.object.getCount(goog.object.filter(this.post_deploy_units, function(obj) { return obj['spec'] == specname && obj['source'] !== 'donated'; }));
};
Session.Session.prototype.count_post_deploy_units = function() {
    return goog.object.getCount(goog.object.filter(this.post_deploy_units, function(obj) { return obj['source'] !== 'donated'; }));
};

// return [army_unit, zombie_status] representing next (healthiest undeployed) unit we can deploy of a certain spec
Session.Session.prototype.get_next_deployable_unit = function(specname) {
    var unit = null, highest_hp = -1, is_zombie = false;
    this.foreach_deployable_unit(function (obj) {
        if(obj['spec'] != specname) { return; }
        if(obj['obj_id'] in this.post_deploy_units ||
           obj['obj_id'] in this.pre_deploy_units) { return; }
        var obj_hp = army_unit_hp(obj)[0];
        if(obj_hp > highest_hp) {
            highest_hp = obj_hp;
            unit = obj;
        }
    }, this);
    if(!unit) { throw Error('get_next_deployable_unit('+specname+') failed'); }
    if(unit && gamedata['zombie_debuff_threshold'] >= 0) {
        var curmax = army_unit_hp(unit);
        var ratio = curmax[0]/Math.max(curmax[1],1);
        if(ratio < gamedata['zombie_debuff_threshold']) { is_zombie = true; }
    }
    return [unit, is_zombie];
};

// return the army_unit of the weakest (non-donated) unit of this spec in pre-deploy, for canceling unit deployment one-by-one
Session.Session.prototype.get_weakest_pre_deploy_unit = function(specname) {
    var weakest = null, lowest_hp = Infinity;
    for(var obj_id in this.pre_deploy_units) {
        var obj = this.pre_deploy_units[obj_id];
        if(obj['spec'] == specname && obj['source'] !== 'donated') {
            var hp = army_unit_hp(obj)[0];
            if(hp < lowest_hp) {
                lowest_hp = hp;
                weakest = obj;
            }
        }
    }
    return weakest;
};

Session.Session.prototype.quarry_victory_satisfied = function() {
    var survivors = this.for_each_real_object(function(obj) {
        if(obj.team === 'enemy') {
            if(obj.is_building() && !obj.is_destroyed() && obj.spec['history_category'] == 'turrets') {
                return true;
            }
            if(obj.is_mobile() && !obj.is_destroyed()) {
                return true;
            }
        }
        return false;
    }, this);
    return !survivors;
};

/** @param {!World.ObjectAddedEvent} event */
Session.Session.prototype.on_real_world_object_added = function(event) {
    var obj = event.obj;

    // when spawning new temporary units (e.g. security teams) during an AI attack, add those to the count of attackers so the bookkeeping works out accurately
    if(this.home_base && this.attack_finish_time > server_time && obj.team == 'enemy' && obj.is_mobile() && obj.is_temporary()) {
        this.incoming_attack_units_total += 1;
    }

    // add to minefield tag index
    // XXX does this need to remain sorted?
    if(obj.is_building() && obj.team == 'player') {
        if(obj.is_minefield()) {
            var dims = gamedata['dialogs']['crafting_dialog_status_mines']['widgets']['mine_slot']['array'];
            var count = goog.object.getCount(this.minefield_tags_by_obj_id);
            var rownum = Math.floor(count/dims[0]);
            var collet = count - rownum*dims[0];
            var tag = String.fromCharCode('A'.charCodeAt(0) + collet)+(rownum+1).toString();
            this.minefield_tags_by_obj_id[obj.id] = tag;
            this.minefield_tags_by_tag[tag] = obj.id;
        } else if(obj.is_factory()) {
            var count = goog.object.getCount(this.factory_tags_by_obj_id[obj.spec['name']] || {});
            var tag = String.fromCharCode('A'.charCodeAt(0) + count).toString();
            if(!(obj.spec['name'] in this.factory_tags_by_obj_id)) {
                this.factory_tags_by_obj_id[obj.spec['name']] = {};
                this.factory_tags_by_tag[obj.spec['name']] = {};
            }
            this.factory_tags_by_obj_id[obj.spec['name']][obj.id] = tag;
            this.factory_tags_by_tag[obj.spec['name']][tag] = obj.id;
        }
    }
};
/** @param {!World.ObjectRemovedEvent} event */
Session.Session.prototype.on_real_world_object_removed = function(event) {
    this.set_battle_outcome_dirty();
};

Session.Session.prototype.clear_building_idle_state_caches = function() {
    this.for_each_real_object(function(obj) {
        if(obj.is_building()) { obj.idle_state_cache = null; }
    }, this);
};

// flag the session so that, after the server catches up, we'll check for battle end at next opportunity
// should be called after any state change that could change the result of calculate_battle_outcome()
Session.Session.prototype.set_battle_outcome_dirty = function() {
    // delay checking for battle outcome until server acknowledges this
    this.battle_outcome_sync_marker = synchronizer.request_sync();
    this.battle_outcome_dirty = true;
};

/** check for earliest forced expiration time of an inventory item by spec
 @param {!Object} spec
 @param {number=} prev_expire_time
 @param {number=} ref_time
 @return {number} */
Session.Session.prototype.get_item_spec_forced_expiration = function(spec, prev_expire_time, ref_time) {
    var expire_time = (prev_expire_time > 0 ? prev_expire_time : -1);
    if(!ref_time || ref_time <= 0) { ref_time = player.get_absolute_time(); }
    if('force_duration' in spec) {
        var force_duration = eval_cond_or_literal(spec['force_duration'], player, null);
        if(force_duration > 0) {
            expire_time = (expire_time > 0) ? Math.min(force_duration+ref_time, expire_time) : (force_duration+ref_time);
        }
    }
    if('force_expire_by' in spec) {
        var expire_by_data = eval_cond_or_literal(spec['force_expire_by'], player, null);
        var expire_by;
        if(typeof expire_by_data === 'object') { // event-driven
            var neg_time_to_end = player.get_event_time(expire_by_data['event_kind'] || 'current_event',
                                                        expire_by_data['event_name'] || null, 'end',
                                                        true, ref_time - player.get_absolute_time());
            if(neg_time_to_end === null) { // event not active
                expire_by = -1;
            } else {
                expire_by = ref_time + (-neg_time_to_end);
            }
        } else { // literal int
            expire_by = expire_by_data;
        }
        if(expire_by > 0) {
            expire_time = (expire_time > 0) ? Math.min(expire_by, expire_time) : expire_by;
        }
    }
    return expire_time;
};

/** Query a loot table for what items you'd get (just for GUI purposes, has nothing to do with actual looting mechanics).
    @return {!LootTable.Result} */
Session.Session.prototype.get_loot_items = function(player, loot_table) {
    return LootTable.get_loot(gamedata['loot_tables_client'], loot_table,
                              (function (_player) { return function(pred) {
                                  return read_predicate(pred).is_satisfied(_player, null);
                              }; })(player));
};

// note: to preserve balance, attack_finish_time might have to be adjusted according to the player_combat_time_scale!
Session.Session.prototype.set_attack_finish_time = function(new_time) {
    this.attack_finish_time = new_time;
};

// display session.attack_finish_time, but in units of seconds unaffected by player_combat_time_scale
Session.Session.prototype.ui_attack_time_togo = function() {
    if(this.attack_finish_time <= server_time) {
        return 0;
    }
    return this.attack_finish_time - server_time;
};

Session.Session.prototype.persist_debris = function() {
    if(this.has_deployed) {
        this.get_real_world().persist_debris();
    }
};

Session.Session.prototype.after_real_world_damage_effects = function(event) {
    var world = this.get_real_world();
    var any_left = world.combat_engine.has_queued_effects();
    if(!any_left && this.no_more_units) {
        this.no_more_units = false;
        this.set_battle_outcome_dirty();
    }
    flush_dirty_objects({urgent_only:true, skip_check:true});
};

/** @param {function(this: T, !GameObject, !GameObjectId=) : (R|null|undefined)} func
    @param {T=} opt_obj
    @return {R|null|undefined}
    @suppress {reportUnknownTypes}
    @template T, R */
Session.Session.prototype.for_each_real_object = function(func, opt_obj) {
    return this.get_real_world().objects.for_each(func, opt_obj);
};

/** @return {boolean} */
Session.Session.prototype.is_recording = function() { return this.replay_recorder !== null; };

/** @param {string} token for the upload
    @param {number} end_client_time - cut off recording at this client_time (-1 for unlimited) */
Session.Session.prototype.start_recording = function(token, end_client_time) {
    if((end_client_time > 0 && end_client_time < client_time) ||
       !read_predicate(gamedata['client']['enable_replay_recording']).is_satisfied(player, null)) { return; }
    this.replay_recorder = new BattleReplay.Recorder(this.get_real_world(), token, end_client_time);
    this.replay_recorder.start();
};
Session.Session.prototype.flush_recording = function() {
    this.replay_recorder.flush(false);
};
/** Stop and upload the end of the recording */
Session.Session.prototype.finish_and_upload_recording = function() {
    this.replay_recorder.stop();
    this.replay_recorder.finish();
    this.replay_recorder = null;
};
