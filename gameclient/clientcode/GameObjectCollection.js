goog.provide('GameObjectCollection');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('GameTypes');

/** GameObjectCollection (client-side version of server's ObjectCollection)

    Note: unlike in the server (where ObjectCollection assigns id numbers), in the client we assume
    that incoming objects added to the collection already have their id fields set (usually by receive_state()).

    We manually set ids of deleted objects to -1 so that any other reference-holders can know that the
    object isn't valid anymore.

    @constructor */
GameObjectCollection.GameObjectCollection = function() {
    /** @type {!Object<!GameObjectId, !GameObject>} */
    this.objects = {};
}

/** @param {!GameObject} obj */
GameObjectCollection.GameObjectCollection.prototype.add_object = function(obj) { this.objects[obj.id] = obj; };
/** @param {!GameObjectId} id
    @return {boolean} */
GameObjectCollection.GameObjectCollection.prototype.has_object = function(id) { return (id in this.objects); };
/** @param {!GameObjectId} id
    @return {!GameObject} */
GameObjectCollection.GameObjectCollection.prototype.get_object = function(id) { return this.objects[id]; };
/** @param {!GameObject} obj */
GameObjectCollection.GameObjectCollection.prototype.rem_object = function(obj) {
    delete this.objects[obj.id];
    obj.id = GameObject.DEAD_ID;
};
GameObjectCollection.GameObjectCollection.prototype.clear = function() {
    for(var id in this.objects) {
        this.objects[id].id = GameObject.DEAD_ID;
    }
    this.objects = {};
};

/** @param {function(this: T, !GameObject, !GameObjectId=) : ?} func
    @param {T=} opt_obj
    @suppress {reportUnknownTypes}
    @template T */
GameObjectCollection.GameObjectCollection.prototype.for_each = function(func, opt_obj) {
    for(var id in this.objects) {
        func.call(opt_obj, this.objects[id], id);
    }
};
