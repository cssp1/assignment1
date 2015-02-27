goog.provide('CombatEngine');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('GameTypes');

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

/** @constructor
    @struct */
CombatEngine.CombatEngine = function() {
    /** @type {!GameTypes.TickCount} */
    this.cur_tick = new GameTypes.TickCount(0);

    /** list of queued damage effects that should be applied at later times (possible optimization: use a priority queue)
        @type {Array.<!CombatEngine.DamageEffect>} */
    this.damage_effect_queue = [];
};

// DamageEffects

/** @constructor
    @struct
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack - until SPFX can think in terms of ticks, have to use client_time instead of tick count for applicaiton
    @param {GameObject|null} source
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.DamageEffect = function(tick, client_time_hack, source, amount, vs_table) {
    this.tick = tick;
    this.client_time_hack = client_time_hack;
    this.source = source;
    this.amount = amount;
    this.vs_table = vs_table;
}
CombatEngine.DamageEffect.prototype.apply = goog.abstractMethod;


/** @return {boolean} true if more are pending */
CombatEngine.CombatEngine.prototype.apply_queued_damage_effects = function() {
    for(var i = 0; i < this.damage_effect_queue.length; i++) {
        var effect = this.damage_effect_queue[i];
        if(client_time >= effect.client_time_hack) {
        //if(GameTypes.TickCount.gte(this.cur_tick, effect.tick)) {
            this.damage_effect_queue.splice(i,1);
            effect.apply();
        }
    }
    return this.damage_effect_queue.length > 0;
};


/** KillDamageEffect removes the object directly WITHOUT running on-death spells
    @constructor
    @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObject|null} source
    @param {GameObject} target_obj
*/
CombatEngine.KillDamageEffect = function(tick, client_time_hack, source, target_obj) {
    goog.base(this, tick, client_time_hack, source, 0, null);
    this.target_obj = target_obj;
}
goog.inherits(CombatEngine.KillDamageEffect, CombatEngine.DamageEffect);
CombatEngine.KillDamageEffect.prototype.apply = function() {
    // ensure the destroy_object message is sent only once, but do allow it to be sent even if target_obj.hp == 0
    if(!this.target_obj.id || (this.target_obj.id === GameObject.DEAD_ID)) { return; }

    if(this.target_obj.is_mobile()) {
        if((this.target_obj === this.source) && ('suicide_explosion_effect' in this.target_obj.spec)) {
            // leave no debris
        } else {
            create_debris(this.target_obj, this.target_obj.interpolate_pos()); // XXXXXX calls into main
        }
        send_and_destroy_object(this.target_obj, this.source); // XXXXXX calls into main
    } else if(this.target_obj.is_building()) {
        this.target_obj.hp = 1;
        hurt_object(this.target_obj, 999, {}, this.source); // XXXXXX calls into main
    }
};

/** @constructor
    @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObject|null} source
    @param {GameObject} target_obj
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.TargetedDamageEffect = function(tick, client_time_hack, source, target_obj, amount, vs_table) {
    goog.base(this, tick, client_time_hack, source, amount, vs_table);
    this.target_obj = target_obj;
}
goog.inherits(CombatEngine.TargetedDamageEffect, CombatEngine.DamageEffect);
CombatEngine.TargetedDamageEffect.prototype.apply = function() {
    if(this.target_obj.is_destroyed()) {
        // target is already dead
        return;
    }
    hurt_object(this.target_obj, this.amount, this.vs_table, this.source); // XXXXXX calls into main
};

/** @constructor
    @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObject|null} source
    @param {GameObject} target_obj
    @param {!GameTypes.Integer} amount
    @param {string} aura_name
    @param {!GameTypes.TickCount} aura_duration
    @param {!CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
*/
CombatEngine.TargetedAuraEffect = function(tick, client_time_hack, source, target_obj, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table) {
    goog.base(this, tick, client_time_hack, source, amount, vs_table);
    this.target_obj = target_obj;
    this.aura_name = aura_name;
    this.aura_duration = aura_duration;
    this.aura_range = aura_range;
    this.duration_vs_table = duration_vs_table;
}
goog.inherits(CombatEngine.TargetedAuraEffect, CombatEngine.DamageEffect);
CombatEngine.TargetedAuraEffect.prototype.apply = function() {
    if(this.target_obj.is_destroyed()) {
        // target is already dead
        return;
    }
    if(this.amount != 0) {
        var duration = GameTypes.TickCount.scale(get_damage_modifier(this.duration_vs_table, this.target_obj), this.aura_duration);
        if(duration.is_nonzero()) {
            this.target_obj.create_aura(this.source, this.aura_name, this.amount, duration, this.aura_range, this.vs_table);
        }
    }
};

/** @constructor
    @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObject|null} source
    @param {!CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {!CombatEngine.Pos} radius
    @param {string} falloff XXXXXX make into an enum
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaDamageEffect = function(tick, client_time_hack, source, target_location, hit_ground, hit_air, radius, falloff, amount, vs_table, allow_ff) {
    goog.base(this, tick, client_time_hack, source, amount, vs_table);
    this.target_location = target_location;
    this.hit_ground = hit_ground;
    this.hit_air = hit_air;
    this.radius = radius;
    this.falloff = falloff;
    this.allow_ff = allow_ff;
}
goog.inherits(CombatEngine.AreaDamageEffect, CombatEngine.DamageEffect);

CombatEngine.AreaDamageEffect.prototype.apply = function() {
    // hurt all objects within radius
    var obj_list = query_objects_within_distance(this.target_location, this.radius,
                                                 { exclude_invul: true,
                                                   exclude_flying: !this.hit_air,
                                                   flying_only: (this.hit_air && !this.hit_ground) });
    goog.array.forEach(obj_list, function(result) {
        var obj = result.obj;
        var dist = result.dist;
        var pos = result.pos;
        if(obj.is_destroyed()) { return; }
        if(!this.allow_ff && obj.team === this.source.team) { return; }
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
            hurt_object(obj, amt, this.vs_table, this.source);  // XXXXXX calls into main
        }
    }, this);
};

/** @constructor
    @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObject|null} source
    @param {!CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {!CombatEngine.Pos} radius
    @param {boolean} radius_rect - use rectangular rather than circular coverage
    @param {string} falloff XXXXXX make into an enum
    @param {!GameTypes.Integer} amount
    @param {string} aura_name
    @param {!GameTypes.TickCount} aura_duration
    @param {!CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaAuraEffect = function(tick, client_time_hack, source, target_location, hit_ground, hit_air, radius, radius_rect, falloff, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table, allow_ff) {
    goog.base(this, tick, client_time_hack, source, amount, vs_table);
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
CombatEngine.AreaAuraEffect.prototype.apply = function() {
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
    var obj_list = query_objects_within_distance(this.target_location, query_r,
                                                 { exclude_invul: true,
                                                   exclude_flying: !this.hit_air,
                                                   flying_only: (this.hit_air && !this.hit_ground) });
    goog.array.forEach(obj_list, function(result) {
        var obj = result.obj, dist = result.dist, pos = result.pos;

        if(obj.is_destroyed()) { return; }
        if(!this.allow_ff && obj.team === this.source.team) { return; }
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
                obj.create_aura(this.source, this.aura_name, amt, duration, this.aura_range, this.vs_table);
            }
        }
    }, this);
};
