goog.provide('BattleReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('Session');

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
    this.base_snapshot = null;
    this.snapshots = [];
    this.listen_key = null;


    this.replay_world = null;
    this.replay_i = 0;
};
BattleReplay.Recorder.prototype.start = function() {
    if(this.listen_key) { throw Error('already started'); }
    this.listen_key = this.world.listen('before_control', this.after_control, false, this);
    this.base_snapshot = this.world.base.serialize();
};
BattleReplay.Recorder.prototype.after_control = function(event) {
    this.snapshots.push(this.world.serialize());
};
BattleReplay.Recorder.prototype.stop = function() {
    if(this.listen_key) {
        this.world.unlistenByKey(this.listen_key);
        this.listen_key = null;
    }
};
BattleReplay.Recorder.prototype.replay = function() {
    if(this.snapshots.length < 1) { throw Error('no snapshots'); }
    var w = new World.World(new Base.Base(this.base_snapshot['base_id'], this.base_snapshot), [], false);
    this.replay_world = w;
    w.ai_paused = true;
    w.control_paused = true;
    session.push_world(w);
    this.replay_i = 0;
    this.replay_step();
};
BattleReplay.Recorder.prototype.replay_step = function() {
    this.replay_world.apply_snapshot(this.snapshots[this.replay_i]);
    this.replay_world.run_unit_ticks();
    this.replay_i += 1;
    if(this.replay_i >= this.snapshots.length) {
        this.replay_i = 0;
    }
};
