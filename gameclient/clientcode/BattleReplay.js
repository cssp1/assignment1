goog.provide('BattleReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('World');
goog.require('SPFX'); // only for item usage display - move out of here?
goog.require('ItemDisplay'); // only for item usage display - move out of here?
goog.require('goog.array');
goog.require('goog.object');

BattleReplay.invoke = function(log) {
    if(!log || log.length < 1 || log[0]['event_name'] !== '3820_battle_start' ||
       !log[0]['base'] || !log[0]['base_objects']) {
        throw Error('invalid battle log');
    }

    var props_3820 = log[0];

    var base = new Base.Base(props_3820['base_id'], props_3820['base']);
    var objects = [];
    goog.array.forEach(props_3820['base_objects'], function(state) {
        var obj = create_object(state, false);
        objects.push(obj);
    });

    // 3900_unit_exists always comes in one big block
    goog.array.forEach(log, function(event) {
        if(event['event_name'] === '3900_unit_exists') {
            if(goog.array.find(objects, function(x) { return x.id === event['obj_id']; }) !== null) { return; } // already in object list
            if(!('state' in event)) { throw Error('incompatible battle log: no state in 3900_unit_exists'); }
            var obj = create_object(event['state'], false);
            objects.push(obj);
        }
    });

    var world = new World.World(base, objects, false);
    session.push_world(world);
};

/** RECORDER
    @constructor @struct
    @param {!World.World} world
*/
BattleReplay.Recorder = function(world) {
    this.world = world;
    this.snapshots = [];
    this.listen_keys = {};
    this.diff_snap = null;
};
BattleReplay.Recorder.prototype.start = function() {
    if('before_control' in this.listen_keys) { throw Error('already started'); }

    // need to grab objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys['before_control'] = this.world.listen('before_control', this.before_control, false, this);
    this.listen_keys['before_damage_effects'] = this.world.listen('before_damage_effects', this.before_damage_effects, false, this);
    this.listen_keys['after_damage_effects'] = this.world.listen('after_damage_effects', this.after_damage_effects, false, this);
};
/** @private
    @param {string} reason */
BattleReplay.Recorder.prototype.compare_snapshots = function(reason) {
    if(this.diff_snap) {
        var new_snap = this.world.objects.serialize();
        console.log(reason +' diffs:');
        console.log(json_diff(this.diff_snap, new_snap));
        this.diff_snap = new_snap;
    }
};

BattleReplay.Recorder.prototype.before_control = function() {
    console.log('Recorded snapshot '+this.snapshots.length.toString());
    var snap = {'tick_time': this.world.last_tick_time,
                'objects': this.world.objects.serialize_incremental()};
    if(this.snapshots.length < 1) {
        // grab base on first snapshot only
        snap['base'] = this.world.base.serialize();
    }
    this.snapshots.push(snap);

    // uncomment this line to enable checking which fields mutated across the World control passes
    // XXX note: this breaks playback since the incremental serialization is stateful
    //this.diff_snap = this.world.objects.serialize();
};
BattleReplay.Recorder.prototype.before_damage_effects = function() {
    this.compare_snapshots('run_control');
    this.snapshots[this.snapshots.length-1]['combat_engine'] = this.world.combat_engine.serialize_incremental();
};
BattleReplay.Recorder.prototype.after_damage_effects = function() {
    this.compare_snapshots('damage effects');
};
BattleReplay.Recorder.prototype.stop = function() {
    goog.array.forEach(goog.object.getKeys(this.listen_keys), function(k) {
        this.world.unlistenByKey(this.listen_keys[k]);
        delete this.listen_keys[k];
    }, this);
    console.log('Recorder stopped with '+this.snapshots.length.toString()+' snapshots');
};

/** Return the final uploadable representation of the replay
    @return {string} native JS string, possibly including Unicode */
BattleReplay.Recorder.prototype.pack_for_upload = function() {
    var pack = {'version': gamedata['replay_version'] || 0,
                'snapshots': this.snapshots};
    // stringify, but don't UTF-8 encode yet
    return JSON.stringify(pack);
};

/** LINK FROM DOWNLOAD TO PLAYER
    @param {string} packed - native JS string, possibly including Unicode
    @return {BattleReplay.Player|null} - null if error */
BattleReplay.replay_from_download = function(packed) {
    var cur_ver = gamedata['replay_version'] || 0;
    var pack = JSON.parse(packed);
    if(pack['version'] !== cur_ver) {
        console.log('Replay version mismatch: '+pack['version'].toString()+' vs '+cur_ver.toString());
        return null;
    }
    if(pack['snapshots'].length < 1) {
        console.log('Replay had no snapshots');
        return null;
    }
    return new BattleReplay.Player(pack['snapshots']);
};

/** LINK FROM RECORDER TO PLAYER
    @param {!BattleReplay.Recorder} recorder */
BattleReplay.replay = function(recorder) {
    if(recorder.snapshots.length < 1) { throw Error('recorded not initialized'); }
    return new BattleReplay.Player(recorder.snapshots);
};

/** PLAYER
    @constructor @struct
    @param {!Array<!Object>} snapshots
*/
BattleReplay.Player = function(snapshots) {
    if(snapshots.length < 1) { throw Error('no snapshots'); }
    if(!('base' in snapshots[0])) { throw Error('first snapshot does not contain base'); }
    this.snapshots = snapshots;
    this.world = new World.World(new Base.Base(snapshots[0]['base']['base_id'], snapshots[0]['base']), [], false);
    this.world.ai_paused = true;
    //this.world.control_paused = true;
    // *throw away* damage effects added by our control code, in favor of the recorded ones
    this.world.combat_engine.accept_damage_effects = false;
    this.index = 0;
    // need to apply objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys = {'before_control': this.world.listen('before_control', this.before_control, false, this),
                        'before_damage_effects': this.world.listen('before_damage_effects', this.before_damage_effects, false, this)};
    console.log('Initialized replay with '+this.snapshots.length.toString()+' snapshots');
};
/** @return {number} */
BattleReplay.Player.prototype.num_ticks = function() { return this.snapshots.length; };
/** @return {number} */
BattleReplay.Player.prototype.cur_tick = function() { return this.index; };
/** @private */
BattleReplay.Player.prototype.before_control = function(event) {
    console.log('Applying snapshot '+this.index.toString()+' at tick '+this.world.combat_engine.cur_tick.get());
    if(this.index === 0) {
        this.world.objects.clear();
        this.world.combat_engine.clear_queued_damage_effects();
    }
    this.world.objects.apply_snapshot(this.snapshots[this.index]['objects']);
};
/** @private */
BattleReplay.Player.prototype.before_damage_effects = function(event) {
    var combat_snap = this.snapshots[this.index]['combat_engine'];

    // grab any item-usage events and post them to on-screen log
    if('item_log' in combat_snap) {
        goog.array.forEach(combat_snap['item_log'], function(event) {
            var spec = ItemDisplay.get_inventory_item_spec(event['item']['spec']);

            if('use_effect' in spec) {
                // check for null separately from checking if the effect exists so we can use a null effect
                // in the item spec to disable the game-wide effect
                if(spec['use_effect']) {
                    this.world.fxworld._add_visual_effect([0,0], 0, [0,1,0], this.world.fxworld.now_time(), spec['use_effect'], true, null);
                }
            } else if(gamedata['client']['vfx']['item_use']) {
                this.world.fxworld._add_visual_effect([0,0], 0, [0,1,0], this.world.fxworld.now_time(), gamedata['client']['vfx']['item_use'], true, null);
            }

            var ui_text = ItemDisplay.get_inventory_item_ui_name(spec, event['item']['level'] || 1, event['item']['stack'] || 1) + " " + gamedata['strings']['combat_messages']['activated'];
            if(event['target_pos']) {
                this.world.fxworld.add_under(new SPFX.ClickFeedback(event['target_pos'], [1,1,1,1], this.world.fxworld.now_time(), 0.15));
                this.world.fxworld.add(new SPFX.CombatText(event['target_pos'], 0,
                                                           ui_text,
                                                           [1,1,0.3],
                                                           this.world.fxworld.now_time(), 3.0,
                                                           { drop_shadow: true, font_size: 20, text_style: 'thick' }));
            } else {
                user_log.msg(ui_text, new SPUI.Color(1,1,0,1));
            }
        }, this);
    }

    this.world.combat_engine.apply_snapshot(combat_snap);
    this.index += 1;
    if(this.index >= this.snapshots.length) {
        if(!this.world.control_paused) { // pause at end
            this.world.control_paused = true;
        }
        this.index = 0;
    }
};
BattleReplay.Player.prototype.restart = function() {
    this.index = 0;
    if(this.world.control_paused) { // force a single-step to reset
        this.world.control_step = 1;
    }
};
