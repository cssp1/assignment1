goog.provide('GameObjectCollection');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('GameTypes');
goog.require('goog.events.EventTarget');
goog.require('goog.events.Event');

/** @constructor @struct
    @extends {goog.events.Event}
    @param {string} type
    @param {Object} target
    @param {!GameObject} obj */
GameObjectCollection.AddedEvent = function(type, target, obj) {
    goog.base(this, type, target);
    this.obj = obj;
};
goog.inherits(GameObjectCollection.AddedEvent, goog.events.Event);

/** GameObjectCollection (client-side version of server's ObjectCollection)

    Note: unlike in the server (where ObjectCollection assigns id numbers), in the client we assume
    that incoming objects added to the collection already have their id fields set (usually by receive_state()).

    We manually set ids of deleted objects to -1 so that any other reference-holders can know that the
    object isn't valid anymore.

    @constructor @struct
    @implements {GameTypes.ISerializable}
    @extends {goog.events.EventTarget}
*/
GameObjectCollection.GameObjectCollection = function() {
    goog.base(this);

    /** @type {!Object<!GameObjectId, !GameObject>} */
    this.objects = {};
}
goog.inherits(GameObjectCollection.GameObjectCollection, goog.events.EventTarget);

/** @param {!GameObject} obj */
GameObjectCollection.GameObjectCollection.prototype.add_object = function(obj) {
    if(this.has_object(obj.id)) { throw Error('double-added object '+obj.id); }
    this.objects[obj.id] = obj;
    this.dispatchEvent(new GameObjectCollection.AddedEvent('added', this, obj));
};

/** @param {!GameObjectId} id
    @return {boolean} */
GameObjectCollection.GameObjectCollection.prototype.has_object = function(id) { return (id in this.objects); };
/** @param {GameObjectId|null} id
    @return {GameObject|null} */
GameObjectCollection.GameObjectCollection.prototype._get_object = function(id) { return this.objects[/** @type {string} */ (id)] || null; };
/** @param {!GameObjectId} id
    @return {!GameObject} */
GameObjectCollection.GameObjectCollection.prototype.get_object = function(id) {
    var ret = this.objects[id];
    if(!ret) { throw Error('object not found '+id); }
    return ret;
};
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

/** Return a randomly-permuted array of all our objects
    @param {function(this: T, !GameObject): boolean=} filter_func
    @param {T=} opt_obj
    @return {!Array<!GameObject>}
    @suppress {reportUnknownTypes}
    @template T */
GameObjectCollection.GameObjectCollection.prototype.get_random_permutation = function(filter_func, opt_obj) {
    var obj_list = [null];
    var i = 0;
    for(var id in this.objects) {
        var obj = this.objects[id];
        if(filter_func && !filter_func.call(opt_obj, obj)) {
            continue;
        }
        // See http://en.wikipedia.org/wiki/Fisher%E2%80%93Yates_shuffle
        var j = Math.floor(Math.random()*(i+1));
        obj_list[i] = obj_list[j];
        obj_list[j] = obj;
        i++;
    }
    return (obj_list[0] ? obj_list : []);
};

/** @param {function(this: T, !GameObject, !GameObjectId=) : (R|null)} func
    @param {T=} opt_obj
    @return {R|null}
    @suppress {reportUnknownTypes}
    @template T, R */
GameObjectCollection.GameObjectCollection.prototype.for_each = function(func, opt_obj) {
    for(var id in this.objects) {
        var ret = func.call(opt_obj, this.objects[id], id);
        if(ret) { return ret; }
    }
    return null;
};

/** @override */
GameObjectCollection.GameObjectCollection.prototype.serialize = function() {
    var ret = {};
    for(var id in this.objects) {
        ret[id] = this.objects[id].serialize();
    }
    return ret;
};

/** @override */
GameObjectCollection.GameObjectCollection.prototype.apply_snapshot = function(snap) {
    /** @type {!Object<!GameObjectId, !GameObject>} */
    var new_objects = {};
    goog.object.forEach(snap, function(/** !Object<string,?> */ s, /** string */ id) {
        var obj;
        if(id in this.objects) {
            // reuse reference
            obj = this.objects[id];
            obj.apply_snapshot(s);
        } else {
            obj = GameObject.unserialize(s);
        }
        new_objects[id] = obj;
    }, this);
    this.objects = new_objects;
};
