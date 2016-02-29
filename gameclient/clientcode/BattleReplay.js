goog.provide('BattleReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('Session');
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

/** @constructor @struct
    @param {!World.World} world */
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

BattleReplay.Recorder.prototype.before_control = function(event) {

    console.log('Snapshot '+this.snapshots.length.toString()+' at '+this.world.last_tick_time.toString());
    var snap = {'tick_time': this.world.last_tick_time,
                'objects': this.world.objects.serialize_incremental()};
    if(this.snapshots.length < 1) {
        snap['base'] = this.world.base.serialize();
    }
    this.snapshots.push(snap);

    // uncomment this line to enable checking which fields mutated across the World control passes
    // XXX note: this breaks playback since the incremental serialization is stateful
    //this.diff_snap = this.world.objects.serialize();
};
BattleReplay.Recorder.prototype.before_damage_effects = function(event) {
    this.compare_snapshots('run_control');

    this.snapshots[this.snapshots.length-1]['combat_engine'] = this.world.combat_engine.serialize_incremental();
};
BattleReplay.Recorder.prototype.after_damage_effects = function(event) {
    this.compare_snapshots('damage effects');
};

BattleReplay.Recorder.prototype.stop = function() {
    goog.array.forEach(goog.object.getKeys(this.listen_keys), function(k) {
        this.world.unlistenByKey(this.listen_keys[k]);
        delete this.listen_keys[k];
    }, this);
    console.log('Recorder stopped with '+this.snapshots.length.toString()+' snapshots');
};

/** @param {!BattleReplay.Recorder} recorder */
BattleReplay.replay = function(recorder) {
    if(recorder.snapshots.length < 1) { throw Error('recorded not initialized'); }
    return new BattleReplay.Player(recorder.snapshots);
};

/** @constructor @struct
    @param {!Array<!Object>} snapshots */
BattleReplay.Player = function(snapshots) {
    if(snapshots.length < 1) { throw Error('no snapshots'); }
    if(!('base' in snapshots[0])) { throw Error('first snapshot does not contain base'); }
    this.snapshots = snapshots;
    this.world = new World.World(new Base.Base(snapshots[0]['base']['base_id'], snapshots[0]['base']), [], false);
    //this.world.ai_paused = true;
    //this.world.control_paused = true;
    this.index = 0;

    // need to apply objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys = {'before_control': this.world.listen('before_control', this.before_control, false, this),
                        'before_damage_effects': this.world.listen('before_damage_effects', this.before_damage_effects, false, this)};
};
BattleReplay.Player.prototype.before_control = function(event) {
    console.log('Applying snapshot '+this.index.toString()+' at '+this.world.last_tick_time.toString());
    if(this.index === 0) {
        this.world.objects.clear();
    }
    this.world.objects.apply_snapshot(this.snapshots[this.index]['objects']);

    // *throw away* damage effects added by our control code, in favor of the recorded ones
    this.world.combat_engine.accept_damage_effects = false;
};
BattleReplay.Player.prototype.before_damage_effects = function(event) {
    this.world.combat_engine.accept_damage_effects = true;
    this.world.combat_engine.apply_snapshot(this.snapshots[this.index]['combat_engine']);
    this.index += 1;
    if(this.index >= this.snapshots.length) {
        this.index = 0;
    }
};
