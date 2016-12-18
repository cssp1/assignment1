goog.provide('GameObjectCollection');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('GameTypes');
goog.require('goog.array');
goog.require('goog.object');
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

/** @constructor @struct
    @extends {goog.events.Event}
    @param {string} type
    @param {Object} target
    @param {!GameObject} obj */
GameObjectCollection.RemovedEvent = function(type, target, obj) {
    goog.base(this, type, target);
    this.obj = obj;
};
goog.inherits(GameObjectCollection.RemovedEvent, goog.events.Event);

/** GameObjectCollection (client-side version of server's ObjectCollection)

    Note: unlike in the server (where ObjectCollection assigns id numbers), in the client we assume
    that incoming objects added to the collection already have their id fields set (usually by receive_state()).

    We manually set ids of deleted objects to -1 so that any other reference-holders can know that the
    object isn't valid anymore.

    @constructor @struct
    @implements {GameTypes.IIncrementallySerializable}
    @extends {goog.events.EventTarget}
*/
GameObjectCollection.GameObjectCollection = function() {
    goog.base(this);

    /** @type {!Object<!GameObjectId, !GameObject>} */
    this.objects = {};

    // for incremental serialization only
    /** @type {!Object<!GameObjectId, boolean>} */
    this.dirty_removed = {};
    /** @type {!Object<!GameObjectId, boolean>} */
    this.dirty_added = {};
}
goog.inherits(GameObjectCollection.GameObjectCollection, goog.events.EventTarget);

/** @param {!GameObject} obj */
GameObjectCollection.GameObjectCollection.prototype.add_object = function(obj) {
    if(this.has_object(obj.id)) { throw Error('double-added object '+obj.id); }
    this.objects[obj.id] = obj;
    this.dispatchEvent(new GameObjectCollection.AddedEvent('added', this, obj));

    if(obj.id in this.dirty_removed) {
        // XXX will this de-synchronize? the object is going to forget which part of its state is dirty...
        delete this.dirty_removed[obj.id];
    } else if(!(obj.id in this.dirty_added)) {
        this.dirty_added[obj.id] = true;
    }
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
    var prev_id = obj.id;
    this.dispatchEvent(new GameObjectCollection.RemovedEvent('removed', this, obj));
    delete this.objects[obj.id];
    obj.id = GameObject.DEAD_ID;

    if(!(prev_id in this.dirty_removed)) {
        this.dirty_removed[prev_id] = true;
    }
    if(prev_id in this.dirty_added) {
        delete this.dirty_added[prev_id];
    }
};
GameObjectCollection.GameObjectCollection.prototype.clear = function() {
    goog.array.forEach(goog.object.getValues(this.objects), function(obj) {
        this.rem_object(obj);
    }, this);
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
    var ret = {'full':{}};
    for(var id in this.objects) {
        ret['full'][id] = this.objects[id].serialize();
    }
    return ret;
};

/** @override */
GameObjectCollection.GameObjectCollection.prototype.serialize_incremental = function() {
    var ret = {};
    var snap_removed = goog.object.getKeys(this.dirty_removed); // ids only
    if(snap_removed.length > 0) {
        ret['removed'] = snap_removed;
    }
    var snap_added = goog.object.map(this.dirty_added, function(_, /** GameObjectId */ id) { // full state
        return this.objects[id].serialize_incremental(); // assumes this is its first serialization!
    }, this);
    if(goog.object.getCount(snap_added) > 0) {
        ret['added'] = snap_added;
    }
    for(var id in this.objects) {
        if(id in this.dirty_added) { continue; } // taken care of by addition
        var mutation = this.objects[id].serialize_incremental();
        if(mutation) {
            if(!('changed' in ret)) { ret['changed'] = {}; }
            ret['changed'][id] = mutation;
        }
    }
    this.dirty_removed = {};
    this.dirty_added = {};
    return ret;
};

/** @override */
GameObjectCollection.GameObjectCollection.prototype.apply_snapshot = function(snap) {
    if('full' in snap) { // complete replacement
        /** @type {!Object<!GameObjectId, !GameObject>} */
        var new_objects = {};
        /** @type {!Array<!GameObject>} */
        var added_objects = [];
        /** @type {!Array<!GameObject>} */
        var removed_objects = [];

        goog.object.forEach(snap['full'], function(/** !Object<string,?> */ s, /** string */ id) {
            var obj;
            if(id in this.objects) {
                // reuse reference
                obj = this.objects[id];
                obj.apply_snapshot(s);
            } else {
                obj = GameObject.unserialize(s);
                added_objects.push(obj);
            }
            new_objects[id] = obj;
        }, this);
        goog.object.forEach(this.objects, function(/** !GameObject */ obj, /** string */ id) {
            if(!(id in snap['full'])) {
                removed_objects.push(obj);
            }
        }, this);

        this.objects = new_objects;
        goog.array.forEach(removed_objects, function(obj) {
            this.dispatchEvent(new GameObjectCollection.RemovedEvent('removed', this, obj));
            obj.id = GameObject.DEAD_ID;
        }, this);
        goog.array.forEach(added_objects, function(obj) {
            this.dispatchEvent(new GameObjectCollection.AddedEvent('added', this, obj));
        }, this);

    } else { // incremental update
        if('removed' in snap) {
            goog.array.forEach(snap['removed'], function(/** string */ id) {
                if(!this.has_object(id)) {
                    console.log('attempt to remove nonexistent object! '+id);
                    return;
                }
                this.rem_object(this.objects[id]);
            }, this);
        }
        if('added' in snap) {
            goog.object.forEach(snap['added'], function(/** !Object<string,?> */ s, /** string */ id) {
                this.add_object(GameObject.unserialize(s));
            }, this);
        }
        if('changed' in snap) {
            goog.object.forEach(snap['changed'], function(/** !Object<string,?> */ s, /** string */ id) {
                if(!this.has_object(id)) {
                    console.log('attempt to change nonexistent object! '+id);
                    return;
                }
                var obj = this.objects[id];
                obj.apply_snapshot(s);
            }, this);
        }
    }
};
