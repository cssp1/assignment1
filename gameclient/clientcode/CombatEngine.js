goog.provide('CombatEngine');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('GameTypes');
goog.require('goog.array');

// numeric types - eventually will need to become fixed-point

/** Scaling coefficient, like a damage_vs coefficient
    Assumed to be small, like 0-100, but need fractional precision
    @typedef {number} */
CombatEngine.Coeff;

/** 1D object position
    @typedef {number} */
CombatEngine.Pos;
CombatEngine.Pos = {};

/** @param {!CombatEngine.Pos} x
    @param {!CombatEngine.Pos} lo
    @param {!CombatEngine.Pos} hi
    @return {!CombatEngine.Pos} */
CombatEngine.Pos.clamp = function(x, lo, hi) {
    if(x < lo) {
        return lo;
    } else if(x > hi) {
        return hi;
    } else {
        return x;
    }
};

/** 2D object location
    @typedef {Array.<CombatEngine.Pos>} */
CombatEngine.Pos2D;
CombatEngine.Pos2D = {};

/** @param {!CombatEngine.Pos2D} a
    @param {!CombatEngine.Pos2D} b
    @return {!CombatEngine.Pos2D} */
CombatEngine.Pos2D.sub = function(a, b) {
    return [a[0]-b[0], a[1]-b[1]];
};

/** @constructor @struct
    @implements {GameTypes.ISerializable} */
CombatEngine.CombatEngine = function() {
    /** @type {!GameTypes.TickCount} */
    this.cur_tick = new GameTypes.TickCount(0);

    /** @type {number} hack for time-based effects */
    this.cur_client_time = 0;

    /** list of queued damage effects that should be applied at later times (possible optimization: use a priority queue)
        @private
        @type {Array.<!CombatEngine.DamageEffect>} */
    this.damage_effect_queue = [];
};

/** @override */
CombatEngine.CombatEngine.prototype.serialize = function() {
    return {'cur_tick': this.cur_tick.get(),
            'cur_client_time': this.cur_client_time,
            'damage_effect_queue': goog.array.map(this.damage_effect_queue, function(effect) { return effect.serialize(); }, this)};
};
/** @override */
CombatEngine.CombatEngine.prototype.apply_snapshot = function(snap) {
    this.cur_tick = new GameTypes.TickCount(snap['cur_tick']);
    this.cur_client_time = snap['cur_client_time'];
    this.damage_effect_queue = goog.array.map(snap['damage_effect_queue'], function(/** !Object<string,?> */ effect_snap) {
        return this.unserialize_damage_effect(effect_snap);
    }, this);
};

/** @param {!Object<string,?>} snap
    @return {!CombatEngine.DamageEffect} */
CombatEngine.CombatEngine.prototype.unserialize_damage_effect = function(snap) {
    if(snap['kind'] === 'KillDamageEffect') {
        return new CombatEngine.KillDamageEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['target_id']);
    } else if(snap['kind'] === 'TargetedDamageEffect') {
        return new CombatEngine.TargetedDamageEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['target_id'], snap['amount'], snap['vs_table']);
    } else if(snap['kind'] === 'TargetedAuraEffect') {
        return new CombatEngine.TargetedAuraEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['target_id'], snap['amount'], snap['aura_name'], snap['aura_duration'], snap['aura_range'], snap['vs_table'], snap['duration_vs_table']);
    } else if(snap['kind'] === 'AreaDamageEffect') {
        return new CombatEngine.AreaDamageEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['target_location'], snap['hit_ground'], snap['hit_air'], snap['radius'], snap['falloff'], snap['amount'], snap['vs_table'], snap['allow_ff']);
    } else if(snap['kind'] === 'AreaAuraEffect') {
        return new CombatEngine.AreaAuraEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['target_location'], snap['hit_ground'], snap['hit_air'], snap['radius'], snap['radius_rect'], snap['falloff'], snap['amount'], snap['aura_name'], snap['aura_duration'], snap['aura_range'], snap['vs_table'], snap['duration_vs_table'], snap['allow_ff']);
    } else {
        throw Error('unknown kind '+snap['kind']);
    }
};

// DamageEffects

/** @constructor @struct
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack - until SPFX can think in terms of ticks, have to use client_time instead of tick count for applicaiton
    @param {GameObjectId|null} source_id
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.DamageEffect = function(tick, client_time_hack, source_id, amount, vs_table) {
    this.tick = tick;
    this.client_time_hack = client_time_hack;
    this.source_id = source_id;
    this.amount = amount;
    this.vs_table = vs_table;
}
/** @param {!World.World} world */
CombatEngine.DamageEffect.prototype.apply = goog.abstractMethod;

/** @return {!Object<string,?>} */
CombatEngine.DamageEffect.prototype.serialize = function() {
    /** @type {!Object<string,?>} */
    var ret;
    ret = {'tick': this.tick.get(),
           'client_time_hack': this.client_time_hack,
           'source_id': this.source_id,
           'amount': this.amount,
           'vs_table': this.vs_table};
    return ret;
};

/** @param {!CombatEngine.DamageEffect} effect */
CombatEngine.CombatEngine.prototype.queue_damage_effect = function(effect) {
    this.damage_effect_queue.push(effect);
};

/** @param {!World.World} world
    @param {boolean} use_ticks instead of client_time
    @return {boolean} true if more are pending */
CombatEngine.CombatEngine.prototype.apply_queued_damage_effects = function(world, use_ticks) {
    for(var i = 0; i < this.damage_effect_queue.length; i++) {
        var effect = this.damage_effect_queue[i];
        var do_it = (use_ticks ? GameTypes.TickCount.gte(this.cur_tick, effect.tick) :
                     (this.cur_client_time >= effect.client_time_hack));
        if(do_it) {
            this.damage_effect_queue.splice(i,1);
            effect.apply(world);
        }
    }
    return this.damage_effect_queue.length > 0;
};

/** @return {boolean} */
CombatEngine.CombatEngine.prototype.has_pending_damage_effects = function() {
    return this.damage_effect_queue.length > 0;
};


/** KillDamageEffect removes the object directly WITHOUT running on-death spells
    @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {!GameObjectId} target_id
*/
CombatEngine.KillDamageEffect = function(tick, client_time_hack, source_id, target_id) {
    goog.base(this, tick, client_time_hack, source_id, 0, null);
    this.target_id = target_id;
}
goog.inherits(CombatEngine.KillDamageEffect, CombatEngine.DamageEffect);
/** @override */
CombatEngine.KillDamageEffect.prototype.serialize = function() {
    var ret = goog.base(this, 'serialize');
    ret['kind'] = 'KillDamageEffect';
    ret['target_id'] = this.target_id;
    return ret;
};

/** @override */
CombatEngine.KillDamageEffect.prototype.apply = function(world) {
    // ensure the destroy message is sent only once, but do allow it to be sent even if target_obj.hp == 0
    var target = world.objects._get_object(this.target_id);
    if(!target) { return; }

    if(target.is_mobile()) {
        if((this.target_id === this.source_id) && ('suicide_explosion_effect' in target.spec)) {
            // leave no debris
        } else {
            world.create_debris(target, target.raw_pos());
        }
        world.send_and_destroy_object(target, world.objects._get_object(this.source_id));
    } else if(target.is_building()) {
        target.hp = 1;
        world.hurt_object(target, 999, {}, world.objects._get_object(this.source_id));
    }
};

/** @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {!GameObjectId} target_id
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.TargetedDamageEffect = function(tick, client_time_hack, source_id, target_id, amount, vs_table) {
    goog.base(this, tick, client_time_hack, source_id, amount, vs_table);
    this.target_id = target_id;
}
goog.inherits(CombatEngine.TargetedDamageEffect, CombatEngine.DamageEffect);
/** @override */
CombatEngine.TargetedDamageEffect.prototype.serialize = function() {
    var ret = goog.base(this, 'serialize');
    ret['kind'] = 'TargetedDamageEffect';
    ret['target_id'] = this.target_id;
    return ret;
};

/** @override */
CombatEngine.TargetedDamageEffect.prototype.apply = function(world) {
    var target = world.objects._get_object(this.target_id);
    if(!target || target.is_destroyed()) {
        // target is already dead
        return;
    }
    world.hurt_object(target, this.amount, this.vs_table, world.objects._get_object(this.source_id));
};

/** @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {!GameObjectId} target_id
    @param {!GameTypes.Integer} amount
    @param {string} aura_name
    @param {!GameTypes.TickCount} aura_duration
    @param {!CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
*/
CombatEngine.TargetedAuraEffect = function(tick, client_time_hack, source_id, target_id, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table) {
    goog.base(this, tick, client_time_hack, source_id, amount, vs_table);
    this.target_id = target_id;
    this.aura_name = aura_name;
    this.aura_duration = aura_duration;
    this.aura_range = aura_range;
    this.duration_vs_table = duration_vs_table;
}
goog.inherits(CombatEngine.TargetedAuraEffect, CombatEngine.DamageEffect);
/** @override */
CombatEngine.TargetedAuraEffect.prototype.serialize = function() {
    var ret = goog.base(this, 'serialize');
    ret['kind'] = 'TargetedAuraEffect';
    ret['target_id'] = this.target_id;
    ret['aura_name'] = this.aura_name;
    ret['aura_duration'] = this.aura_duration.get();
    ret['aura_range'] = this.aura_range;
    ret['duration_vs_table'] = this.duration_vs_table;
    return ret;
};

/** @override */
CombatEngine.TargetedAuraEffect.prototype.apply = function(world) {
    var target = world.objects._get_object(this.target_id);
    if(!target || target.is_destroyed()) {
        // target is already dead
        return;
    }
    if(this.amount != 0) {
        var duration = GameTypes.TickCount.scale(get_damage_modifier(this.duration_vs_table, target), this.aura_duration);
        if(duration.is_nonzero()) {
            target.create_aura(world, this.source_id, this.aura_name, this.amount, duration, this.aura_range, this.vs_table);
        }
    }
};

/** @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {!CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {!CombatEngine.Pos} radius
    @param {string} falloff XXX make into an enum
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaDamageEffect = function(tick, client_time_hack, source_id, target_location, hit_ground, hit_air, radius, falloff, amount, vs_table, allow_ff) {
    goog.base(this, tick, client_time_hack, source_id, amount, vs_table);
    this.target_location = target_location;
    this.hit_ground = hit_ground;
    this.hit_air = hit_air;
    this.radius = radius;
    this.falloff = falloff;
    this.allow_ff = allow_ff;
}
goog.inherits(CombatEngine.AreaDamageEffect, CombatEngine.DamageEffect);
/** @override */
CombatEngine.AreaDamageEffect.prototype.serialize = function() {
    var ret = goog.base(this, 'serialize');
    ret['kind'] = 'AreaDamageEffect';
    ret['target_location'] = this.target_location;
    ret['hit_ground'] = this.hit_ground;
    ret['hit_air'] = this.hit_air;
    ret['radius'] = this.radius;
    ret['falloff'] = this.falloff;
    ret['allow_ff'] = this.allow_ff;
    return ret;
};

/** @override */
CombatEngine.AreaDamageEffect.prototype.apply = function(world) {
    var source = world.objects._get_object(this.source_id);

    // hurt all objects within radius
    var obj_list = world.query_objects_within_distance(this.target_location, this.radius,
                                                       { exclude_invul: true,
                                                         exclude_flying: !this.hit_air,
                                                         flying_only: (this.hit_air && !this.hit_ground) });
    goog.array.forEach(obj_list, function(result) {
        var obj = result.obj;
        var dist = result.dist;
        var pos = result.pos;
        if(obj.is_destroyed()) { return; }
        if(!this.allow_ff && source && obj.team === source.team) { return; }
        if(obj.spec['immune_to_splash']) { return; }

        /** @type {!CombatEngine.Pos} */
        var falloff;
        if(this.falloff == 'linear') {
            // fall off the damage amount as 1/r
            falloff = CombatEngine.Pos.clamp(1.0-(dist/this.radius), 0, 1);
        } else if(this.falloff == 'constant') {
            falloff = 1;
        } else {
            console.log('unhandled falloff type '+this.falloff);
        }

        var amt = this.amount * falloff;
        if(amt != 0) {
            world.hurt_object(obj, amt, this.vs_table, source);
        }
    }, this);
};

/** @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {!CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {!CombatEngine.Pos} radius
    @param {boolean} radius_rect - use rectangular rather than circular coverage
    @param {string} falloff XXX make into an enum
    @param {!GameTypes.Integer} amount
    @param {string} aura_name
    @param {!GameTypes.TickCount} aura_duration
    @param {!CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaAuraEffect = function(tick, client_time_hack, source_id, target_location, hit_ground, hit_air, radius, radius_rect, falloff, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table, allow_ff) {
    goog.base(this, tick, client_time_hack, source_id, amount, vs_table);
    this.target_location = target_location;
    this.hit_ground = hit_ground;
    this.hit_air = hit_air;
    this.radius = radius;
    this.radius_rect = radius_rect;
    this.falloff = falloff;
    this.aura_name = aura_name;
    this.aura_duration = aura_duration;
    this.aura_range = aura_range;
    this.duration_vs_table = duration_vs_table;
    this.allow_ff = allow_ff;
}
goog.inherits(CombatEngine.AreaAuraEffect, CombatEngine.DamageEffect);
/** @override */
CombatEngine.AreaAuraEffect.prototype.serialize = function() {
    var ret = goog.base(this, 'serialize');
    ret['target_location'] = this.target_location;
    ret['kind'] = 'AreaAuraEffect';
    ret['hit_ground'] = this.hit_ground;
    ret['hit_air'] = this.hit_air;
    ret['radius'] = this.radius;
    ret['radius_rect'] = this.radius_rect;
    ret['falloff'] = this.falloff;
    ret['aura_name'] = this.aura_name;
    ret['aura_duration'] = this.aura_duration.get();
    ret['aura_range'] = this.aura_range;
    ret['duration_vs_table'] = this.duration_vs_table;
    ret['allow_ff'] = this.allow_ff;
    return ret;
};

/** @override */
CombatEngine.AreaAuraEffect.prototype.apply = function(world) {
    var source = world.objects._get_object(this.source_id);

    var query_r;
    if(this.radius_rect) {
        // query the max possible distance away a unit could be and still be within the rectangle
        var a = this.radius_rect[0]/2, b = this.radius_rect[1]/2;
        query_r = Math.sqrt(a*a+b*b);
    } else {
        // query the circular effect radius
        query_r = this.radius;
    }

    // apply aura to all objects within radius
    var obj_list = world.query_objects_within_distance(this.target_location, query_r,
                                                       { exclude_invul: true,
                                                         exclude_flying: !this.hit_air,
                                                         flying_only: (this.hit_air && !this.hit_ground) });
    goog.array.forEach(obj_list, function(result) {
        var obj = result.obj, dist = result.dist, pos = result.pos;

        if(obj.is_destroyed()) { return; }
        if(!this.allow_ff && source && obj.team === source.team) { return; }
        if(obj.spec['immune_to_splash']) { return; }

        if(this.radius_rect) {
            // skip objects that are outside the radius_rect rectangle centered on target_location
            var d = CombatEngine.Pos2D.sub(pos, this.target_location);
            var a = this.radius_rect[0]/2, b = this.radius_rect[1]/2;
            if(d[0] < -a || d[0] > a || d[1] < -b || d[1] > b) { return; }
        }

        /** @type {!CombatEngine.Coeff} */
        var falloff;
        if(this.falloff == 'linear' && !this.radius_rect) {
            // fall off the damage amount as 1/r
            falloff = CombatEngine.Pos.clamp(1.0-(dist/this.radius), 0, 1);
        } else if(this.falloff == 'constant') {
            falloff = 1;
        } else {
            console.log('unhandled falloff type '+this.falloff);
        }

        var amt = this.amount * falloff;
        if(amt != 0) {
            var duration = GameTypes.TickCount.scale(get_damage_modifier(this.duration_vs_table, obj), this.aura_duration);
            if(duration.is_nonzero()) {
                obj.create_aura(world, this.source_id, this.aura_name, amt, duration, this.aura_range, this.vs_table);
            }
        }
    }, this);
};
