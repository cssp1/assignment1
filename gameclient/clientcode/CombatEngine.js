goog.provide('CombatEngine');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.array');
goog.require('goog.object');

// numeric types - eventually will need to become fixed-point

/** Scaling coefficient, like a damage_vs coefficient
    Assumed to be small, like 0-100, but need fractional precision
    @typedef {number} */
CombatEngine.Coeff;

/** @typedef {number} */
CombatEngine.Integer;

/** 1D object position
    @typedef {number} */
CombatEngine.Pos;

/** 2D object location
    @typedef {Array.<CombatEngine.Pos>} */
CombatEngine.Pos2D;

/** @constructor */
CombatEngine.CombatEngine = function() {
    /** list of queued damage effects that should be applied at later times (possible optimization: use a priority queue)
        @type {Array.<CombatEngine.DamageEffect>} */
    this.damage_effect_queue = [];
};

// DamageEffects

/** @constructor
    @param {number} time XXXXXX this should be a tick count!
    @param {GameObject|null} source
    @param {CombatEngine.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.DamageEffect = function(time, source, amount, vs_table) {
    this.time = time;
    this.source = source;
    this.amount = amount;
    this.vs_table = vs_table;
}

/** KillDamageEffect removes the object directly WITHOUT running on-death spells
    @constructor
    @extends CombatEngine.DamageEffect
    @param {number} time XXXXXX this should be a tick count!
    @param {GameObject|null} source
    @param {GameObject} target_obj
*/
CombatEngine.KillDamageEffect = function(time, source, target_obj) {
    goog.base(this, time, source, 0, null);
    this.target_obj = target_obj;
}
goog.inherits(CombatEngine.KillDamageEffect, CombatEngine.DamageEffect);
CombatEngine.KillDamageEffect.prototype.apply = function() {
    // ensure the destroy_object message is sent only once, but do allow it to be sent even if target_obj.hp == 0
    if(!this.target_obj.id || (this.target_obj.id === -1)) { return; }

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
    @extends CombatEngine.DamageEffect
    @param {number} time XXXXXX this should be a tick count!
    @param {GameObject|null} source
    @param {GameObject} target_obj
    @param {CombatEngine.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.TargetedDamageEffect = function(time, source, target_obj, amount, vs_table) {
    goog.base(this, time, source, amount, vs_table);
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
    @extends CombatEngine.DamageEffect
    @param {number} time XXXXXX this should be a tick count!
    @param {GameObject|null} source
    @param {GameObject} target_obj
    @param {CombatEngine.Integer} amount
    @param {string} aura_name
    @param {number} aura_duration XXXXXX tick count?
    @param {CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
*/
CombatEngine.TargetedAuraEffect = function(time, source, target_obj, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table) {
    goog.base(this, time, source, amount, vs_table);
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
        var duration = this.aura_duration * get_damage_modifier(this.duration_vs_table, this.target_obj); // XXXXXX calls into main
        if(duration > 0) {
            this.target_obj.create_aura(this.source, this.aura_name, this.amount, duration, this.aura_range, this.vs_table);
        }
    }
};

/** @constructor
    @extends CombatEngine.DamageEffect
    @param {number} time XXXXXX this should be a tick count!
    @param {GameObject|null} source
    @param {CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {CombatEngine.Pos} radius
    @param {string} falloff XXXXXX make into an enum
    @param {CombatEngine.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaDamageEffect = function(time, source, target_location, hit_ground, hit_air, radius, falloff, amount, vs_table, allow_ff) {
    goog.base(this, time, source, amount, vs_table);
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
    var obj_list = query_objects_within_distance(this.target_location, this.radius, // XXXXXX calls into main
                                                 { exclude_invul: true,
                                                   exclude_flying: !this.hit_air,
                                                   flying_only: (this.hit_air && !this.hit_ground) });
    for(var i = 0; i < obj_list.length; i++) {
        var obj = obj_list[i][0], dist = obj_list[i][1], pos = obj_list[i][2];
        if(obj.is_destroyed()) { continue; }
        if(!this.allow_ff && obj.team === this.source.team) { continue; }
        if(obj.spec['immune_to_splash']) { continue; }

        var falloff;
        if(this.falloff == 'linear') {
            // fall off the damage amount as 1/r
            falloff = clamp(1.0-(dist/this.radius), 0, 1);
        } else if(this.falloff == 'constant') {
            falloff = 1;
        } else {
            console.log('unhandled falloff type '+this.falloff);
        }

        var amt = this.amount * falloff;
        if(amt != 0) {
            hurt_object(obj, amt, this.vs_table, this.source);  // XXXXXX calls into main
        }
    }
};

/** @constructor
    @extends CombatEngine.DamageEffect
    @param {number} time XXXXXX this should be a tick count!
    @param {GameObject|null} source
    @param {CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {CombatEngine.Pos} radius
    @param {boolean} radius_rect - use rectangular rather than circular coverage
    @param {string} falloff XXXXXX make into an enum
    @param {CombatEngine.Integer} amount
    @param {string} aura_name
    @param {number} aura_duration XXXXXX tick count?
    @param {CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaAuraEffect = function(time, source, target_location, hit_ground, hit_air, radius, radius_rect, falloff, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table, allow_ff) {
    goog.base(this, time, source, amount, vs_table);
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
    var obj_list = query_objects_within_distance(this.target_location, query_r, // XXXXXX calls into main
                                                 { exclude_invul: true,
                                                   exclude_flying: !this.hit_air,
                                                   flying_only: (this.hit_air && !this.hit_ground) });
    for(var i = 0; i < obj_list.length; i++) {
        var obj = obj_list[i][0], dist = obj_list[i][1], pos = obj_list[i][2];
        if(obj.is_destroyed()) { continue; }
        if(!this.allow_ff && obj.team === this.source.team) { continue; }
        if(obj.spec['immune_to_splash']) { continue; }

        if(this.radius_rect) {
            // skip objects that are outside the radius_rect rectangle centered on target_location
            var d = vec_sub(pos, this.target_location);
            var a = this.radius_rect[0]/2, b = this.radius_rect[1]/2;
            if(d[0] < -a || d[0] > a || d[1] < -b || d[1] > b) { continue; }
        }

        var falloff;
        if(this.falloff == 'linear' && !this.radius_rect) {
            // fall off the damage amount as 1/r
            falloff = clamp(1.0-(dist/this.radius), 0, 1);
        } else if(this.falloff == 'constant') {
            falloff = 1;
        } else {
            console.log('unhandled falloff type '+this.falloff);
        }

        var amt = this.amount * falloff;
        if(amt != 0) {
            var duration = this.aura_duration * get_damage_modifier(this.duration_vs_table, obj); // XXXXXX calls into main
            if(duration > 0) {
                obj.create_aura(this.source, this.aura_name, amt, duration, this.aura_range, this.vs_table);
            }
        }
    }
};
