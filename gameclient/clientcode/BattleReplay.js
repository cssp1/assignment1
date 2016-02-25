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
    // base snapshot is grabbed once at the start, since it won't change during the recording
    this.base_snapshot = null;
    this.snapshots = [];
    this.listen_keys = {};
};
BattleReplay.Recorder.prototype.start = function() {
    if('before_control' in this.listen_keys) { throw Error('already started'); }

    // need to grab objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys['before_control'] = this.world.listen('before_control', this.before_control, false, this);
    this.listen_keys['before_damage_effects'] = this.world.listen('before_damage_effects', this.before_damage_effects, false, this);
    this.base_snapshot = this.world.base.serialize();
};
BattleReplay.Recorder.prototype.before_control = function(event) {
    console.log('Snapshot '+this.snapshots.length.toString()+' at '+this.world.last_tick_time.toString());
    this.snapshots.push({'tick_time': this.world.last_tick_time,
                         'objects': this.world.objects.serialize()});
};
BattleReplay.Recorder.prototype.before_damage_effects = function(event) {
    this.snapshots[this.snapshots.length-1]['combat_engine'] = this.world.combat_engine.serialize();
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
    if(!recorder.base_snapshot || recorder.snapshots.length < 1) { throw Error('recorded not initialized'); }
    return new BattleReplay.Player(recorder.base_snapshot, recorder.snapshots);
};

/** @constructor @struct
    @param {!Object} base_snapshot
    @param {!Array<!Object>} snapshots */
BattleReplay.Player = function(base_snapshot, snapshots) {
    if(snapshots.length < 1) { throw Error('no snapshots'); }
    this.snapshots = snapshots;
    this.world = new World.World(new Base.Base(base_snapshot['base_id'], base_snapshot), [], false);
    //this.world.ai_paused = true;
    //this.world.control_paused = true;
    this.index = 0;

    // need to apply objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys = {'before_control': this.world.listen('before_control', this.before_control, false, this),
                        'before_damage_effects': this.world.listen('before_damage_effects', this.before_damage_effects, false, this)};
};
BattleReplay.Player.prototype.before_control = function(event) {
    this.world.objects.apply_snapshot(this.snapshots[this.index]['objects']);
};
BattleReplay.Player.prototype.before_damage_effects = function(event) {
    this.world.combat_engine.apply_snapshot(this.snapshots[this.index]['combat_engine']);
    this.index += 1;
    if(this.index >= this.snapshots.length) {
        this.index = 0;
    }
};
