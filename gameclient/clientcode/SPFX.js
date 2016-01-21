goog.provide('SPFX');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview

    Note: references from main.js: canvas_width, canvas_height, canvas_oversample, view_is_zoomed, and some others
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('GameTypes');
goog.require('GameArt');
goog.require('SPUI');
goog.require('ShakeSynth');

// all coordinates here are in game map cell units (not quantized, fractions OK)

// global namespace

/** @type {?CanvasRenderingContext2D} */
SPFX.ctx = null;

/** @type {number}
    @private */
SPFX.time = 0;

/** @type {number}
    @private */
SPFX.last_tick_time = 0;

/** @type {!GameTypes.TickCount}
    @private */
SPFX.tick = new GameTypes.TickCount(0);

/** @type {!GameTypes.TickCount}
    @private */
SPFX.last_tick = new GameTypes.TickCount(0);


/** Some effects want to fire at specific client_times and others want
 to fire at specific combat ticks. This type encapsulates both cases.
 @constructor
 @struct
 @param {number|null} time - compared against SPFX.time (client_time)
 @param {GameTypes.TickCount|null} tick - compared against current combat tick count
 @param {number|null=} tick_delay - additional real-time delay (seconds) AFTER tick is reached
*/
SPFX.When = function(time, tick, tick_delay) {
    if(time !== null && tick !== null) { throw Error('either time or tick must be null'); }
    this.time = time;
    this.tick = tick || null;
    this.tick_delay = tick_delay || 0;
};

/** @param {!SPFX.When} a
    @param {!SPFX.When} b
    @return {boolean} */
SPFX.When.equal = function(a, b) {
    if(a.time !== null) {
        return a.time === b.time;
    } else if(a.tick !== null) {
        return (b.tick !== null) && GameTypes.TickCount.equal(a.tick, b.tick) && (a.tick_delay === b.tick_delay);
    }
    throw Error('bad When values');
};

/** @type {number} */
SPFX.last_id = 0;

/** @type {number} */
SPFX.detail = 1;

SPFX.global_gravity = 1;
SPFX.global_ground_plane = 0;

// hack to fake z-ordering - there are several "layers" of effects

/** @type {!Object.<string,!SPFX.Effect>} */
SPFX.current_under = {}; // underneath units/buildings

/** @type {!Object.<string,!SPFX.PhantomUnit>} */
SPFX.current_phantoms = {}; // phantom units/buildings managed by SPFX

/** @type {!Object.<string,!SPFX.Effect>} */
SPFX.current_over = {}; // on top of units/buildings, below UI

/** @type {!Object.<string,!SPFX.Effect>} */
SPFX.current_ui = {}; // on top of UI

/** @type {!Object.<string,!SPFX.Field>} */
SPFX.fields = {}; // force fields only

/** @typedef {{when: !SPFX.When, amplitude: number, falloff: number, started_at: number}} */
SPFX.ShakeImpulse;

/** @type {Array.<!SPFX.ShakeImpulse>} */
SPFX.shake_impulses = [];

/** @type {?ShakeSynth.Shake} */
SPFX.shake_synth = null;

SPFX.shake_origin_time = -1;

// SPFX

/** @param {!CanvasRenderingContext2D} ctx
    @param {boolean} use_low_gfx
    @param {boolean} use_high_gfx */
SPFX.init = function(ctx, use_low_gfx, use_high_gfx) {
    SPFX.ctx = ctx;
    SPFX.time = 0;
    SPFX.tick = new GameTypes.TickCount(0);
    SPFX.last_tick = new GameTypes.TickCount(0);
    SPFX.last_tick_time = 0;

    SPFX.last_id = 0;

    // turn down number of particles/sprites for higher performance
    if(use_low_gfx) {
        SPFX.detail = gamedata['client']['graphics_detail']['low'];
    } else if(use_high_gfx) {
        SPFX.detail = gamedata['client']['graphics_detail']['high'];
    } else {
        SPFX.detail = gamedata['client']['graphics_detail']['default'];
    }

    if('sound_throttle' in gamedata['client']) { SPFX.sound_throttle = /** @type {number} */ (gamedata['client']['sound_throttle']); }

    SPFX.clear();

    SPFX.shake_synth = new ShakeSynth.Shake(0);
    SPFX.shake_origin_time = SPFX.time;
};

/** @param {number} time
    @param {!GameTypes.TickCount} tick */
SPFX.set_time = function(time, tick) {
    SPFX.time = time;
    SPFX.tick = tick;
    if(GameTypes.TickCount.gt(SPFX.tick, SPFX.last_tick)) {
        SPFX.last_tick = SPFX.tick;
        SPFX.last_tick_time = SPFX.time;
    }
};

/** @param {!SPFX.When} t
    @return {boolean} */
SPFX.time_lt = function(t) {
    if(t.tick) {
        if(GameTypes.TickCount.lt(SPFX.tick, t.tick)) {
            return true;
        }
        // we've reached the tick. Do we need an additional delay?
        if(t.tick_delay > 0) {
            if(GameTypes.TickCount.equal(SPFX.tick, t.tick)) {
                // MUTATE t to a time value tick_delay into the future
                t.time = SPFX.last_tick_time + t.tick_delay;
                t.tick = null;
                return SPFX.time < t.time;
            } else {
                return false; // we skipped a tick - fire immediately
            }
        }
        return false;
    } else {
        return SPFX.time < t.time;
    }
};

/** @param {!SPFX.When} t
    @return {boolean} */
SPFX.time_gte = function(t) { return !SPFX.time_lt(t); };

/** only allow non-default compositing modes when detail > 1
    @param {string} mode */
SPFX.set_composite_mode = function(mode) {
    if(SPFX.detail > 1) {
        SPFX.ctx.globalCompositeOperation = mode;
    }
};

/** @private
    @param {!Object.<string, !SPFX.FXObject>} layer
    @param {!SPFX.FXObject} effect */
SPFX.do_add = function(layer, effect) {
    effect.id = SPFX.last_id.toString();
    SPFX.last_id += 1;
    layer[effect.id] = effect;
};

/** @param {!SPFX.Effect} effect
    @return {!SPFX.Effect} */
SPFX.add = function(effect) { SPFX.do_add(SPFX.current_over, effect); return effect; };
/** @param {!SPFX.PhantomUnit} effect
    @return {!SPFX.PhantomUnit} */
SPFX.add_phantom = function(effect) { SPFX.do_add(SPFX.current_phantoms, effect); return effect; };
/** @param {!SPFX.Effect} effect
    @return {!SPFX.Effect} */
SPFX.add_under = function(effect) { SPFX.do_add(SPFX.current_under, effect); return effect; };
/** @param {!SPFX.Effect} effect
    @return {!SPFX.Effect} */
SPFX.add_ui = function(effect) { SPFX.do_add(SPFX.current_ui, effect); return effect; };
/** @param {!SPFX.Field} effect
    @return {!SPFX.Field} */
SPFX.add_field = function(effect) { SPFX.do_add(SPFX.fields, effect); return effect; };

/** @param {!SPFX.FXObject} effect */
SPFX.remove = function(effect) {
    effect.dispose();

    if(effect.id in SPFX.current_over) {
        delete SPFX.current_over[effect.id];
    } else if(effect.id in SPFX.current_phantoms) {
        delete SPFX.current_phantoms[effect.id];
    } else if(effect.id in SPFX.current_under) {
        delete SPFX.current_under[effect.id];
    } else if(effect.id in SPFX.current_ui) {
        delete SPFX.current_ui[effect.id];
    } else if(effect.id in SPFX.fields) {
        delete SPFX.fields[effect.id];
    }
};

SPFX.clear = function() {
    SPFX.current_over = {};
    SPFX.current_under = {};
    SPFX.current_phantoms = {};
    SPFX.current_ui = {};
    SPFX.fields = {};
    SPFX.shake_impulses = [];
};

SPFX.draw_over = function() {
    for(var id in SPFX.current_over) {
        SPFX.current_over[id].draw();
    }
};
SPFX.draw_under = function() {
    for(var id in SPFX.current_under) {
        SPFX.current_under[id].draw();
    }
};
SPFX.draw_ui = function() {
    for(var id in SPFX.current_ui) {
        SPFX.current_ui[id].draw();
    }
};
SPFX.get_phantom_objects = function() {
    var ret = [];
    goog.array.forEach(goog.object.getValues(SPFX.current_phantoms), function(fx) {
        var obj = (/** @type {SPFX.PhantomUnit} */ (fx)).get_phantom_object(); // will throw if it's not a SPFX.PhantomUnit
        if(obj === null) { // done
            SPFX.remove(fx);
        } else {
            ret.push(obj);
        }
    });
    return ret;
};

SPFX.get_camera_shake = function() {
    if(SPFX.shake_impulses.length < 1) { return [0,0,0]; }

    if(SPFX.shake_origin_time < 0) {
        SPFX.shake_origin_time = SPFX.time + 10.0*Math.random();
    }

    // sum impulse response
    var total_amp = 0.0;
    for(var i = 0; i < SPFX.shake_impulses.length; i++) {
        var imp = SPFX.shake_impulses[i];

        if(imp.started_at < 0) { // check for start time/tick
            if(SPFX.time_gte(imp.when)) {
                // once the shake starts, use time only
                imp.started_at = SPFX.time;
            }
        }

        if(imp.started_at > 0) {
            var exponent = (SPFX.time-imp.started_at)/imp.falloff;
            if(exponent > 4.0) { // too late, no longer needed
                SPFX.shake_impulses.splice(i, 1);
                continue;
            }
            total_amp += imp.amplitude * Math.exp(-exponent);
        }
    }
    if(Math.abs(total_amp) >= 0.0001) {
        var v = SPFX.shake_synth.evaluate(24.0*(SPFX.time-SPFX.shake_origin_time));
        return [total_amp*v[0], total_amp*v[1], total_amp*v[2]];
    }
    return [0,0,0];
};

/** @param {!SPFX.When} when
    @param {number} amplitude
    @param {number} falloff */
SPFX.shake_camera = function(when, amplitude, falloff) {
    SPFX.shake_impulses.push({when:when, amplitude: gamedata['client']['camera_shake_scale']*amplitude, falloff:falloff, started_at: -1});
};

/** @constructor
    @struct */
SPFX.FXObject = function() {
    /** @type {string} */
    this.id = '';
};
/** Repositions this object in the game world. Useful when attaching effects to a moving object.
    @param {!Array.<number>} xyz
    @param {number=} rotation */
SPFX.FXObject.prototype.reposition = function(xyz, rotation) {};
/** Called by SPFX.remove to perform any work needed to cleanly remove this object. */
SPFX.FXObject.prototype.dispose = function() {};

/** @constructor
    @struct
    @extends SPFX.FXObject
    @param {?string=} charge */
SPFX.Field = function(charge) {
    goog.base(this);
    this.charge = charge;
};
goog.inherits(SPFX.Field, SPFX.FXObject);

/** @param {!Array.<number>} pos
    @param {!Array.<number>} vel
    @return {!Array.<number>} */
SPFX.Field.prototype.eval_field = goog.abstractMethod;

// MagnetField
/** @constructor
    @struct
    @param {!Array.<number>} pos
    @param {!Object} data
    @param {Object|null|undefined} instance_data
    @extends SPFX.Field */
SPFX.MagnetField = function(pos, data, instance_data) {
    goog.base(this, ('charge' in data ? /** @type {string} */ (data['charge']) : null));
    this.pos = pos; // note: in 3D here
    this.strength = ('strength' in data ? /** @type {number} */ (data['strength']) : 10.0);
    this.strength_3d = ('strength_3d' in data ? /** @type {!Array.<number>} */ (data['strength_3d']) : [1,1,1]);
    this.falloff = ('falloff' in data ? /** @type {number} */ (data['falloff']) : 0);
    this.falloff_rim = ('falloff_rim' in data ? /** @type {number} */ (data['falloff_rim']) : 0);
};
goog.inherits(SPFX.MagnetField, SPFX.Field);

/** @override
    @param {!Array.<number>} pos
    @param {!Array.<number>} vel
    @return {!Array.<number>} */
SPFX.MagnetField.prototype.eval_field = function(pos, vel) {
    var str = this.strength;
    var ray = v3_sub(pos, this.pos);
    if(this.falloff != 0) {
        var r = v3_length(ray);
        r = Math.max(r, this.falloff_rim);
        str *= Math.pow(r, this.falloff);
    }
    return v3_mul(v3_scale(-str, this.strength_3d), ray);
};
/** @override
    @param {!Array.<number>} xyz
    @param {number=} rotation */
SPFX.MagnetField.prototype.reposition = function(xyz, rotation) {
    this.pos = xyz;
};

/** @constructor
    @struct
    @param {!Array.<number>} pos
    @param {!Object} data
    @param {Object|null|undefined} instance_data
    @extends SPFX.Field */
SPFX.DragField = function(pos, data, instance_data) {
    goog.base(this, ('charge' in data ? /** @type {string} */ (data['charge']) : null));
    this.strength = ('strength' in data ? /** @type {number} */ (data['strength']) : 1.0);
};
goog.inherits(SPFX.DragField, SPFX.Field);

/** @override
    @param {!Array.<number>} pos
    @param {!Array.<number>} vel
    @return {!Array.<number>} */
SPFX.DragField.prototype.eval_field = function(pos, vel) {
    var spd = v3_length(vel);
    return v3_scale(-spd*this.strength, vel);
};

// Effect

/** @constructor
    @struct
    @param {Object|null=} data
    @extends SPFX.FXObject */
SPFX.Effect = function(data) {
    goog.base(this);
    this.data = data || null;
    this.user_data = null;
};
goog.inherits(SPFX.Effect, SPFX.FXObject);

SPFX.Effect.prototype.draw = function() {};

// CoverScreen
/** @constructor
    @struct
    @param {string} color_str
*/
SPFX.CoverScreen = function(color_str) {
    this.color_str = color_str;
};

SPFX.CoverScreen.prototype.draw = function() {
    SPFX.ctx.save();
    SPFX.ctx.fillStyle = this.color_str;
    SPFX.ctx.fillRect(0,0, canvas_width, canvas_height);
    SPFX.ctx.restore();
};

/** @constructor
  * @extends SPFX.Effect
  * @param {Array.<SPFX.Effect>=} effects */
SPFX.CombineEffect = function(effects) {
    goog.base(this, null);

    /** @type {!Array.<!SPFX.Effect>} */
    this.effects = effects || [];
};
goog.inherits(SPFX.CombineEffect, SPFX.Effect);

SPFX.CombineEffect.prototype.draw = function() {
    // SPFX maintains handles to each child effect so we don't need to draw them here
};

/** @override
    @param {!Array.<number>} xyz
    @param {number=} rotation */
SPFX.CombineEffect.prototype.reposition = function(xyz, rotation) {
    var len = this.effects.length;
    for(var i = 0; i < len; i++) {
        this.effects[i].reposition(xyz, rotation);
    }
};

SPFX.CombineEffect.prototype.dispose = function() {
    var len = this.effects.length;
    for(var i = 0; i < len; i++) {
        SPFX.remove(this.effects[i]);
    }
};

// Particle system

/** @constructor
  * @extends SPFX.Effect
  * @param {Array.<number>|null} spawn_pos
  * @param {!SPFX.When} when
  * @param {number} duration
  * @param {Object} data
  * @param {Object=} instance_data
  */
SPFX.Particles = function(spawn_pos, when, duration, data, instance_data) {
    goog.base(this, data);
    this.spawn_pos = v3_add(spawn_pos || [0, 0, 0], (data && 'offset' in data) ? /** @type {!Array.<number>} */ (data['offset']) : [0, 0, 0]);
    this.spawn_radius = (instance_data && 'radius' in instance_data ? /** @type {number} */ (instance_data['radius']) : 1) * (('radius' in this.data ? /** @type {number} */ (this.data['radius']) : 0));
    this.draw_mode = ('draw_mode' in data? /** @type {string} */ (data['draw_mode']) : ('child' in data ? 'none' : 'lines'));
    this.max_age = ('max_age' in data ? /** @type {number} */ (data['max_age']) : 0.5);
    this.child_data = ('child' in data ? /** @type {!Object} */ (data['child']) : null);

    if(SPFX.detail > 1) {
        this.max_age *= 1.2; // increase max_age to compensate for particles fading out individually
    }

    this.emit_instant_done = false;
    this.emit_pattern = ('emit_pattern' in this.data ? /** @type {string} */ (this.data['emit_pattern']) : 'square');
    this.emit_by_area = ('emit_by_area' in this.data ? /** @type {number} */ (this.data['emit_by_area']) : 0);
    this.emit_continuous_rate = ('emit_continuous_rate' in this.data ? /** @type {number} */ (this.data['emit_continuous_rate']) : 0);
    this.emit_continuous_for = ('emit_continuous_for' in this.data ? /** @type {number} */ (this.data['emit_continuous_for']) : 0);
    this.emit_continuous_residual = Math.random();

    this.when = when;
    this.duration = duration;
    this.start_time = -1; // determined after start
    this.end_time = -1;
    this.last_time = -1;

    /** @type {!Array.<number>} */
    var col = ('color' in data ? /** @type {!Array.<number>} */ (data['color']) : [0,1,0,1]);
    if(col.length == 4) {
        // good
    } else if(col.length == 3) {
        col = [col[0],col[1],col[2],1];
    } else {
        log_exception(null, 'SPFX particles with bad color length '+col.length.toString()+' value '+col[0].toString()+','+col[1].toString()+','+col[2].toString());
        col = [1,1,1,1];
    }

    this.color = new SPUI.Color(col[0],col[1],col[2],col[3]);
    this.accel = [0,
                  SPFX.global_gravity * ('gravity' in data ? /** @type {number} */ (data['gravity']) : -25),
                  0];
    this.collide_ground = ('collide_ground' in data ? /** @type {boolean} */ (data['collide_ground']) : true);
    this.elasticity = ('elasticity' in data ? /** @type {number} */ (data['elasticity']) : 0.5);
    this.nmax = ('max_count' in data ? /** @type {number} */ (data['max_count']) : 50); // max number of particles
    this.nnext = 0;
    this.line_width =  ('width' in data ? /** @type {number} */ (data['width']) : 2);
    this.min_length = ('min_length' in data ? /** @type {number} */ (data['min_length']) : 0);
    this.fixed_length = ('fixed_length' in data ? /** @type {number} */ (data['fixed_length']) : 0);
    this.spin_rate = (Math.PI/180) * ('spin_rate' in data ? /** @type {number} */ (data['spin_rate']) : 0);

    if('opacity' in data) {
        this.opacity = /** @type {number} */ (data['opacity']);
    } else {
        this.opacity = 1;
    }
    this.fade_power = ('fade_power' in data ? /** @type {number} */ (data['fade_power']) : 1);
    this.composite_mode = ('composite_mode' in data ? /** @type {string} */ (data['composite_mode']) : 'source-over');

    this.charge = ('charge' in data ? /** @type {string} */ (data['charge']) : null); // charge for field interactions

    this.spawn_count = 0;
    this.pp_age = false; // whether or not age[i] varies between particles
    this.pp_state = false; // whether or not to change graphics state between drawing each particle (SLOW!)

    this.pos = [];
    this.vel = [];

    // per-particle rotations
    /** @type {Array.<!Array.<number>>|null} */
    this.axis = (this.spin_rate > 0 ? [] : null);
    /** @type {Array.<number>|null} */
    this.angle = (this.spin_rate > 0 ? [] : null);
    /** @type {Array.<number>|null} */
    this.angle_v = (this.spin_rate > 0 ? [] : null);
    /** @type {!Array.<number>} */
    this.age = [];
    /** @type {Array.<SPFX.FXObject|null>|null} */
    this.children = (this.child_data !== null ? [] : null);
};
goog.inherits(SPFX.Particles, SPFX.Effect);

/** @override
    @param {!Array.<number>} xyz
    @param {number=} rotation */
SPFX.Particles.prototype.reposition = function(xyz, rotation) {
    if(this.data && 'offset' in this.data) {
        this.spawn_pos = v3_add(xyz, /** @type {!Array.<number>} */ (this.data['offset']));
    } else {
        this.spawn_pos = xyz;
    }
};

/** @param {!Array.<number>} pos
    @param {number} dpos
    @param {!Array.<number>} vel
    @param {number} dvel
    @param {!Array.<number>} dvel_scale
    @param {number} count */
SPFX.Particles.prototype.spawn = function(pos, dpos, vel, dvel, dvel_scale, count) {
    if(this.spawn_count > 0) {
        // if particles are spawned more than once, it means the age is no longer global, so we have to turn on pp_age
        this.pp_age = true;
        if(SPFX.detail > 1) {
            this.pp_state = true;
        }
    }
    this.spawn_count += 1;

    if(this.emit_by_area) {
        // scale up the number of particles to spawn by the dpos area
        if(dpos > 1) {
            count *= Math.min(5, dpos*dpos);
        }
    }

    for(var i = 0; i < count; i++) {
        /** @type {!Array.<number>} */
        var p = [pos[0], pos[1], pos[2]];
        if(dpos != 0) {
            // randomize spawn location
            var dx, dz;
            if(this.emit_pattern == 'square') {
                dx = (2*Math.random()-1); dz = (2*Math.random()-1);
            } else if(this.emit_pattern == 'circle') {
                var theta = 2*Math.PI*Math.random(), r = Math.sqrt(Math.random());
                dx = r*Math.cos(theta); dz = r*Math.sin(theta);
            } else {
                throw Error('unknown emit_pattern '+this.emit_pattern);
            }
            p[0] += dpos * dx;
            //p[1] += dpos * (2*Math.random()-1);
            p[2] += dpos * dz;
        }

        // randomize spawn velocity
        var v = [vel[0] + dvel * dvel_scale[0] * (2*Math.random() - 1),
                 vel[1] + dvel * dvel_scale[1] * (2*Math.random() - 1),
                 vel[2] + dvel * dvel_scale[2] * (2*Math.random() - 1)
                ];

        // randomize spawn rotation axis and angular velocity

        /** @type {Array.<number>|null} */
        var ax = null;
        var an = 0, anv = 0;

        if(this.spin_rate > 0) {
            ax = [0,0,1];
            an = 2*Math.PI*Math.random();
            anv = (0.5 + 1.0 * Math.random()) * this.spin_rate;
        }

        // spawn child effect
        var c = null;
        if(this.child_data) {
            var props = null;
            if(this.spin_rate > 0) {
                props = {'rotation': (180.0/Math.PI)*an, 'rotate_speed': (180.0/Math.PI)*anv};
            }
            // note: c may be null
            c = SPFX.add_visual_effect_at_time([p[0],p[2]], p[1], [0,1,0], SPFX.time, this.child_data, true, props);
        }

        if(this.pos.length < this.nmax) {
            this.pos.push(p);
            this.vel.push(v);
            this.age.push(0);
            if(ax !== null) {
                this.axis.push(ax);
                this.angle.push(an);
                this.angle_v.push(anv);
            }
            if(this.child_data) { this.children.push(c); }
        } else {
            this.pos[this.nnext] = p;
            this.vel[this.nnext] = v;
            this.age[this.nnext] = 0;
            if(ax !== null) {
                this.axis[this.nnext] = ax;
                this.angle[this.nnext] = an;
                this.angle_v[this.nnext] = anv;
            }
            if(this.child_data) { this.children[this.nnext] = c; }
            this.nnext = (this.nnext+1) % this.nmax;
        }
    }
};
SPFX.Particles.prototype.draw = function() {
    if(SPFX.time_lt(this.when)) { return; }
    if(this.start_time < 0) {
        this.start_time = this.last_time = SPFX.time;
        this.end_time = (this.emit_continuous_for >= 0 ? (this.start_time + this.duration + this.max_age + this.emit_continuous_for) : -1);
    }

    if(this.end_time >= 0 && SPFX.time > this.end_time) { SPFX.remove(this); return; }

    if(!this.emit_instant_done && ('emit_instant' in this.data) && /** @type {number} */ (this.data['emit_instant']) > 0) {
        this.spawn(this.spawn_pos,
                   this.spawn_radius,
                   v3_scale(this.data['speed'], ('emit_orient' in this.data ? /** @type {!Array.<number>} */ (this.data['emit_orient']) : [0,1,0])),
                   ('speed_random' in this.data ? /** @type {number} */ (this.data['speed_random']) : ('speed' in this.data ? /** @type {number} */ (this.data['speed']) : 0)),
                   ('speed_random_scale' in this.data ? /** @type {!Array.<number>} */ (this.data['speed_random_scale']) : [1,1,1]),
                   Math.floor(Math.min(SPFX.detail, 1) * /** @type {number} */ (this.data['emit_instant'])));
        this.emit_instant_done = true;
    }

    var dt = SPFX.time - this.last_time;
    this.run_physics(dt);
    this.last_time = SPFX.time;

    if(this.emit_continuous_rate > 0 && (this.emit_continuous_for < 0 || SPFX.time - this.start_time < this.emit_continuous_for)) {
        // continuous particle emission
        var num_to_emit = this.emit_continuous_rate*dt;
        num_to_emit = Math.min(SPFX.detail, 1)*num_to_emit;

        // with fractional num_to_emit, smooth it out over time to
        // maintain the correct average spawn rate without frame-time-dependent "clumping".
        var frac = num_to_emit - Math.floor(num_to_emit);
        num_to_emit = Math.floor(num_to_emit);
        if(frac > 0) {
            if(this.emit_continuous_residual >= 1/frac) {
                num_to_emit += 1;
                this.emit_continuous_residual = 0;
            } else {
                this.emit_continuous_residual += 1;
            }
        }
        if(num_to_emit >= 1) {
            this.spawn(this.spawn_pos,
                       this.spawn_radius,
                       v3_scale(this.data['speed'], ('emit_orient' in this.data ? /** @type {!Array.<number>} */ (this.data['emit_orient']) : [0,1,0])),
                       ('speed_random' in this.data ? /** @type {number} */ (this.data['speed_random']) : ('speed' in this.data ? /** @type {number} */ (this.data['speed']) : 0)),
                       ('speed_random_scale' in this.data ? /** @type {!Array.<number>} */ (this.data['speed_random_scale']) : [1,1,1]),
                       num_to_emit);
        }
    }

    if(this.draw_mode != null && this.draw_mode != 'none') {
        // motion blur streak length - by default 50% of time interval to simulate 1/48th
        // shutter, but don't let it get too large if framerate drops
        var strokelen;
        if(this.fixed_length > 0) {
            strokelen = 0;
        } else {
            strokelen = Math.max(0.5 * Math.min(dt, 0.05), this.min_length);
        }

        SPFX.ctx.save();
        SPFX.ctx.strokeStyle = this.color.str();
        SPFX.ctx.lineWidth = this.line_width;
        SPFX.set_composite_mode(this.composite_mode);

        if(this.opacity < 1 || !this.pp_age) {
            var op = this.opacity;
            if(!this.pp_age) {
                op *= Math.pow(1.0 - (SPFX.time - this.start_time) / this.max_age, this.fade_power);
            }
            op = Math.min(Math.max(op, 0), 1);
            SPFX.ctx.globalAlpha = op;
        }

        if(this.draw_mode == 'lines' && !this.pp_state) {
            SPFX.ctx.beginPath();
        } else if(this.draw_mode == 'circles') {
            var grad = SPFX.ctx.createRadialGradient(0, 0, 0, 0, 0, this.line_width);
            grad.addColorStop(0.0, this.color.str());
            var transp = new SPUI.Color(this.color.r, this.color.g, this.color.b, 0.0);
            grad.addColorStop(1.0, transp.str());
            SPFX.ctx.fillStyle = grad;
        }

        for(var i = 0; i < this.pos.length; i++) {
            if(this.age[i] > this.max_age) { continue; }

            if(1 /*|| this.pos[i][1] > 0*/) {
                var xy, xy2; // endpoints of line to draw

                if(this.fixed_length > 0) {
                    // draw line representing a solid "pipe"
                    var a = (this.spin_rate > 0 ? this.angle[i] : 0);
                    var c = Math.cos(a), s = Math.sin(a);
                    var v = [c,s,0]; // unit vector along long axis of object body, in 3D space
                    // XXX this should eventually use the right 3D math for arbitrary axes and angles
                    xy = ortho_to_draw_3d(v3_add(this.pos[i], v3_scale(-0.5*this.fixed_length, v)));
                    xy2 = ortho_to_draw_3d(v3_add(this.pos[i], v3_scale(0.5*this.fixed_length, v)));
                } else {
                    // draw motion blur streak
                    xy = ortho_to_draw_3d(this.pos[i]);
                    xy2 = ortho_to_draw_3d(v3_add(this.pos[i], v3_scale(strokelen, this.vel[i])));
                }

                if(this.draw_mode == 'lines') {
                    if(!view_is_zoomed()) { quantize_streak(xy, xy2); }
                    if(this.pp_state) {
                        if(this.pp_age) {
                            var a = Math.pow(Math.min(Math.max(this.opacity * (1.0 - (1.0*this.age[i])/this.max_age),0),1), this.fade_power);
                            SPFX.ctx.globalAlpha = a;
                        }
                        SPFX.ctx.beginPath();
                    }
                    SPFX.ctx.moveTo(xy[0], xy[1]);
                    SPFX.ctx.lineTo(xy2[0], xy2[1]);
                    if(this.pp_state) {
                        SPFX.ctx.stroke();
                    }
                } else if(this.draw_mode == 'circles') {
                    if(!view_is_zoomed() && SPFX.detail <= 1) { quantize_streak(xy, xy2); }
                    var progress = Math.max(0.2, this.age[i] / this.max_age);
                    SPFX.ctx.globalAlpha = this.opacity * (1.0-progress);
                    var rad = progress * this.line_width;
                    SPFX.ctx.save();
                    SPFX.ctx.transform(1, 0, 0, 1, xy[0], xy[1]);
                    SPFX.ctx.fillRect(-rad, -rad, 2*rad, 2*rad);
                    SPFX.ctx.restore();
                }
            }
        }

        if(this.draw_mode == 'lines' && !this.pp_state) {
            SPFX.ctx.stroke();
        }

        SPFX.ctx.restore();
    }
};

/** @param {number} dt - time delta since last step */
SPFX.Particles.prototype.run_physics = function(dt) {
    if(dt <= 0) { return; }

    for(var i = 0; i < this.pos.length; i++) {
        if(this.age[i] > this.max_age) { continue; }

        // bounce off the ground
        if(this.collide_ground && this.pos[i][1] < SPFX.global_ground_plane) {
            this.pos[i][1] = 0.001;
            this.vel[i][0] *= this.elasticity;
            this.vel[i][1] *= -this.elasticity;
            this.vel[i][2] *= this.elasticity;
            if(this.spin_rate > 0) {
                this.angle_v[i] *= -this.elasticity;
            }
        }

        var forces = this.accel;
        for(var id in SPFX.fields) {
            var field = SPFX.fields[id];
            if(field.charge !== this.charge) { continue; }
            forces = v3_add(forces, field.eval_field(this.pos[i], this.vel[i])); /* times mass, of course */
        }

        this.pos[i] = v3_add(this.pos[i], v3_scale(dt, this.vel[i]));
        this.vel[i] = v3_add(this.vel[i], v3_scale(dt, forces));
        this.age[i] += dt;

        if(this.spin_rate > 0) {
            this.angle[i] += this.angle_v[i] * dt;
        }

        // update children
        if(this.children !== null && this.children[i]) {
            this.children[i].reposition(this.pos[i], (this.spin_rate > 0 ? this.angle[i] : 0));
        }
    }
};

// TimeProjectile

/** @constructor
    @struct
    @extends SPFX.Effect
    @param {!Array.<number>} from
    @param {number} from_height
    @param {!Array.<number>} to
    @param {number} to_height
    @param {number} launch_time
    @param {number} impact_time
    @param {number} max_height
    @param {!Array.<number>} color
    @param {Object|null} exhaust
    @param {number} line_width
    @param {number} min_length
    @param {number} fade_time
    @param {string} comp_mode
    @param {number} glow
    @param {string|null} asset
*/
SPFX.TimeProjectile = function(from, from_height, to, to_height, launch_time, impact_time, max_height, color, exhaust, line_width, min_length, fade_time, comp_mode, glow, asset) {
    goog.base(this, null);
    this.from = from;
    this.to = to;
    this.launch_time = launch_time;
    this.impact_time = impact_time;
    this.launch_height = 0.5 + from_height;
    this.to_height = to_height;
    this.max_height = max_height;
    this.line_width = line_width;
    this.min_length = min_length;
    this.fade_time = fade_time;
    this.composite_mode = comp_mode || 'source-over';
    this.glow = glow;
    this.asset = asset;

    this.last_time = launch_time;
    this.color_str = (new SPUI.Color(color[0], color[1], color[2], 1.0)).str();

    if(this.impact_time != this.launch_time) {
        this.tscale = 1/(this.impact_time-this.launch_time);
    } else {
        this.tscale = 1000.0;
    }

    var shot_d = vec_sub(to, this.from);
    var shot_len = vec_length(shot_d);
    var shot_dir = vec_scale(1/shot_len, shot_d);
    this.shot_vel = vec_scale(shot_len * this.tscale, shot_dir);

    if(exhaust) {
        // exhaust particles
        this.particles = new SPFX.Particles(null, new SPFX.When(launch_time, null), impact_time - launch_time, exhaust); // should_be_tick
        this.exhaust_speed = ('speed' in exhaust ? /** @type {number} */ (exhaust['speed']) : 0);
        this.exhaust_dvel = ('randomize_vel' in exhaust ? /** @type {number} */ (exhaust['randomize_vel']) : 0) * this.exhaust_speed;
        this.exhaust_vel = vec_scale(-this.exhaust_speed, shot_dir);
        this.exhaust_rate = Math.floor(Math.min(SPFX.detail, 1) * ('emit_rate' in exhaust ? /** @type {number} */ (exhaust['emit_rate']) : 60));
        SPFX.add(this.particles);
    } else {
        this.particles = null;
    }
};
goog.inherits(SPFX.TimeProjectile, SPFX.Effect);

SPFX.TimeProjectile.prototype.draw_beam = function() {
    var stroke_start = ortho_to_draw_3d([this.from[0], this.launch_height, this.from[1]]);
    var stroke_end = ortho_to_draw_3d([this.to[0], this.to_height, this.to[1]]);

    // quantize to pixels
    quantize_streak(stroke_start, stroke_end);

    var fade = 1;
    if(this.fade_time > 0) {
        fade = 1 - (SPFX.time - this.launch_time) / this.fade_time;
        if(fade <= 0) {
            return;
        }
    }

    SPFX.ctx.save();

    if(1) {
        SPFX.ctx.globalAlpha = fade;
        SPFX.set_composite_mode(this.composite_mode);
        SPFX.ctx.strokeStyle = this.color_str;
        SPFX.ctx.lineWidth = this.line_width;
        SPFX.ctx.beginPath();
        SPFX.ctx.moveTo(stroke_start[0], stroke_start[1]);
        SPFX.ctx.lineTo(stroke_end[0], stroke_end[1]);
        SPFX.ctx.stroke();
    }

    SPFX.ctx.restore();
};

SPFX.TimeProjectile.prototype.draw = function() {
    if(SPFX.time < this.launch_time) {
        return;
    }

    if(SPFX.time > this.impact_time + this.fade_time) {
        SPFX.remove(this);
        return;
    }

    if(this.min_length > 100.0) {
        // draw as solid beam instead of projectile
        return this.draw_beam();
    }

    var t = SPFX.time - this.launch_time;
    var dt = SPFX.time - this.last_time;

    // compute x,y ground position
    var pos = vec_mad(this.from, t, this.shot_vel);

    // parabolic arc
    var height = this.launch_height + this.max_height * (1 - ((t*this.tscale-0.5)*(t*this.tscale-0.5))/0.25) + t*this.tscale * (this.to_height - this.launch_height);
    // derivative of above with respect to t
    var dheight_dt = -8 * this.max_height * (t*this.tscale - 0.5) * this.tscale + this.tscale * (this.to_height - this.launch_height);

    // spawn exhaust particles
    if(this.particles) {
        var num_particles = Math.min(0.10, dt) * this.exhaust_rate;
        var int_particles = Math.floor(num_particles);
        var frac_particles = num_particles - int_particles;
        if(Math.random() < frac_particles) {
            int_particles += 1;
        }
        for(var i = 0; i < int_particles; i++) {
            var pt = t - Math.random()*dt;
            var ppos = vec_mad(this.from, pt, this.shot_vel);
            var vel = this.exhaust_vel;
            /** @type {!Array.<number>} */
            var spawn_loc = [ppos[0], height, ppos[1]];
            if(this.particles.spawn_radius > 0) {
                for(var axis = 0; axis < 3; axis++) {
                    spawn_loc[i] += this.particles.spawn_radius * (2*Math.random()-1);
                }
            }
            this.particles.spawn(spawn_loc, 0, [vel[0], 0, vel[1]], this.exhaust_dvel, [1,1,1], 1);
        }
    }

    // motion blur streak length - by default 50% of time interval to simulate 1/48th
    // shutter, but don't let it get too large if framerate drops
    var sdt = 0.5 * Math.min(dt, 0.05);

    var stroke_start = ortho_to_draw_3d([pos[0], height, pos[1]]);
    var stroke_end_pos = vec_mad(pos, sdt, this.shot_vel);
    var stroke_end_height = height + sdt * dheight_dt;
    var stroke_end = ortho_to_draw_3d([stroke_end_pos[0], stroke_end_height, stroke_end_pos[1]]);

    if(this.min_length > 0) {
        var len = vec_distance(stroke_start, stroke_end);
        if(len < this.min_length && len > 0) {
            stroke_end = vec_mad(stroke_start, this.min_length/len, vec_sub(stroke_end, stroke_start));
        }
    }

    SPFX.ctx.save();

    // quantize to pixels
    quantize_streak(stroke_start, stroke_end);

    if(this.glow > 0 && SPFX.detail > 1) {

        SPFX.set_composite_mode(/** @type {string|undefined} */ (gamedata['client']['projectile_glow_mode']) || 'source-over');
        var glow_asset_name = 'fx/glows';
        var glow_asset = GameArt.assets[glow_asset_name]
        var glow_sprite = /** @type {!GameArt.Sprite} down-cast from AbstractSprite */ (glow_asset.states['normal']);
        var glow_image = glow_sprite.images[0];

        // primary glow
        SPFX.ctx.globalAlpha = this.glow*gamedata['client']['projectile_glow_intensity'];
        glow_image.draw([stroke_end[0]-Math.floor(glow_image.wh[0]/2),
                         stroke_end[1]-Math.floor(glow_image.wh[1]/2)]);

        // secondary, fainter glow
        SPFX.ctx.globalAlpha = this.glow*0.56*gamedata['client']['projectile_glow_intensity'];
        glow_image = glow_sprite.images[1];
        glow_image.draw([stroke_end[0]-Math.floor(glow_image.wh[0]/2),
                         stroke_end[1]-Math.floor(glow_image.wh[1]/2)]);

        SPFX.ctx.globalAlpha = 1;
        SPFX.set_composite_mode('source-over');
    }

    if(this.asset) {
        var sprite = GameArt.assets[this.asset].states['normal'];
        sprite.draw(stroke_start, 0, SPFX.time);
    } else {
        SPFX.ctx.strokeStyle = this.color_str;
        SPFX.ctx.lineWidth = this.line_width;
        SPFX.set_composite_mode(this.composite_mode);
        SPFX.ctx.beginPath();
        SPFX.ctx.moveTo(stroke_start[0], stroke_start[1]);
        SPFX.ctx.lineTo(stroke_end[0], stroke_end[1]);
        SPFX.ctx.stroke();
    }

    SPFX.ctx.restore();

    this.last_time = SPFX.time;
};

// TicksProjectile

/** @constructor
    @struct
    @extends SPFX.Effect
    @param {!Array.<number>} from
    @param {number} from_height
    @param {!Array.<number>} to
    @param {number} to_height
    @param {!GameTypes.TickCount} launch_tick
    @param {!GameTypes.TickCount} impact_tick
    @param {number} tick_delay - additional delay in seconds after impact_tick/launch_time for graphics offset
    @param {number} max_height
    @param {!Array.<number>} color
    @param {Object|null} exhaust
    @param {number} line_width
    @param {number} min_length
    @param {number} fade_time
    @param {string} comp_mode
    @param {number} glow
    @param {string|null} asset
*/
SPFX.TicksProjectile = function(from, from_height, to, to_height, launch_tick, impact_tick, tick_delay, max_height, color, exhaust, line_width, min_length, fade_time, comp_mode, glow, asset) {
    goog.base(this, null);

    if(SPFX.TicksProjectile.DEBUG) {
        console.log("TicksProjectile launch_tick "+launch_tick.get().toString()+" impact_tick "+impact_tick.get().toString()+" tick_delay "+tick_delay.toString());
    }

    this.from = from;
    this.to = to;
    this.launch_tick = launch_tick;
    this.impact_tick = impact_tick;
    this.tick_delay = tick_delay;
    this.launch_height = 0.5 + from_height;
    this.to_height = to_height;
    this.max_height = max_height;
    this.line_width = line_width;
    this.min_length = min_length;
    this.fade_time = fade_time;
    this.composite_mode = comp_mode || 'source-over';
    this.glow = glow;
    this.asset = asset;

    this.start_time = -1; // set upon launch_tick
    this.end_time = -1; // set upon impact_tick
    this.last_time = -1; // SPFX.time of last computation
    this.last_progress = -1;

    this.color_str = (new SPUI.Color(color[0], color[1], color[2], 1.0)).str();

    var shot_d = vec_sub(this.to, this.from);
    var shot_len = vec_length(shot_d);
    this.shot_dir = vec_scale(1/shot_len, shot_d);

    if(exhaust) {
        // exhaust particles
        this.particles = new SPFX.Particles(null, new SPFX.When(null, launch_tick),
                                            // duration gets converted to seconds immediately here, for graphics only
                                            (impact_tick.get() - launch_tick.get()) * TICK_INTERVAL/combat_time_scale(),
                                            exhaust);
        this.exhaust_speed = ('speed' in exhaust ? /** @type {number} */ (exhaust['speed']) : 0);
        this.exhaust_dvel = ('randomize_vel' in exhaust ? /** @type {number} */ (exhaust['randomize_vel']) : 0) * this.exhaust_speed;
        this.exhaust_vel = vec_scale(-this.exhaust_speed, this.shot_dir);
        this.exhaust_rate = Math.floor(Math.min(SPFX.detail, 1) * ('emit_rate' in exhaust ? /** @type {number} */ (exhaust['emit_rate']) : 60));
        SPFX.add(this.particles);
    } else {
        this.particles = null;
    }
};
goog.inherits(SPFX.TicksProjectile, SPFX.Effect);

SPFX.TicksProjectile.DEBUG = false;

SPFX.TicksProjectile.prototype.draw_beam = function() {
    var stroke_start = ortho_to_draw_3d([this.from[0], this.launch_height, this.from[1]]);
    var stroke_end = ortho_to_draw_3d([this.to[0], this.to_height, this.to[1]]);

    // quantize to pixels
    quantize_streak(stroke_start, stroke_end);

    var fade = 1;
    if(this.fade_time > 0) {
        fade = 1 - (SPFX.time - this.start_time) / this.fade_time;
        if(fade <= 0) {
            return;
        }
    }

    SPFX.ctx.save();

    if(1) {
        SPFX.ctx.globalAlpha = fade;
        SPFX.set_composite_mode(this.composite_mode);
        SPFX.ctx.strokeStyle = this.color_str;
        SPFX.ctx.lineWidth = this.line_width;
        SPFX.ctx.beginPath();
        SPFX.ctx.moveTo(stroke_start[0], stroke_start[1]);
        SPFX.ctx.lineTo(stroke_end[0], stroke_end[1]);
        SPFX.ctx.stroke();
    }

    SPFX.ctx.restore();
};

SPFX.TicksProjectile.prototype.draw = function() {
    var shot_ticks = this.impact_tick.get() - this.launch_tick.get();

    if(GameTypes.TickCount.lt(SPFX.tick, this.launch_tick)) {
        return;
    } else if(this.start_time < 0) {
        this.start_time = SPFX.last_tick_time + this.tick_delay;
        this.last_time = this.start_time;
    }
    if(SPFX.time < this.start_time) {
        if(SPFX.TicksProjectile.DEBUG) {
            console.log(SPFX.tick.get().toString()+' '+this.id+' cancelled - before start_time');
        }
        return;
    }

    if(GameTypes.TickCount.gte(SPFX.tick, this.impact_tick)) {
        if(this.end_time < 0) {
            this.end_time = SPFX.last_tick_time + this.tick_delay;
            if(shot_ticks < 1) { this.end_time += TICK_INTERVAL/combat_time_scale(); }
        }
        if(SPFX.time > this.end_time + this.fade_time) {
            if(SPFX.TicksProjectile.DEBUG) {
                console.log(SPFX.tick.get().toString()+' '+this.id+' cancelled - after end_time');
            }
            SPFX.remove(this);
            return;
        }
    }

    if(this.min_length > 100.0) {
        // draw as solid beam instead of projectile
        return this.draw_beam();
    }

    // 0 = launch, 1 = impact
    // works for shot_ticks = 0!
    var progress = (SPFX.tick.get() - this.launch_tick.get()) / Math.max(shot_ticks, 1);

    // add time since last tick
    progress += ((SPFX.time-SPFX.last_tick_time-this.tick_delay)/(TICK_INTERVAL/combat_time_scale())) / Math.max(shot_ticks, 1);
    var dprogress_dt = (1/(TICK_INTERVAL/combat_time_scale())) / Math.max(shot_ticks, 1);

    //progress = Math.max(progress, 0);

    //progress = Math.min(progress, 1);

    // delta since last draw
    var dprogress = (this.last_progress < 0 ? dprogress_dt : progress - this.last_progress);
    var dt = SPFX.time - this.last_time;

    // compute x,y ground position
    var pos = vec_lerp(this.from, this.to, progress);

    // parabolic arc
    var height = this.launch_height + this.max_height * (1 - ((progress-0.5)*(progress-0.5))/0.25) + progress * (this.to_height - this.launch_height);
    // derivative of above with respect to progress
    var dheight_dprogress = -8 * this.max_height * (progress - 0.5) + (this.to_height - this.launch_height);

    // spawn exhaust particles
    if(this.particles) {
        var num_particles = Math.min(0.10, dt) * this.exhaust_rate;
        var int_particles = Math.floor(num_particles);
        var frac_particles = num_particles - int_particles;
        if(Math.random() < frac_particles) {
            int_particles += 1;
        }
        for(var i = 0; i < int_particles; i++) {
            var pt = progress - Math.random()*dprogress;
            var ppos = vec_lerp(this.from, this.to, pt);
            var vel = this.exhaust_vel;
            /** @type {!Array.<number>} */
            var spawn_loc = [ppos[0], height, ppos[1]];
            if(this.particles.spawn_radius > 0) {
                for(var axis = 0; axis < 3; axis++) {
                    spawn_loc[i] += this.particles.spawn_radius * (2*Math.random()-1);
                }
            }
            this.particles.spawn(spawn_loc, 0, [vel[0], 0, vel[1]], this.exhaust_dvel, [1,1,1], 1);
        }
    }

    // motion blur streak length - by default 50% of time interval to simulate 1/48th
    // shutter, but don't let it get too large if framerate drops
    var sdprogress = 0.5 * Math.min(dprogress, 0.05);

    if(SPFX.TicksProjectile.DEBUG) {
        console.log('tick '+SPFX.tick.get().toString()+' progress '+progress.toString()+' dprogress '+dprogress.toString());
    }

    var stroke_start = ortho_to_draw_3d([pos[0], height, pos[1]]);
    var stroke_end_pos = vec_mad(pos, sdprogress, vec_sub(this.to, this.from));
    var stroke_end_height = height + sdprogress * dheight_dprogress;
    var stroke_end = ortho_to_draw_3d([stroke_end_pos[0], stroke_end_height, stroke_end_pos[1]]);

    if(this.min_length > 0) {
        var len = vec_distance(stroke_start, stroke_end);
        if(len < this.min_length && len > 0) {
            stroke_end = vec_mad(stroke_start, this.min_length/len, vec_sub(stroke_end, stroke_start));
        }
    }

    SPFX.ctx.save();

    if(0) {
        //console.log(this.from[0]+','+t+' '+height+','+this.shot_vel[0]);
        SPFX.ctx.strokeStyle = 'rgba(255,200,50,0.1)';
        SPFX.ctx.lineWidth = 2;
        SPFX.ctx.beginPath();
        SPFX.ctx.moveTo(stroke_start[0], stroke_start[1]);
        SPFX.ctx.lineTo(stroke_end[0], stroke_end[1]);
        SPFX.ctx.stroke();
    }

    // quantize to pixels
    quantize_streak(stroke_start, stroke_end);

    if(this.glow > 0 && SPFX.detail > 1) {

        SPFX.set_composite_mode(/** @type {string|undefined} */ (gamedata['client']['projectile_glow_mode']) || 'source-over');
        var glow_asset_name = 'fx/glows';
        var glow_asset = GameArt.assets[glow_asset_name]
        var glow_sprite = /** @type {!GameArt.Sprite} down-cast from AbstractSprite */ (glow_asset.states['normal']);
        var glow_image = glow_sprite.images[0];

        // primary glow
        SPFX.ctx.globalAlpha = this.glow*gamedata['client']['projectile_glow_intensity'];
        glow_image.draw([stroke_end[0]-Math.floor(glow_image.wh[0]/2),
                         stroke_end[1]-Math.floor(glow_image.wh[1]/2)]);

        // secondary, fainter glow
        SPFX.ctx.globalAlpha = this.glow*0.56*gamedata['client']['projectile_glow_intensity'];
        glow_image = glow_sprite.images[1];
        glow_image.draw([stroke_end[0]-Math.floor(glow_image.wh[0]/2),
                         stroke_end[1]-Math.floor(glow_image.wh[1]/2)]);

        SPFX.ctx.globalAlpha = 1;
        SPFX.set_composite_mode('source-over');
    }

    if(this.asset) {
        var sprite = GameArt.assets[this.asset].states['normal'];
        sprite.draw(stroke_start, 0, SPFX.time);
    } else {
        SPFX.ctx.strokeStyle = this.color_str;
        SPFX.ctx.lineWidth = this.line_width;
        SPFX.set_composite_mode(this.composite_mode);
        SPFX.ctx.beginPath();
        SPFX.ctx.moveTo(stroke_start[0], stroke_start[1]);
        SPFX.ctx.lineTo(stroke_end[0], stroke_end[1]);
        SPFX.ctx.stroke();
    }

    SPFX.ctx.restore();

    this.last_time = SPFX.time;
    this.last_progress = progress;
};

/** Quantize a line segment for drawing. Mutates start/end in place.
    @param {!Array.<number>} start
    @param {!Array.<number>} end */
function quantize_streak(start, end) {
    start = draw_quantize(start);
    end = draw_quantize(end);

    // prevent streak from disappearing between pixels
    if(start[0] == end[0] && start[1] == end[1]) {
        start[0] += 2;
    }
}

// SoundCue
// plays a sound effect, being smart about the single-channel restriction

SPFX.cue_tracker = {};

/** @type {number} allow at least this much of a gap between successive plays of the
    same sound effect (helps with swarm firing and bad browsers) */
SPFX.sound_throttle = 0.3;

/** @constructor
    @struct
    @extends SPFX.Effect
    @param {!Object} data
    @param {!SPFX.When} when
  */
SPFX.SoundCue = function(data, when) {
    goog.base(this, data);
    this.when = when;
    this.start_time = -1; // determined after "when"

    /** @type {!Array.<!GameArt.AbstractSprite>} */
    this.sprites = [];

    /** @type {!Array.<string>} */
    var asset_list = [];

    if('assets' in data) {
        // use multiple assets
        asset_list = /** @type {!Array.<string>} */ (data['assets']);
    } else {
        asset_list = [/** @type {string} */ (data['sprite'])];
    }

    for(var i = 0; i < asset_list.length; i++) {
        /** @type {string} */
        var assetname = asset_list[i];
        if(!(assetname in GameArt.assets)) {
            console.log('missing audio SFX asset '+assetname+'!');
            continue;
        }
        var sprite = GameArt.assets[assetname].states['normal'];
        if(!sprite || !sprite.get_audio()) {
            throw Error('unknown or soundless audio asset '+assetname);
        }
        this.sprites.push(sprite);
    }
};
goog.inherits(SPFX.SoundCue, SPFX.Effect);
SPFX.SoundCue.prototype.draw = function() {
    if(SPFX.time_lt(this.when)) { return; }

    if(this.start_time < 0) {
        this.start_time = SPFX.time;
    }

    // start at a random place in the list
    var idx = (this.sprites.length > 1 ? Math.floor(this.sprites.length*Math.random()) : 0);

    // keep running down the list if we can't play effects due to channel overlap
    for(var i = 0; i < this.sprites.length; i++) {
        var s = this.sprites[(i + idx) % this.sprites.length];
        var audio = s.get_audio();
        var key = audio.filename;
        if(key in SPFX.cue_tracker && (SPFX.time - SPFX.cue_tracker[key]) < SPFX.sound_throttle) {
            continue;
        }

        if(audio.play(SPFX.time)) {
            SPFX.cue_tracker[key] = SPFX.time;
            break;
        }
    }
    SPFX.remove(this);
}

// Explosion

/** get a parameter that could be one- or two-dimensional
    @param {number|!Array.<number>} param
    @return {!Array.<number>} */
SPFX.get_vec_parameter = function(param) {
    if((typeof param) === 'number') {
        return [param, param];
    } else {
        return [param[0], param[1]];
    }
};

/** @constructor
    @extends SPFX.Effect
    @struct
    @param {!Array.<number>} where
    @param {number} height
    @param {string} assetname
    @param {!SPFX.When} when
    @param {boolean} enable_audio
    @param {!Object} data
    @param {Object|null} instance_data
  */
SPFX.Explosion = function(where, height, assetname, when, enable_audio, data, instance_data) {
    goog.base(this, data);

    if(instance_data) {
        for(var key in instance_data) {
            assetname = assetname.replace(key, instance_data[key]);
        }
    }

    this.where = vec_add(where, (data && 'offset' in data ? [data['offset'][0], data['offset'][2]] : [0,0]));
    this.height = height + (data && 'offset' in data ? /** @type {number} */ (data['offset'][1]) : 0.5);
    var asset = GameArt.assets[assetname];
    if(!asset) {
        throw Error('unknown art asset '+assetname);
    }

    /** @type {!GameArt.AbstractSprite} */
    this.sprite = asset.states['normal'];
    this.when = when;
    this.start_time = -1; // determined once "when" passes
    this.end_time = -1;

    /** @type {boolean} "is_ui" means "this is a UI dialog effect, not a 3D playfield effect" */
    this.is_ui = (instance_data && ('is_ui' in instance_data) ? /** @type {boolean} */ (instance_data['is_ui']) : false);

    if(data && 'duration' in data) {
        this.duration = /** @type {number} */ (data['duration']);
    } else {
        this.duration = this.sprite.duration();
        if(this.duration <= 0) {
            this.duration = 0.07; // default for still images
        }
    }

    if(this.duration >= 0) {
        this.fade = ((data && ('fade' in data)) ? /** @type {number} */ (data['fade']) : 0);
        this.fade_duration = ((data && ('fade_duration' in data)) ? /** @type {number} */ (data['fade_duration']) : this.duration / 2);
    } else {
        this.fade = 0;
    }

    /** @type {string|null} */
    this.motion = ((data && ('motion' in data)) ? /** @type {string} */ (data['motion']) : null);
    this.motion_scale = ((data && 'motion_scale' in data) ? SPFX.get_vec_parameter(data['motion_scale']) : [1,1]);

    /** @type {boolean} */
    this.enable_audio = enable_audio;

    /** @type {boolean} */
    this.audio_started = false;

    this.opacity = ((data && ('opacity' in data)) ? /** @type {number} */ (data['opacity']) : 1);
    this.composite_mode = ((data && ('composite_mode' in data)) ? /** @type {string} */ (data['composite_mode']) : 'source-over');

    this.sprite_scale = (instance_data && 'sprite_scale' in instance_data ? SPFX.get_vec_parameter(instance_data['sprite_scale']) : ((data && 'sprite_scale' in data) ? SPFX.get_vec_parameter(data['sprite_scale']) : [1,1]));

    this.rotation = (instance_data && 'rotation' in instance_data ? /** @type {number} */ (instance_data['rotation']) : (data && ('rotation' in data) ? /** @type {number} */ (data['rotation']) : 0));
    this.rotate_speed = (instance_data && 'rotate_speed' in instance_data ? /** @type {number} */ (instance_data['rotate_speed']) : (data && ('rotate_speed' in data) ? /** @type {number} */ (data['rotate_speed']) : 0));

    var old_data = /** @type {!Object} */ (gamedata['art'][assetname]['states']['normal']);
    if('particles' in old_data) {
        var particles = new SPFX.Particles([this.where[0], this.height, this.where[1]], when, this.duration, /** @type {!Object} */ (old_data['particles']));
        SPFX.add(particles);
    }

    /** @type {HTMLImageElement|null} alternate HTML5 Image object used for tinting effects
        NOTE: this is not cached or shared, so use sparingly to avoid resource exhaustion! */
    this.special_img = null;

    // disable for now, since we must find some way to guarantee that the affected image is loaded in a CORS-safe way on all browsers
    // (see GameArt.TintedImage)
    /*
    if(0 && data && data['tint'] && SPFX.detail > 1 && gamedata['client']['enable_pixel_manipulation']) {
        var img = this.sprite.select_image(0,0);
        // note: if pixels aren't here yet, just punt
        if(img.data_loaded) {
            this.special_img = GameArt.make_tinted_image(img.img, img.origin, img.wh, data['tint']);
        }
    }
    */
};
goog.inherits(SPFX.Explosion, SPFX.Effect);

/** @override
    @param {!Array.<number>} xyz
    @param {number=} rotation */
SPFX.Explosion.prototype.reposition = function(xyz, rotation) {
    this.where = vec_add([xyz[0],xyz[2]], (this.data && 'offset' in this.data ?
                                           [/** @type {number} */ (this.data['offset'][0]),
                                           /** @type {number} */ (this.data['offset'][2])] : [0,0]));
    this.height = xyz[1] + (this.data && 'offset' in this.data ? /** @type {number} */ (this.data['offset'][1]) : 0.5);
    if(typeof(rotation) != 'undefined') { this.rotation = rotation; }
};

/** @override */
SPFX.Explosion.prototype.draw = function() {
    if(SPFX.time_lt(this.when)) { return; }
    if(this.start_time < 0) {
        this.start_time = SPFX.time;
        if(this.duration >= 0) {
            this.end_time = this.start_time + this.duration;
        }
    }

    if(this.enable_audio && !this.audio_started && this.sprite.get_audio()) {
        this.sprite.get_audio().play(SPFX.time);
        this.audio_started = true;
    }

    if(this.end_time >= 0 && SPFX.time >= this.end_time) {
        SPFX.remove(this);
        return;
    }

    var t = (SPFX.time - this.start_time) / (this.end_time-this.start_time);

    /** @type {!Array.<number>} */
    var xyz = [this.where[0], this.height, this.where[1]];
    var scale = [this.sprite_scale[0], this.sprite_scale[1]];
    var rot = this.rotation + this.rotate_speed*(SPFX.time-this.start_time);

    if(this.motion == 'starfall') {
        if(t < 0.5) {
            xyz[1] = xyz[1] + 60*Math.pow(1 - 2*t, 1.0);
        }
    } else if(this.motion == 'grow_then_shrink') {
        scale = vec_scale(Math.pow(1-Math.abs(2*t-1), 2.0), scale);
    } else if(this.motion == 'grow') {
        scale = vec_mul(vec_add([1,1], vec_scale(t, this.motion_scale)), scale);
    }

    var xy;
    if(this.is_ui) {
        xy = [xyz[0], xyz[2]];
    } else {
        xy = ortho_to_draw_3d(xyz);
    }

    var opacity = this.opacity;
    if(this.fade) {
        var fade_t = 1;
        if (SPFX.time - this.start_time < this.fade_duration) {
            fade_t = (SPFX.time - this.start_time) / this.fade_duration;
        } else if (this.end_time - SPFX.time < this.fade_duration) {
            fade_t = (this.end_time - SPFX.time) / this.fade_duration;
        }
        opacity *= Math.pow(1 - Math.abs(fade_t - 1), 2.0);
    }

    var has_state = (opacity != 1 || scale[0] != 1 || scale[1] != 1 || rot!=0 || this.composite_mode != 'source-over');

    if(has_state) {
        SPFX.ctx.save();
        if(opacity != 1) { SPFX.ctx.globalAlpha = opacity; }
        if(this.composite_mode != 'source-over') { SPFX.set_composite_mode(this.composite_mode); }
        if(scale[0] != 1 || scale[1] != 1 || rot != 0) {
            var m = [scale[0], 0,
                     0, scale[1]];
            if(rot != 0) {
                rot *= Math.PI/180.0; // degrees->radians
                m = [Math.cos(rot)*m[0], -Math.sin(rot)*m[0],
                     Math.sin(rot)*m[3], Math.cos(-rot)*m[3]];
            }
            SPFX.ctx.transform(m[0], m[1], m[2], m[3], xy[0], xy[1]);
            xy = [0,0];
        }
    }

    xy = draw_quantize(xy);

    if(this.special_img) {
        if(this.sprite.center) {
            xy[0] -= this.sprite.center[0];
            xy[1] -= this.sprite.center[1];
        }
        SPFX.ctx.drawImage(this.special_img, xy[0], xy[1]);
    } else {
        this.sprite.draw(xy, 0, (SPFX.time - this.start_time));
    }

    if(has_state) {
        SPFX.ctx.restore();
    }
};

// Debris

/** @constructor
    @struct
    @extends SPFX.Effect
    @param {!Array.<number>} where
    @param {string} assetname
    @param {number} facing
*/
SPFX.Debris = function(where, assetname, facing) {
    goog.base(this, null);
    this.show = true;
    this.where = where;
    var asset = GameArt.assets[assetname];
    if(!asset) {
        throw Error('unknown art asset '+assetname);
    }
    this.sprite = asset.states['normal'];
    this.facing = facing;
};
goog.inherits(SPFX.Debris, SPFX.Effect);
SPFX.Debris.prototype.draw = function() {
    if(!this.show) { return; }
    var xy = ortho_to_draw(this.where);
    this.sprite.draw([Math.floor(xy[0]), Math.floor(xy[1])], this.facing, 0);
};

// Blinking arrow to indicate units that are off-screen

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.OffscreenArrow = function() {
    goog.base(this, null);
    /** @type {Array.<number>|null} */
    this.where = null;
    /** @type {GameArt.AbstractSprite|null} */
    this.sprite = null;
};
goog.inherits(SPFX.OffscreenArrow, SPFX.Effect);
/** @param {Array.<number>|null} where */
SPFX.OffscreenArrow.prototype.reset = function(where) {
    this.where = where;
};

/** @type {!Array.<{min_angle: number, max_angle: number, sprite: string, draw_location: !Array.<number>}>} */
SPFX.OffscreenArrow_data = [
    {min_angle: 0, max_angle: Math.PI/8, sprite: 'n', draw_location: [0.5, 0.15]},
    {min_angle: Math.PI/8, max_angle: 3*Math.PI/8, sprite: 'ne', draw_location: [0.95, 0.15]},
    {min_angle: 3*Math.PI/8, max_angle: 5*Math.PI/8, sprite: 'e', draw_location: [0.95, 0.5]},
    {min_angle: 5*Math.PI/8, max_angle: 7*Math.PI/8, sprite: 'se', draw_location: [0.95, 0.65]},
    {min_angle: 7*Math.PI/8, max_angle: 9*Math.PI/8, sprite: 's', draw_location: [0.5, 0.70]},
    {min_angle: 9*Math.PI/8, max_angle: 11*Math.PI/8, sprite: 'sw', draw_location: [0.05, 0.65]},
    {min_angle: 11*Math.PI/8, max_angle: 13*Math.PI/8, sprite: 'w', draw_location: [0.05, 0.5]},
    {min_angle: 13*Math.PI/8, max_angle: 15*Math.PI/8, sprite: 'nw', draw_location: [0.05, 0.15]},
    {min_angle: 15*Math.PI/8, max_angle: 2*Math.PI, sprite: 'n', draw_location: [0.5, 0.1]}
];

SPFX.OffscreenArrow.prototype.draw = function() {
    if(!this.where) { return; }

    var xy = ortho_to_draw(this.where);

    var MARGIN_HORIZ = 50, MARGIN_VERT = 150;

    if(xy[0] >= view_roi[0][0]+MARGIN_HORIZ && xy[0] < (view_roi[1][0]-MARGIN_HORIZ) &&
       xy[1] >= view_roi[0][1]+MARGIN_VERT && xy[1] < (view_roi[1][1]-MARGIN_VERT)) {
        // target location is visible on screen, don't draw the arrow
        return;
    }

    var screen_center = [(view_roi[0][0]+view_roi[1][0]/2),(view_roi[0][1]+view_roi[1][1])/2];//[canvas_width/2, canvas_height/2];

    // find angle from screen center towards the xy pixel location
    // (add 0.01 to avoid undefined value at 0,0)
    var angle = Math.atan2(screen_center[1]-xy[1]+0.01, screen_center[0]-xy[0]+0.01);

    // rotate so that angle=0 is due north
    angle -= Math.PI/2;
    if(angle < 0) {
        angle += 2*Math.PI;
    }

    // pick direction for the arrow
    var dir = 'n';
    var draw_loc = [0,0];
    for(var i = 0; i < SPFX.OffscreenArrow_data.length; i++) {
        var data = SPFX.OffscreenArrow_data[i];
        if(angle >= data.min_angle && angle <= data.max_angle) {
            dir = data.sprite;
            draw_loc = data.draw_location;
            break;
        }
    }
    //console.log('xy '+xy[0]+','+xy[1]+' angle '+angle+' dir '+dir);
    var assetname = 'arrow_'+dir;
    var asset = GameArt.assets[assetname];
    if(!asset) {
        throw Error('unknown art asset '+assetname);
    }
    var sprite = asset.states['normal'];

    SPFX.ctx.save();
    set_default_canvas_transform(SPFX.ctx); // reset to null transform

    // blinking arrow
    if(Math.floor(2.0*SPFX.time) % 2 === 0) {
        sprite.draw(draw_quantize([draw_loc[0]*canvas_width,
                                   draw_loc[1]*canvas_height]), 0, 0);
    }
    SPFX.ctx.restore();
    /*
    SPFX.ctx.beginPath();
    SPFX.ctx.moveTo(screen_center[0], screen_center[1]);
    SPFX.ctx.lineTo(xy[0], xy[1]);
    SPFX.ctx.stroke();
    */
};

// Scrolling Combat Text

/** @constructor
 @extends SPFX.Effect
 @param {!Array.<number>} where
 @param {number} altitude
 @param {string} str
 @param {!Array.<number>} col
 @param {SPFX.When|null} when - null means "right now"
 @param {number} duration
 @param {{solid_for: (number|undefined),
          rise_speed: (number|undefined),
          drop_shadow: (boolean|undefined),
          font_size: (number|undefined), font_leading: (number|undefined), text_style: (string|undefined),
          is_ui: (boolean|undefined)}=} props
  */
SPFX.CombatText = function(where, altitude, str, col, when, duration, props) {
    goog.base(this, null);
    this.where = where;
    this.altitude = altitude;
    this.str = str;
    this.solid_for = props.solid_for || 0.4; // alpha remains 1 for this portion of the start-end interval
    this.color = SPUI.make_colorv(SPUI.low_fonts ? [1,1,0,1] : col);
    this.shadow_color = new SPUI.Color(0, 0, 0, col[3]);
    this.when = when || new SPFX.When(SPFX.time, null);
    this.duration = duration;
    this.start_time = this.end_time = -1; // figured out after "when"
    this.speed = props.rise_speed || 40; // pixels per second
    this.drop_shadow = props.drop_shadow || false;
    this.font = SPUI.make_font(props.font_size || 15, props.font_leading || 15, props.text_style || 'normal');
    this.is_ui = props.is_ui || false; // "is_ui" means "this is a UI dialog effect, not a 3D playfield effect"
};
goog.inherits(SPFX.CombatText, SPFX.Effect);
SPFX.CombatText.prototype.draw = function() {
    if(SPFX.time_lt(this.when)) { return; }
    if(this.start_time < 0) {
        this.start_time = SPFX.time;
        this.end_time = this.start_time + this.duration;
    }

    if(SPFX.time > this.end_time) {
        SPFX.remove(this);
        return;
    }

    var interval = this.end_time - this.start_time;
    this.color.a = 1 - (SPFX.time - this.start_time - this.solid_for*interval) / ((1-this.solid_for)*interval);
    this.color.a = Math.min(Math.max(this.color.a, 0), 1);
    this.shadow_color.a = this.color.a;

    SPFX.ctx.save();
    SPFX.ctx.font = this.font.str();

    var xy, roi;
    if(this.is_ui) {
        xy = [this.where[0], this.where[1]];
        roi = [[0,0],[canvas_width,canvas_height]];
    } else {
        xy = ortho_to_draw_3d([this.where[0], this.altitude, this.where[1]]);
        roi = view_roi;
    }

    var dims = SPFX.ctx.measureText(this.str);
    xy[0] = xy[0] - dims.width/2;
    xy[1] = xy[1] - (15 + this.speed*(SPFX.time - this.start_time));

    // don't let it go off-screen horizontally
    if(xy[0] > roi[1][0] - dims.width) {
        xy[0] = roi[1][0] - dims.width;
    }
    if(xy[0] < roi[0][0]) { xy[0] = roi[0][0]; }

    xy = draw_quantize(xy);

    if(this.drop_shadow && !SPUI.low_fonts) {
        SPFX.ctx.fillStyle = this.shadow_color.str();
        SPFX.ctx.fillText(this.str, xy[0]+1, xy[1]+1);
    }
    SPFX.ctx.fillStyle = this.color.str();
    SPFX.ctx.fillText(this.str, xy[0], xy[1]);
    SPFX.ctx.restore();
};

/** Unit movement/attack feedback
    @constructor
    @struct
    @extends SPFX.Effect
    @param {!Array.<number>} col
    @param {!SPFX.When} when
    @param {number} duration
*/
SPFX.FeedbackEffect = function(col, when, duration) {
    goog.base(this, null);
    this.base_col = col;
    this.color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    this.when = when;
    this.duration = duration;
    this.start = this.end = -1;
};
goog.inherits(SPFX.FeedbackEffect, SPFX.Effect);
SPFX.FeedbackEffect.prototype.do_draw = goog.abstractMethod;
SPFX.FeedbackEffect.prototype.draw = function() {
    if(SPFX.time_lt(this.when)) { return; }
    if(this.start < 0) {
        this.start = SPFX.time;
        this.end = this.start + this.duration;
    }
    if(SPFX.time > this.end) {
        SPFX.remove(this);
        return;
    }

    var fade = (SPFX.time - this.start) / (this.end - this.start);
    this.color.a = this.base_col[3] * (1 - fade*fade);
    this.do_draw();
};

/** @constructor
    @struct
    @extends SPFX.FeedbackEffect
    @param {!Array.<number>} pos
    @param {!Array.<number>} col
    @param {number} duration
  */
SPFX.ClickFeedback = function(pos, col, duration) {
    goog.base(this, col, new SPFX.When(SPFX.time, null), duration);
    this.pos = vec_copy(pos);
};
goog.inherits(SPFX.ClickFeedback, SPFX.FeedbackEffect);

/** @override */
SPFX.ClickFeedback.prototype.do_draw = function() {
    var radius = 20.0 * (SPFX.time - this.start) / (this.end - this.start);

    SPFX.ctx.save();
    SPFX.ctx.strokeStyle = this.color.str();
    SPFX.ctx.lineWidth = 2;
    var xy = draw_quantize(ortho_to_draw(this.pos));
    SPFX.ctx.beginPath();

    SPFX.ctx.transform(1, 0, 0, 0.5, xy[0], xy[1]);
    SPFX.ctx.arc(0, 0, Math.floor(radius), 0, 2*Math.PI, false);

    SPFX.ctx.stroke();
    SPFX.ctx.restore();
};

/** @constructor
    @struct
    @extends SPFX.Effect
    @param {!Array.<number>} where (2D)
    @param {number} altitude
    @param {!SPFX.When} when
    @param {!Object} data
  */
SPFX.Shockwave = function(where, altitude, when, data) {
    goog.base(this, data);
    this.where = where;
    this.altitude = altitude;
    this.speed = (/** @type {number|undefined} */ (data['speed']) || 500);
    this.thickness = Math.min(Math.max((/** @type {number|undefined} */ (data['thickness']) || 0.5),0.0),1.0);
    var col;
    if('color' in data) {
        col = /** @type {!Array.<number>} */ (data['color']);
    } else {
        col = [1,1,1];
    }
    this.center_color = new SPUI.Color(col[0], col[1], col[2], 0.0);
    this.edge_color = new SPUI.Color(col[0], col[1], col[2], /** @type {number|undefined} */ (data['opacity']) || 1.0);
    this.when = when;
    this.start_time = -1; // determined only after "when" is passed
    this.end_time = -1;
    this.composite_mode = /** @type {string|undefined} */ (data['composite_mode']) || 'source-over';
};
goog.inherits(SPFX.Shockwave, SPFX.Effect);

SPFX.Shockwave.prototype.draw = function() {
    if(SPFX.time_lt(this.when)) {
        return;
    }

    if(this.start_time < 0) {
        this.start_time = SPFX.time;
        this.end_time = this.start_time + Math.max(/** @type {number|undefined} */ (this.data['duration']) || 0.5, 0.0);
    }

    if(SPFX.time > this.end_time) {
        SPFX.remove(this);
        return;
    }

    var t = SPFX.time - this.start_time;
    var u = t / (this.end_time - this.start_time);

    var xy = draw_quantize(ortho_to_draw_3d([this.where[0], this.altitude, this.where[1]]));

    var rad, opacity;
    if(this.speed > 0) {
        rad = Math.floor(t * this.speed);
        opacity = 1-u;
    } else {
        rad = Math.max(1, Math.floor((this.end_time-this.start_time - t)*(-this.speed)));
        opacity = u;
    }

    SPFX.ctx.save();
    SPFX.ctx.globalAlpha = opacity;
    SPFX.set_composite_mode(this.composite_mode);

    var grad = SPFX.ctx.createRadialGradient(0, 0, 0, 0, 0, rad);
    grad.addColorStop((1 - this.thickness*0.9), this.center_color.str());
    grad.addColorStop((1 - this.thickness*0.15), this.edge_color.str());
    grad.addColorStop(1.0, this.center_color.str());

    SPFX.ctx.fillStyle = grad;
    SPFX.ctx.transform(1, 0, 0, 0.5, xy[0], xy[1]);
    SPFX.ctx.fillRect(-rad, -rad, 2*rad, 2*rad);
    SPFX.ctx.restore();
};


/** @constructor
    @struct
    @extends SPFX.Effect
    @param {!Array.<number>} pos
    @param {number} altitude
    @param {!Array.<number>} orient
    @param {SPFX.When|null} when - null means "right now"
    @param {!Object} data
    @param {Object|null} instance_data
  */
SPFX.PhantomUnit = function(pos, altitude, orient, when, data, instance_data) {
    goog.base(this, data);

    instance_data = instance_data || {};

    // allow override of spawn position for more precision when spawning from moving objects
    // since the phantom will appear at the NEXT combat tick
    if('my_next_pos' in instance_data && 'tick_offset' in instance_data) {
        pos = vec_add(pos, vec_scale(instance_data['tick_offset'], vec_sub(instance_data['my_next_pos'], pos)));
    }

    if(!when) {
        when = new SPFX.When(SPFX.time, null);
    }

    this.when = when;
    this.start_time = -1; // determined after "when"
    this.end_time = -1;
    this.duration = (!('duration' in data) || /** @type {number} */ (data['duration']) >= 0) ? (/** @type {number} */ (data['duration']) || 3.0) : -1;
    this.end_at_dest = (('end_at_dest' in data) ? /** @type {boolean} */ (data['end_at_dest']) : true);

    /** @type {!Mobile} */
    this.obj = new Mobile();
    this.obj.id = GameObject.DEAD_ID;
    this.obj.spec = gamedata['units']['spec' in instance_data ? /** @type {string} */ (instance_data['spec']) : /** @type {string} */ (data['spec'])];
    this.obj.x = pos[0]; this.obj.y = pos[1];
    this.obj.hp = this.obj.max_hp = 0;
    this.obj.team = 'none';
    this.obj.level = (instance_data ? /** @type {number|undefined} */ (instance_data['level']) : null) || 1;
    this.obj.update_stats();
    this.obj.combat_stats.maxvel *= /** @type {number|undefined} */ (data['maxvel']) || 1;
    this.obj.ai_state = ai_states.AI_MOVE; // no AI

    /** @type {Array.<number>|null} movement destination */
    var dest = null;
    /** @type {Array.<!Array.<number>>|null} movement path */
    var path = null;
    if('dest' in instance_data) {
        dest = /** @type {!Array.<number>} */ (instance_data['dest']);
    } else if('heading' in instance_data) {
        // compute heading relative to that given with instance data
        var heading = /** @type {number} */ (instance_data['heading']) +
            (Math.PI/180) * (/** @type {number|undefined} */ (data['heading']) || 0); // add heading to original spawn orientation
        if(this.duration <= 0) { throw Error('duration must be positive'); }
        dest = vec_add(pos, vec_scale((this.duration) * this.obj.combat_stats.maxvel * 1.1, [Math.cos(heading), Math.sin(heading)]));
    } else if('path' in instance_data) {
        path = /** @type {!Array.<!Array.<number>>} */ (instance_data['path']);
        dest = path[path.length - 1];
    } else {
        throw Error('PhantomUnit requires one of dest, heading, or path in instance data');
    }

    this.obj.ai_dest = dest;
    this.obj.dest = this.obj.ai_dest;
    if(path) {
        this.obj.path = path;
        this.obj.path_valid = true;
    } else {
        this.obj.path_valid = false;
    }

    // start_halted will be used as the delay after start time at which to begin moving
    /** @type {number} */
    this.start_halted = /** @type {number|undefined} */ (instance_data['start_halted']) ||
        /** @type {number|undefined} */ (this.data['start_halted']) || 0;

    this.obj.control_state = (this.start_halted ? control_states.CONTROL_STOP : control_states.CONTROL_MOVING);
    this.obj.pos = [pos[0],pos[1]];
    this.obj.next_pos = [pos[0],pos[1]];
    this.obj.altitude = altitude;
};
goog.inherits(SPFX.PhantomUnit, SPFX.Effect);
SPFX.PhantomUnit.prototype.dispose = function() {
    if(this.obj.permanent_effect) {
        SPFX.remove(this.obj.permanent_effect);
    }
};

/** set new motion path directly - totally bypasses A*
 * @param {!Array.<!Array.<number>>} new_path */
SPFX.PhantomUnit.prototype.set_path = function(new_path) {
    this.obj.pos = this.obj.next_pos = vec_copy(new_path[0]);
    this.obj.dest = this.obj.ai_dest = vec_copy(new_path[new_path.length-1]);
    this.obj.control_state = control_states.CONTROL_MOVING;
    this.obj.path = new_path;
    this.obj.path_valid = true;
};

/** set new destination - will call A* for pathfinding
 * @param {Array.<number>} new_dest */
SPFX.PhantomUnit.prototype.set_dest = function(new_dest) {
    this.obj.ai_move_towards(new_dest, null, 'SPFX.PhantomUnit.set_dest');
};

SPFX.PhantomUnit.prototype.draw = function() { throw Error('should not be called'); };

/** @return {Mobile|null} */
SPFX.PhantomUnit.prototype.get_phantom_object = function() {
    if(this.end_time >= 0 && SPFX.time >= this.end_time) { return null; } // timed out

    if(SPFX.time_lt(this.when)) {
        this.obj.cur_opacity = 0;
        this.obj.last_opacity = 0;
    } else {
        if(this.start_time < 0) {
            this.start_time = SPFX.time;
            if(this.duration >= 0) {
                this.end_time = this.start_time + this.duration;
            }
        }

        if(this.start_halted && (SPFX.time - this.start_time) > this.start_halted) { // get moving now
            this.obj.control_state = control_states.CONTROL_MOVING;
        }

        // fade out after the specified duration or after reaching destination
        if(this.end_time > 0) {
            this.obj.cur_opacity = 0;
            this.obj.last_opacity = 1;
            this.obj.last_opacity_time = this.end_time - gamedata['client']['unit_fade_time'];
        } else if(this.end_at_dest && this.obj.dest && vec_equals(this.obj.pos, this.obj.dest)) {
            if(this.obj.cur_opacity != 0) {
                this.obj.cur_opacity = 0;
                this.obj.last_opacity = 1;
                this.obj.last_opacity_time = client_time;
            } else if(this.obj.last_opacity == 0) {
                // remove this because it's reached its destination and faded out
                return null;
            }
        }
    }

    return this.obj;
};

/**
   @param {!Array.<number>} pos
   @param {number} altitude
   @param {!Array.<number>} orient
   @param {number} time
   @param {!Object} data
   @param {boolean} allow_sound
   @param {Object|null} instance_data
   @return {SPFX.FXObject|null}
   */
SPFX.add_visual_effect_at_time = function(pos, altitude, orient, time, data, allow_sound, instance_data) {
    return SPFX._add_visual_effect(pos, altitude, orient, new SPFX.When(time, null), data, allow_sound, instance_data);
};

/**
   @param {!Array.<number>} pos
   @param {number} altitude
   @param {!Array.<number>} orient
   @param {!GameTypes.TickCount} tick
   @param {number} tick_delay
   @param {!Object} data
   @param {boolean} allow_sound
   @param {Object|null} instance_data
   @return {SPFX.FXObject|null}
   */
SPFX.add_visual_effect_at_tick = function(pos, altitude, orient, tick, tick_delay, data, allow_sound, instance_data) {
    return SPFX._add_visual_effect(pos, altitude, orient, new SPFX.When(null, tick, tick_delay), data, allow_sound, instance_data);
};

/**
   @param {!Array.<number>} pos
   @param {number} altitude
   @param {!Array.<number>} orient
   @param {!SPFX.When} when
   @param {!Object} data
   @param {boolean} allow_sound
   @param {Object|null} instance_data
   @return {SPFX.FXObject|null}
   @private
   */
SPFX._add_visual_effect = function(pos, altitude, orient, when, data, allow_sound, instance_data) {
    if(/** @type {number} */ (data['require_detail']) > SPFX.detail) { return null; }
    if(('max_detail' in data) && SPFX.detail >= /** @type {number} */ (data['max_detail'])) { return null; }

    if('random_chance' in data && (Math.random() >= /** @type {number} */ (data['random_chance']))) { return null; }

    var effect_type = /** @type {string} */ (data['type']);
    var effect_layer = /** @type {string|undefined} */ (data['layer']) || null;

    if('delay' in data) {
        // increment "when" by the real-time (seconds) delay
        var delay = /** @type {number} */ (data['delay']);
        when = (when.tick ? new SPFX.When(null, when.tick, delay) : new SPFX.When(when.time + delay, null));
    }

    if('translate' in data) { pos = v3_add(pos, /** @type {!Array.<number>} */ (data['translate'])); }

    /** @type {function(!SPFX.Effect): !SPFX.Effect} */
    var add_func = SPFX.add;

    if(effect_layer === 'under') {
        add_func = SPFX.add_under;
    } else if(effect_layer === 'ui') {
        add_func = SPFX.add_ui;
    }

    if(effect_type === 'shockwave') {
        return add_func(new SPFX.Shockwave(pos, altitude, when, data));
    } else if(effect_type === 'combine') {
        var ret = new SPFX.CombineEffect();
        var effects = /** @type {!Array.<!Object>|undefined} */ (data['effects']) || [];
        for(var i = 0; i < effects.length; i++) {
            var child = SPFX._add_visual_effect(pos, altitude, orient, when, effects[i], allow_sound, instance_data);
            if(child) {
                ret.effects.push(child);
            }
        }
        return ret;
    } else if(effect_type === 'random') {
        /** @type {!Array.<!Object>} */
        var effects = /** @type {Array.<!Object>|undefined} */ (data['effects']) || [];
        if(effects.length > 0) {
            /** @type {number} */
            var total_weight = 0;
            /** @type {!Array.<number>} */
            var breakpoints = [];
            goog.array.forEach(effects, function(/** !Object */ fx) {
                total_weight += ('random_weight' in fx ? /** @type {number} */ (fx['random_weight']) : 1);
                breakpoints.push(total_weight);
            });
            var r = Math.random() * total_weight;
            var index = -goog.array.binarySearch(breakpoints, r) - 1;
            return SPFX._add_visual_effect(pos, altitude, orient, when, effects[index], allow_sound, instance_data);
        }
    } else if(effect_type === 'library') {
        var ref = /** @type {!Object} */ (gamedata['client']['vfx'][data['name']]);
        return SPFX._add_visual_effect(pos, altitude, orient, when, ref, allow_sound, instance_data);
    } else if(effect_type === 'explosion') {
        return add_func(new SPFX.Explosion(pos, altitude, /** @type {string} */ (data['sprite']), when, false, data, instance_data));
    } else if(effect_type === 'particles') {
        var particles = new SPFX.Particles([pos[0], altitude, pos[1]], when,
                                           /** @type {number|undefined} */ (data['max_age']) || 1.0,
                                           data, instance_data);
        return add_func(particles);
    } else if(effect_type === 'particle_magnet') {
        return SPFX.add_field(new SPFX.MagnetField([pos[0], altitude, pos[1]], data, instance_data));
    } else if(effect_type === 'drag_field') {
        return SPFX.add_field(new SPFX.DragField([pos[0], altitude, pos[1]], data, instance_data));
    } else if(effect_type === 'camera_shake') {
        SPFX.shake_camera(when,
                          /** @type {number|undefined} */ (data['amplitude']) || 100,
                          /** @type {number|undefined} */ (data['decay_time']) || 0.4);
        return null;
    } else if(effect_type === 'combat_text') {
        return add_func(new SPFX.CombatText(pos, 0, /** @type {string} */ (data['ui_name']),
                                            /** @type {!Array.<number>|undefined} */ (data['text_color']) || [1,1,1],
                                            when,
                                            /** @type {number|undefined} */ (data['duration']) || 3,
                                            {drop_shadow: !!data['drop_shadow'],
                                             font_size: /** @type {number|undefined} */ (data['font_size']) || 20,
                                             text_style: /** @type {string|undefined} */ (data['text_style']) || 'thick'}));
    } else if(effect_type === 'sound') {
        if(allow_sound) {
            return add_func(new SPFX.SoundCue(data, when));
        } else {
            return null;
        }
    } else if(effect_type === 'phantom_unit') {
        if(instance_data && ('dest' in instance_data) && instance_data['dest'] === null) {
            return null; // inhibit spawning
        }
        return SPFX.add_phantom(new SPFX.PhantomUnit(pos, altitude, orient, when, data, instance_data));
    } else {
        console.log('unhandled visual effect type "'+effect_type+'"!');
    }
    return null;
};
