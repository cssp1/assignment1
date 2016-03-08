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
    @implements {GameTypes.IIncrementallySerializable} */
CombatEngine.CombatEngine = function() {
    /** @type {!GameTypes.TickCount} */
    this.cur_tick = new GameTypes.TickCount(0);

    /** @type {number} hack for time-based effects */
    this.cur_client_time = 0;

    /** list of queued damage effects that should be applied at later times (possible optimization: use a priority queue)
        @private
        @type {!Array.<!CombatEngine.DamageEffect>} */
    this.damage_effect_queue = [];

    // XXX awkward - for replays only - disable addition of new damage effects
    // should be replaced by some kind of dataflow mechanism
    this.accept_damage_effects = true;

    /** for incremental serialization
        @private
        @type {!Array<!CombatEngine.DamageEffect>} */
    this.damage_effect_queue_dirty_added = [];

    /** list of not-unit-based (missile) projectiles that need to be evaluated for firing this tick (may not actually fire until a future tick)
        @private
        @type {!Array<!CombatEngine.ProjectileEffect>} */
    this.projectile_queue = [];
    /** for incremental serialization
        @private
        @type {!Array<!CombatEngine.ProjectileEffect>} */
    this.projectile_queue_dirty_added = [];
};

/** @override */
CombatEngine.CombatEngine.prototype.serialize = function() {
    return {'cur_tick': this.cur_tick.get(),
            'cur_client_time': this.cur_client_time,
            'damage_effect_queue': goog.array.map(this.damage_effect_queue, function(effect) { return effect.serialize(); }, this),
            'projectile_queue': goog.array.map(this.projectile_queue, function(effect) { return effect.serialize(); }, this)};
};
/** @override */
CombatEngine.CombatEngine.prototype.serialize_incremental = function() {
    var ret = {'cur_tick': this.cur_tick.get(),
               'cur_client_time': this.cur_client_time};
    // XXXXXX this doesn't work if the first call happens with effects already queued,
    // because the dirty list has been cleared of them already!
    if(this.damage_effect_queue_dirty_added.length > 0) {
        ret['damage_effect_queue_added'] = goog.array.map(this.damage_effect_queue_dirty_added, function(effect) { return effect.serialize(); }, this);
        ret['damage_effect_queue_length'] = this.damage_effect_queue.length;
        goog.array.clear(this.damage_effect_queue_dirty_added);
    }
    if(this.projectile_queue_dirty_added.length > 0) {
        ret['projectile_queue_added'] = goog.array.map(this.projectile_queue_dirty_added, function(effect) { return effect.serialize(); }, this);
        ret['projectile_queue_length'] = this.projectile_queue.length;
        goog.array.clear(this.projectile_queue_dirty_added);
    }
    return ret;
};
/** @override */
CombatEngine.CombatEngine.prototype.apply_snapshot = function(snap) {
    this.cur_tick = new GameTypes.TickCount(snap['cur_tick']);
    this.cur_client_time = snap['cur_client_time'];
    if('damage_effect_queue' in snap) {
        this.damage_effect_queue = goog.array.map(snap['damage_effect_queue'], function(/** !Object<string,?> */ effect_snap) {
            return this.unserialize_damage_effect(effect_snap);
        }, this);
    } else if('damage_effect_queue_added' in snap) {
        this.damage_effect_queue = this.damage_effect_queue.concat(goog.array.map(snap['damage_effect_queue_added'], function(/** !Object<string,?> */ effect_snap) {
            return this.unserialize_damage_effect(effect_snap);
        }, this));
        var expected_len = /** @type {number} */ (snap['damage_effect_queue_length']);
        if(this.damage_effect_queue.length != expected_len) {
            throw Error('unexpected damage_effect_queue_length '+expected_len.toString()+' vs. '+this.damage_effect_queue.length.toString());
        }
    }
    if('projectile_queue' in snap) { // complete replacement
        this.projectile_queue = goog.array.map(snap['projectile_queue'], function(/** !Object<string,?> */ effect_snap) {
            return this.unserialize_projectile_effect(effect_snap);
        }, this);
    } else if('projectile_queue_added' in snap) {
        this.projectile_queue = this.projectile_queue.concat(goog.array.map(snap['projectile_queue_added'], function(/** !Object<string,?> */ effect_snap) {
            return this.unserialize_projectile_effect(effect_snap);
        }, this));
        var expected_len = /** @type {number} */ (snap['projectile_queue_length']);
        if(this.projectile_queue.length != expected_len) {
            throw Error('unexpected projectile_queue_length '+expected_len.toString()+' vs. '+this.projectile_queue.length.toString());
        }
    }
};

/** @param {!Object<string,?>} snap
    @return {!CombatEngine.ProjectileEffect} */
CombatEngine.CombatEngine.prototype.unserialize_projectile_effect = function(snap) {
    return new CombatEngine.ProjectileEffect(snap['source_id'], snap['source_team'], snap['source_pos'], snap['source_height'],
                                             snap['muzzle_pos'],
                                             new GameTypes.TickCount(snap['fire_tick']), snap['fire_time_hack'],
                                             snap['force_hit_tick'] ? new GameTypes.TickCount(snap['force_hit_tick']) : null, snap['force_hit_time_hack'],
                                             snap['spellname'], snap['spell_level'],
                                             snap['target_id'], snap['target_pos'], snap['target_height'], snap['interceptor_id']);
};

/** @param {!Object<string,?>} snap
    @return {!CombatEngine.DamageEffect} */
CombatEngine.CombatEngine.prototype.unserialize_damage_effect = function(snap) {
    if(snap['kind'] === 'KillDamageEffect') {
        return new CombatEngine.KillDamageEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['source_team'], snap['target_id']);
    } else if(snap['kind'] === 'TargetedDamageEffect') {
        return new CombatEngine.TargetedDamageEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['source_team'], snap['target_id'], snap['amount'], snap['vs_table']);
    } else if(snap['kind'] === 'TargetedAuraEffect') {
        return new CombatEngine.TargetedAuraEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['source_team'], snap['target_id'], snap['amount'], snap['aura_name'], new GameTypes.TickCount(snap['aura_duration']), snap['aura_range'], snap['vs_table'], snap['duration_vs_table']);
    } else if(snap['kind'] === 'AreaDamageEffect') {
        return new CombatEngine.AreaDamageEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['source_team'], snap['target_location'], snap['hit_ground'], snap['hit_air'], snap['radius'], snap['falloff'], snap['amount'], snap['vs_table'], snap['allow_ff']);
    } else if(snap['kind'] === 'AreaAuraEffect') {
        return new CombatEngine.AreaAuraEffect(new GameTypes.TickCount(snap['tick']), snap['client_time_hack'], snap['source_id'], snap['source_team'], snap['target_location'], snap['hit_ground'], snap['hit_air'], snap['radius'], snap['radius_rect'], snap['falloff'], snap['amount'], snap['aura_name'], new GameTypes.TickCount(snap['aura_duration']), snap['aura_range'], snap['vs_table'], snap['duration_vs_table'], snap['allow_ff']);
    } else {
        throw Error('unknown kind '+snap['kind']);
    }
};

// ProjectileEffect
// Right now this is only used for firing missiles in combat

/** @constructor @struct
    @implements {GameTypes.ISerializable}
    @param {!GameObjectId} source_id
    @param {!TeamId} source_team
    @param {!CombatEngine.Pos2D} source_pos
    @param {number} source_height
    @param {!CombatEngine.Pos2D} muzzle_pos
    @param {!GameTypes.TickCount} fire_tick
    @param {number} fire_time_hack - offset from client_time at effect creation, -1 if invalid
    @param {GameTypes.TickCount|null} force_hit_tick
    @param {number} force_hit_time_hack - offset from client_time at effect creation -1 if invalid
    @param {string} spellname
    @param {number} spell_level
    @param {GameObjectId|null} target_id
    @param {!CombatEngine.Pos2D} target_pos
    @param {number} target_height
    @param {GameObjectId|null} interceptor_id
*/
CombatEngine.ProjectileEffect = function(source_id, source_team, source_pos, source_height, muzzle_pos,
                                         fire_tick, fire_time_hack, force_hit_tick, force_hit_time_hack,
                                         spellname, spell_level, target_id, target_pos, target_height, interceptor_id) {
    this.source_id = source_id;
    this.source_team = source_team;
    this.source_pos = source_pos;
    this.source_height = source_height;
    this.muzzle_pos = muzzle_pos;
    this.fire_tick = fire_tick;
    this.fire_time_hack = fire_time_hack;
    this.force_hit_tick = force_hit_tick;
    this.force_hit_time_hack = force_hit_time_hack;
    this.spellname = spellname;
    this.spell_level = spell_level;
    this.target_id = target_id;
    this.target_pos = target_pos;
    this.target_height = target_height;
    this.interceptor_id = interceptor_id;
};
/** @override */
CombatEngine.ProjectileEffect.prototype.serialize = function() {
    /** @type {!Object<string,?>} */
    var ret = {'source_id': this.source_id,
               'source_team': this.source_team,
               'source_pos': this.source_pos,
               'source_height': this.source_height,
               'muzzle_pos': this.muzzle_pos,
               'fire_tick': this.fire_tick.get(),
               'fire_time_hack': this.fire_time_hack,
               'force_hit_tick': this.force_hit_tick ? this.force_hit_tick.get() : null,
               'force_hit_time_hack': this.force_hit_time_hack,
               'spellname': this.spellname,
               'spell_level': this.spell_level,
               'target_id': this.target_id,
               'target_pos': this.target_pos,
               'target_height': this.target_height,
               'interceptor_id': this.interceptor_id};
    return ret;
};
/** @override */
CombatEngine.ProjectileEffect.prototype.apply_snapshot = goog.abstractMethod; // immutable

/** @param {!World.World} world */
CombatEngine.ProjectileEffect.prototype.apply = function(world) {
    /** @type {GameObject|null} note: may be null */
    var source = world.objects._get_object(this.source_id);
    /** @type {GameObject|null} note: may be null */
    var target = (this.target_id ? world.objects._get_object(this.target_id) : null);
    if(!target && !this.target_pos) { return; } // targeted to an object that doesn't exist anymore

    var spell = /** @type {!Object<string,?>} */ (gamedata['spells'][this.spellname]);
    var fizzle = !!this.interceptor_id;

    var hit_tick, hit_time;
    if(COMBAT_ENGINE_USE_TICKS) {
        hit_tick = do_fire_projectile_ticks(world, source, this.source_id, source ? /** @type {string} */ (source.spec['name']) : 'VIRTUAL', this.spell_level, this.source_team, null, this.source_pos, this.source_height, this.muzzle_pos, this.fire_tick, this.force_hit_tick, spell, target, this.target_pos, this.target_height, fizzle);
        hit_time = -1;
    } else {
        hit_time = do_fire_projectile_time(world, source, this.source_id, source ? /** @type {string} */ (source.spec['name']) : 'VIRTUAL', this.spell_level, this.source_team, null, this.source_pos, this.source_height, this.muzzle_pos, this.fire_time_hack + world.last_tick_time, this.force_hit_time_hack, spell, target, this.target_pos, this.target_height, fizzle);
        hit_tick = absolute_time_to_tick(hit_time);
    }

    if(this.interceptor_id) {
        // intecepting shot effect
        var interceptor = world.objects.get_object(this.interceptor_id); // will fail for dead mobile interceptors
        // hack - don't bother computing the actual fire time
        interceptor.fire_projectile(world, new GameTypes.TickCount(hit_tick.get()-1), hit_time-0.25, hit_tick, hit_time, interceptor.get_auto_spell(), interceptor.get_auto_spell_level(), null, this.target_pos, this.target_height);
    }
};

// DamageEffects

/** @constructor @struct
    @implements {GameTypes.ISerializable}
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack - until SPFX can think in terms of ticks, have to use client_time instead of tick count for applicaiton
    @param {GameObjectId|null} source_id
    @param {string|null} source_team
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.DamageEffect = function(tick, client_time_hack, source_id, source_team, amount, vs_table) {
    this.tick = tick;
    this.client_time_hack = client_time_hack;
    this.source_id = source_id;
    this.source_team = source_team;
    this.amount = amount;
    this.vs_table = vs_table;
}
/** @param {!World.World} world */
CombatEngine.DamageEffect.prototype.apply = goog.abstractMethod;

/** @override */
CombatEngine.DamageEffect.prototype.serialize = function() {
    /** @type {!Object<string,?>} */
    var ret;
    ret = {'tick': this.tick.get(),
           'client_time_hack': this.client_time_hack,
           'source_id': this.source_id,
           'source_team': this.source_team,
           'amount': this.amount,
           'vs_table': this.vs_table};
    return ret;
};
/** @override */
CombatEngine.DamageEffect.prototype.apply_snapshot = goog.abstractMethod; // immutable

/** @param {!CombatEngine.DamageEffect} effect */
CombatEngine.CombatEngine.prototype.queue_damage_effect = function(effect) {
    if(!this.accept_damage_effects) { return; }
    this.damage_effect_queue.push(effect);
    this.damage_effect_queue_dirty_added.push(effect);
};
/** @param {!CombatEngine.ProjectileEffect} effect */
CombatEngine.CombatEngine.prototype.queue_projectile = function(effect) {
    this.projectile_queue.push(effect);
    this.projectile_queue_dirty_added.push(effect);
};

/** @param {!World.World} world
    @param {boolean} use_ticks instead of client_time
    @return {boolean} true if more are pending */
CombatEngine.CombatEngine.prototype.apply_queued_damage_effects = function(world, use_ticks) {
    goog.array.clear(this.damage_effect_queue_dirty_added); // just a convenient place to reset this
    goog.array.clear(this.projectile_queue_dirty_added); // just a convenient place to reset this

    for(var p = 0; p < this.projectile_queue.length; p++) {
        var peffect = this.projectile_queue.splice(p,1)[0]; p -= 1;
        peffect.apply(world);
    }


    // only apply effects that were already queued right now
    // take care not to apply effects that are appended from within apply() below.
    var to_check = this.damage_effect_queue.length;

    for(var i = 0, checked = 0; checked < to_check; i++, checked++) {
        var effect = this.damage_effect_queue[i];
        var do_it = (use_ticks ? GameTypes.TickCount.gte(this.cur_tick, effect.tick) :
                     (this.cur_client_time >= effect.client_time_hack));
        if(do_it) {
            this.damage_effect_queue.splice(i,1); i -= 1;
            to_check -= 1;
            effect.apply(world);
        }
    }

    return this.has_queued_damage_effects();
};

/** For use by replay code */
CombatEngine.CombatEngine.prototype.clear_queued_damage_effects = function() {
    goog.array.clear(this.damage_effect_queue);
    goog.array.clear(this.damage_effect_queue_dirty_added);
    goog.array.clear(this.projectile_queue);
    goog.array.clear(this.projectile_queue_dirty_added);
};

/** @return {boolean} */
CombatEngine.CombatEngine.prototype.has_queued_damage_effects = function() {
    return this.damage_effect_queue.length > 0 || this.projectile_queue.length > 0;
};


/** KillDamageEffect removes the object directly WITHOUT running on-death spells
    @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {string|null} source_team
    @param {!GameObjectId} target_id
*/
CombatEngine.KillDamageEffect = function(tick, client_time_hack, source_id, source_team, target_id) {
    goog.base(this, tick, client_time_hack, source_id, source_team, 0, null);
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
    @param {string|null} source_team
    @param {!GameObjectId} target_id
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
*/
CombatEngine.TargetedDamageEffect = function(tick, client_time_hack, source_id, source_team, target_id, amount, vs_table) {
    goog.base(this, tick, client_time_hack, source_id, source_team, amount, vs_table);
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
    @param {string|null} source_team
    @param {!GameObjectId} target_id
    @param {!GameTypes.Integer} amount
    @param {string} aura_name
    @param {!GameTypes.TickCount} aura_duration
    @param {!CombatEngine.Pos} aura_range
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {Object.<string,CombatEngine.Coeff>} duration_vs_table
*/
CombatEngine.TargetedAuraEffect = function(tick, client_time_hack, source_id, source_team, target_id, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table) {
    goog.base(this, tick, client_time_hack, source_id, source_team, amount, vs_table);
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
            target.create_aura(world, this.source_id, this.source_team, this.aura_name, this.amount, duration, this.aura_range, this.vs_table);
        }
    }
};

/** @constructor @struct
    @extends CombatEngine.DamageEffect
    @param {!GameTypes.TickCount} tick
    @param {number} client_time_hack
    @param {GameObjectId|null} source_id
    @param {string|null} source_team
    @param {!CombatEngine.Pos2D} target_location
    @param {boolean} hit_ground
    @param {boolean} hit_air
    @param {!CombatEngine.Pos} radius
    @param {string} falloff XXX make into an enum
    @param {!GameTypes.Integer} amount
    @param {Object.<string,CombatEngine.Coeff>} vs_table
    @param {boolean} allow_ff - allow friendly fire
*/
CombatEngine.AreaDamageEffect = function(tick, client_time_hack, source_id, source_team, target_location, hit_ground, hit_air, radius, falloff, amount, vs_table, allow_ff) {
    goog.base(this, tick, client_time_hack, source_id, source_team, amount, vs_table);
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
        if(!this.allow_ff && this.source_team && obj.team === this.source_team) { return; }
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
    @param {string|null} source_team
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
CombatEngine.AreaAuraEffect = function(tick, client_time_hack, source_id, source_team, target_location, hit_ground, hit_air, radius, radius_rect, falloff, amount, aura_name, aura_duration, aura_range, vs_table, duration_vs_table, allow_ff) {
    goog.base(this, tick, client_time_hack, source_id, source_team, amount, vs_table);
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
        if(!this.allow_ff && this.source_team && obj.team === this.source_team) { return; }
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
                obj.create_aura(world, this.source_id, this.source_team, this.aura_name, amt, duration, this.aura_range, this.vs_table);
            }
        }
    }, this);
};
