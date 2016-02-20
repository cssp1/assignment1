goog.provide('BattleReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('GameObjectCollection');
goog.require('Session');

BattleReplay.invoke = function(log) {
    if(!log || log.length < 1 || log[0]['event_name'] !== '3820_battle_start' ||
       !log[0]['base'] || !log[0]['base_objects']) {
        throw Error('invalid battle log');
    }

    var props_3820 = log[0];

    var base = new Base.Base(props_3820['base_id'], props_3820['base']);
    var objects = new GameObjectCollection.GameObjectCollection();
    goog.array.forEach(props_3820['base_objects'], function(state) {
        var obj = create_object(state, false);
        objects.add_object(obj);
    });

    // 3900_unit_exists always comes in one big block
    goog.array.forEach(log, function(event) {
        if(event['event_name'] === '3900_unit_exists') {
            if(objects.has_object(event['obj_id'])) { return; } // already in base
            if(!('state' in event)) { throw Error('incompatible battle log: no state in 3900_unit_exists'); }
            var obj = create_object(event['state'], false);
            objects.add_object(obj);
        }
    });

    var world = new World.World(base, objects, false);
    session.push_world(world);
};
