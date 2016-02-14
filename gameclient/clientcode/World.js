goog.provide('World');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('Citizens');
goog.require('GameTypes');
goog.require('GameObjectCollection');

/** Encapsulates the renderable/simulatable "world"
    @constructor
    @param {Base.Base|null} base
    @param {GameObjectCollection.GameObjectCollection|null} objects
*/
World.World = function(base, objects) {
    /** @type {Base.Base|null} */
    this.base = base;

    /** @type {GameObjectCollection.GameObjectCollection|null} */
    this.objects = objects;

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
