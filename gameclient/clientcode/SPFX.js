goog.provide('SPFX');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
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

/** @type {!GameTypes.TickCount}
    @private */
SPFX.tick = new GameTypes.TickCount(0);

/** Some effects want to fire at specific client_times and others want
 to fire at specific combat ticks. This type encapsulates both cases.
 @constructor
 @struct
 @param {number|null} time
 @param {GameTypes.TickCount|null} tick */
SPFX.When = function(time, tick) {
    this.time = time;
    this.tick = (tick ? tick.copy() : null);
};

SPFX.last_id = 0;
SPFX.detail = 1;
SPFX.global_gravity = 1;
SPFX.global_ground_plane = 0;

// XXX hack to fake z-ordering - there are three "layers" of effects

/** @type {Object.<string,!SPFX.Effect>} */
SPFX.current_under = {}; // underneath units/buildings

/** @type {Object.<string,!SPFX.PhantomUnit>} */
SPFX.current_phantoms = {}; // phantom units/buildings managed by SPFX

/** @type {Object.<string,!SPFX.Effect>} */
SPFX.current_over = {}; // on top of units/buildings, below UI

/** @type {Object.<string,!SPFX.Effect>} */
SPFX.current_ui = {}; // on top of UI

/** @type {Object.<string,!SPFX.Field>} */
SPFX.fields = {}; // force fields

/** @typedef {{time: (number|null|undefined), tick: (GameTypes.TickCount|null|undefined),
               amplitude: number, falloff: number}} */
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
    SPFX.last_id = 0;

    // turn down number of particles/sprites for higher performance
    if(use_low_gfx) {
        SPFX.detail = gamedata['client']['graphics_detail']['low'];
    } else if(use_high_gfx) {
        SPFX.detail = gamedata['client']['graphics_detail']['high'];
    } else {
        SPFX.detail = gamedata['client']['graphics_detail']['default'];
    }

    if('sound_throttle' in gamedata['client']) { SPFX.sound_throttle = gamedata['client']['sound_throttle']; }

    SPFX.clear();

    SPFX.shake_synth = new ShakeSynth.Shake(0);
    SPFX.shake_origin_time = SPFX.time;
};

/** @param {number} time
    @param {!GameTypes.TickCount} tick */
SPFX.set_time = function(time, tick) {
    SPFX.time = time;
    SPFX.tick = tick.copy();
};

/** @param {!SPFX.When} t
    @return {boolean} */
SPFX.time_lt = function(t) {
    if(t.tick) {
        return GameTypes.TickCount.lt(SPFX.tick, t.tick);
    } else {
        return SPFX.time < t.time;
    }
};

/** @param {!SPFX.When} t
    @return {boolean} */
SPFX.time_gte = function(t) { return !SPFX.time_lt(t); };

/** @param {!SPFX.When} start
    @param {!SPFX.When} end
    @return {number} */
SPFX.time_lerp = function(start, end) {
    var s, e, cur;
    if(start.tick) {
        s = start.tick.get();
        if(!end.tick) { throw Error('mixed When types'); }
        e = end.tick.get();
        cur = SPFX.tick.get(); // XXX this will produce non-smooth results, need to fix
    } else {
        s = start.time;
        if(end.tick) { throw Error('mixed When types'); }
        e = end.time;
        cur = SPFX.time;
    }
    return (cur - s) / (e - s);
};


// only allow non-default compositing modes when detail > 1
SPFX.set_composite_mode = function(mode) {
    if(SPFX.detail > 1) {
        SPFX.ctx.globalCompositeOperation = mode;
    }
};
SPFX.do_add = function(layer, effect) {
    effect.id = SPFX.last_id;
    SPFX.last_id++;
    layer[effect.id] = effect;
    return effect;
};

SPFX.add = function(effect) { return SPFX.do_add(SPFX.current_over, effect); };
SPFX.add_phantom = function(effect) { return SPFX.do_add(SPFX.current_phantoms, effect); };
SPFX.add_under = function(effect) { return SPFX.do_add(SPFX.current_under, effect); };
SPFX.add_ui = function(effect) { return SPFX.do_add(SPFX.current_ui, effect); };
SPFX.add_field = function(effect) { return SPFX.do_add(SPFX.fields, effect); };

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
        var obj = fx.get_phantom_object(); // will throw if it's not a SPFX.PhantomUnit
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
        if(SPFX.time < imp.time) { continue; } // too early
        var exponent = (SPFX.time-imp.time)/imp.falloff;
        if(exponent > 4.0) { // too late, no longer needed
            SPFX.shake_impulses.splice(i, 1);
            continue;
        }
        total_amp += imp.amplitude * Math.exp(-exponent);
    }
    if(Math.abs(total_amp) >= 0.0001) {
        var v = SPFX.shake_synth.evaluate(24.0*(SPFX.time-SPFX.shake_origin_time));
        return [total_amp*v[0], total_amp*v[1], total_amp*v[2]];
    }
    return [0,0,0];
};

SPFX.shake_camera = function(start_time, amp, falloff) {
    SPFX.shake_impulses.push({time:start_time, amplitude:amp, falloff:falloff});
};

/** @constructor
    @struct */
SPFX.FXObject = function() {};
/** Repositions this object in the game world. Useful when attaching effects to a moving object.
    @param {Array.<number>} xyz
    @param {number=} rotation */
SPFX.FXObject.prototype.reposition = function(xyz, rotation) {};
/** Called by SPFX.remove to perform any work needed to cleanly remove this object. */
SPFX.FXObject.prototype.dispose = function() {};

/** @constructor
    @extends SPFX.FXObject
    @param {?string=} charge */
SPFX.Field = function(charge) {
    goog.base(this);
    this.charge = charge;
};
goog.inherits(SPFX.Field, SPFX.FXObject);

SPFX.Field.prototype.eval_field = function(pos, vel) {};

// MagnetField
/** @constructor
    @extends SPFX.Field */
SPFX.MagnetField = function(pos, orient, time, data, instance_data) {
    goog.base(this, data['charge'] || null);
    this.pos = pos; // note: in 3D here
    this.strength = data['strength'] || 10.0;
    this.strength_3d = data['strength_3d'] || [1,1,1];
    this.falloff = data['falloff'] || 0;
    this.falloff_rim = data['falloff_rim'] || 0;
};
goog.inherits(SPFX.MagnetField, SPFX.Field);

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
/** @override */
SPFX.MagnetField.prototype.reposition = function(xyz, rotation) {
    this.pos = xyz;
};

/** @constructor
    @extends SPFX.Field */
SPFX.DragField = function(pos, orient, time, data, instance_data) {
    goog.base(this, data['charge'] || null);
    this.strength = data['strength'] || 1.0;
};
goog.inherits(SPFX.DragField, SPFX.Field);

SPFX.DragField.prototype.eval_field = function(pos, vel) {
    var spd = v3_length(vel);
    return v3_scale(-spd*this.strength, vel);
};

// Effect

/** @constructor
    @struct
    @extends SPFX.FXObject */
SPFX.Effect = function(data) {
    goog.base(this);
    this.data = data || null;
    this.user_data = null;
};
goog.inherits(SPFX.Effect, SPFX.FXObject);

SPFX.Effect.prototype.draw = function() {};

// CoverScreen
/** @constructor */
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
    this.effects = effects || [];
};
goog.inherits(SPFX.CombineEffect, SPFX.Effect);

SPFX.CombineEffect.prototype.draw = function() {
    // SPFX maintains handles to each child effect so we don't need to draw them here
};

/** @override */
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

// Tesla

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.Tesla = function(from, to, cur_time) {
    goog.base(this, null);
    this.from = from;
    this.to = to;
    this.end_time = cur_time + 0.001;
};
goog.inherits(SPFX.Tesla, SPFX.Effect);

SPFX.Tesla.prototype.draw = function() {
    var xy;
    SPFX.ctx.save();
    SPFX.ctx.strokeStyle = '#ffffaa';
    SPFX.ctx.beginPath();
    xy = ortho_to_draw(this.from);
    SPFX.ctx.moveTo(xy[0], xy[1]);
    xy = ortho_to_draw(this.to);
    SPFX.ctx.lineTo(xy[0], xy[1]);
    SPFX.ctx.stroke();
    SPFX.ctx.restore();

    if(SPFX.time >= this.end_time) {
        SPFX.remove(this);
    }
};

// Particle system

/** @constructor
  * @extends SPFX.Effect
  * @param {Array.<number>} spawn_pos
  * @param {number} start_time
  * @param {number} end_time
  * @param {Object} data
  * @param {Object=} instance_data
  */
SPFX.Particles = function(spawn_pos, start_time, end_time, data, instance_data) {
    goog.base(this, data);
    this.spawn_pos = v3_add(spawn_pos || [0, 0, 0], (data && 'offset' in data) ? data['offset'] : [0, 0, 0]);
    this.spawn_radius = (instance_data ? instance_data['radius'] || 1 : 1) * (this.data['radius'] || 0);
    this.draw_mode = ('draw_mode' in data? data['draw_mode'] : ('child' in data ? 'none' : 'lines'));
    this.max_age = data['max_age'] || 0.5;
    this.child_data = data['child'] || null;

    if(SPFX.detail > 1) {
        this.max_age *= 1.2; // increase max_age to compensate for particles fading out individually
    }

    this.emit_instant_done = false;
    this.emit_pattern = this.data['emit_pattern'] || 'square';
    this.emit_by_area = this.data['emit_by_area'] || 0;
    this.emit_continuous_rate = this.data['emit_continuous_rate'] || 0;
    this.emit_continuous_for = this.data['emit_continuous_for'] || 0;
    this.emit_continuous_residual = Math.random();

    this.start_time = start_time;
    this.end_time = this.emit_continuous_for >= 0 ? (end_time + this.max_age + this.emit_continuous_for) : -1;
    this.last_time = start_time;

    var col = data['color'] || [0,1,0,1];
    if(col.length == 4) {
        // good
    } else if(col.length == 3) {
        col = [col[0],col[1],col[2],1];
    } else {
        log_exception(null, 'SPFX particles with bad color length '+data['color'].length.toString()+' value '+data['color'][0].toString()+','+data['color'][1].toString()+','+data['color'][2].toString());
        col = [1,1,1,1];
    }

    this.color = new SPUI.Color(col[0],col[1],col[2],col[3]);
    this.accel = [0,
                  SPFX.global_gravity * ('gravity' in data ? data['gravity'] : -25),
                  0];
    this.collide_ground = ('collide_ground' in data ? data['collide_ground'] : true);
    this.elasticity = ('elasticity' in data ? data['elasticity'] : 0.5);
    this.nmax = data['max_count'] || 50; // max number of particles
    this.nnext = 0;
    this.line_width = data['width'] || 2;
    this.min_length = data['min_length'] || 0;
    this.fixed_length = data['fixed_length'] || 0;
    this.spin_rate = (Math.PI/180) * (data['spin_rate'] || 0);

    if('opacity' in data) {
        this.opacity = data['opacity'];
    } else {
        this.opacity = 1;
    }
    this.fade_power = (data['fade_power'] || 1);
    this.composite_mode = data['composite_mode'] || 'source-over';

    this.charge = data['charge'] || null; // charge for field interactions

    this.spawn_count = 0;
    this.pp_age = false; // whether or not age[i] varies between particles
    this.pp_state = false; // whether or not to change graphics state between drawing each particle (SLOW!)

    this.pos = [];
    this.vel = [];
    // per-particle rotation
    this.axis = (this.spin_rate > 0 ? [] : null);
    this.angle = (this.spin_rate > 0 ? [] : null);
    this.angle_v = (this.spin_rate > 0 ? [] : null);
    this.age = [];
    this.children = (this.child_data !== null ? [] : null);
};
goog.inherits(SPFX.Particles, SPFX.Effect);

/** @override */
SPFX.Particles.prototype.reposition = function(xyz, rotation) {
    if(this.data && 'offset' in this.data) {
        this.spawn_pos = v3_add(xyz, this.data['offset']);
    } else {
        this.spawn_pos = xyz;
    }
};

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
        var ax = null, an = 0, anv = 0;
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
            c = SPFX.add_visual_effect([p[0],p[2]], p[1], [0,1,0], SPFX.time, this.child_data, true, props);
        }

        if(this.pos.length < this.nmax) {
            this.pos.push(p);
            this.vel.push(v);
            this.age.push(0);
            if(this.spin_rate > 0) {
                this.axis.push(ax);
                this.angle.push(an);
                this.angle_v.push(anv);
            }
            if(this.child_data) { this.children.push(c); }
        } else {
            this.pos[this.nnext] = p;
            this.vel[this.nnext] = v;
            this.age[this.nnext] = 0;
            if(this.spin_rate > 0) {
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
    if(SPFX.time < this.start_time) { return; }
    if(this.end_time >= 0 && SPFX.time > this.end_time) { SPFX.remove(this); return; }

    if(!this.emit_instant_done && ('emit_instant' in this.data) && this.data['emit_instant'] > 0) {
        this.spawn(this.spawn_pos,
                   this.spawn_radius,
                   v3_scale(this.data['speed'], this.data['emit_orient'] || [0,1,0]),
                   this.data['speed_random'] || (this.data['speed'] || 0),
                   this.data['speed_random_scale'] || [1,1,1],
                   Math.floor(Math.min(SPFX.detail, 1)*this.data['emit_instant']));
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
                       v3_scale(this.data['speed'], this.data['emit_orient'] || [0,1,0]),
                       this.data['speed_random'] || (this.data['speed'] || 0),
                       this.data['speed_random_scale'] || [1,1,1],
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
            this.children[i].spawn_pos = this.pos[i]; // XXX should use a generic move() method or something
            if(this.spin_rate > 0) {
                this.children[i].rotation = this.angle[i]; /// XXX should check attr
            }
        }
    }
};

// Projectile

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.Projectile = function(from, from_height, to, to_height, launch_time, impact_time, max_height, color, exhaust, line_width, min_length, fade_time, comp_mode, glow, asset) {
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
        this.particles = new SPFX.Particles(null, launch_time, impact_time, exhaust);
        this.exhaust_speed = exhaust['speed'] || 0;
        this.exhaust_dvel = (exhaust['randomize_vel'] || 0) * this.exhaust_speed;
        this.exhaust_vel = vec_scale(-this.exhaust_speed, shot_dir);
        this.exhaust_rate = Math.floor(Math.min(SPFX.detail, 1) * (exhaust['emit_rate'] || 60));
        SPFX.add(this.particles);
    } else {
        this.particles = null;
    }
};
goog.inherits(SPFX.Projectile, SPFX.Effect);

SPFX.Projectile.prototype.draw_beam = function() {
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

SPFX.Projectile.prototype.draw = function() {
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

        SPFX.set_composite_mode(gamedata['client']['projectile_glow_mode'] || 'source-over');
        var glow_asset = 'fx/glows';
        var glow_image = GameArt.assets[glow_asset].states['normal'].images[0];

        // primary glow
        SPFX.ctx.globalAlpha = this.glow*gamedata['client']['projectile_glow_intensity'];
        glow_image.draw([stroke_end[0]-Math.floor(glow_image.wh[0]/2),
                         stroke_end[1]-Math.floor(glow_image.wh[1]/2)]);

        // secondary, fainter glow
        SPFX.ctx.globalAlpha = this.glow*0.56*gamedata['client']['projectile_glow_intensity'];
        glow_image = GameArt.assets[glow_asset].states['normal'].images[1];
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

function quantize_streak(start, end) {
    start[0] = Math.floor(start[0]);
    start[1] = Math.floor(start[1]);
    end[0] = Math.floor(end[0]);
    end[1] = Math.floor(end[1]);

    // prevent streak from disappearing between pixels
    if(start[0] == end[0] && start[1] == end[1]) {
        start[0] += 2;
    }
}

// SoundCue
// plays a sound effect, being smart about the single-channel restriction

SPFX.cue_tracker = {};

// allow at least this much of a gap between successive plays of the
// same sound effect (helps with swarm firing and bad browsers)
SPFX.sound_throttle = 0.3;

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.SoundCue = function(data, start_time) {
    goog.base(this, data);
    this.start_time = start_time;
    this.sprites = [];
    if('assets' in data) {
        // use multiple assets
        for(var i = 0; i < data['assets'].length; i++) {
            var assetname = data['assets'][i];
            if(!(assetname in GameArt.assets)) {
                console.log('missing audio SFX asset '+assetname+'!');
                continue;
            }
            var sprite = GameArt.assets[assetname].states['normal'];
            if(!sprite || !sprite.audio) {
                throw Error('unknown or soundless audio asset '+assetname);
            }
            this.sprites.push(sprite);
        }
    } else {
        var assetname = data['sprite'];
        if(!(assetname in GameArt.assets)) {
            console.log('missing audio SFX asset '+assetname+'!');
            return;
        }
        var sprite = GameArt.assets[assetname].states['normal'];
        if(!sprite || !sprite.audio) {
            throw Error('unknown or soundless audio asset '+assetname);
        }
        this.sprites.push(sprite);
    }
};
goog.inherits(SPFX.SoundCue, SPFX.Effect);
SPFX.SoundCue.prototype.draw = function() {
    if(SPFX.time < this.start_time) {
        return;
    }
    // start at a random place in the list
    var idx = (this.sprites.length > 1 ? Math.floor(this.sprites.length*Math.random()) : 0);

    // keep running down the list if we can't play effects due to channel overlap
    for(var i = 0; i < this.sprites.length; i++) {
        var s = this.sprites[(i + idx) % this.sprites.length];
        var key = s.audio.filename;
        if(key in SPFX.cue_tracker && (SPFX.time - SPFX.cue_tracker[key]) < SPFX.sound_throttle) {
            continue;
        }

        if(s.audio.play(SPFX.time)) {
            SPFX.cue_tracker[key] = SPFX.time;
            break;
        }
    }
    SPFX.remove(this);
}

// Explosion

// get a parameter that could be one- or two-dimensional
SPFX.get_vec_parameter = function(param) {
    if((typeof param) === 'number') {
        return [param, param];
    } else {
        return [param[0], param[1]];
    }
};

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.Explosion = function(where, height, assetname, start_time, enable_audio, data, instance_data) {
    goog.base(this, data);

    if(instance_data) {
        for(var key in instance_data) {
            assetname = assetname.replace(key, instance_data[key]);
        }
    }

    this.where = vec_add(where, (data && 'offset' in data ? [data['offset'][0], data['offset'][2]] : [0,0]));
    this.height = height + (data && 'offset' in data ? data['offset'][1] : 0.5);
    var asset = GameArt.assets[assetname];
    if(!asset) {
        throw Error('unknown art asset '+assetname);
    }
    this.sprite = asset.states['normal'];
    this.start_time = start_time;

    this.is_ui = (instance_data && instance_data.is_ui) || false; // "is_ui" means "this is a UI dialog effect, not a 3D playfield effect"

    var duration;
    if(data && data['duration']) {
        duration = data['duration'];
    } else {
        duration = this.sprite.duration();
        if(duration <= 0) {
            duration = 0.07; // default for still images
        }
    }
    if (duration >= 0) {
        this.fade = ((data && data['fade']) ? data['fade'] : 0);
        this.fade_duration = ((data && data['fade_duration']) ? data['fade_duration'] : duration / 2);
    } else {
        this.fade = 0;
    }
    this.motion = ((data && data['motion']) ? data['motion'] : null);
    this.motion_scale = ((data && 'motion_scale' in data) ? SPFX.get_vec_parameter(data['motion_scale']) : [1,1]);

    if(duration >= 0) {
        this.end_time = start_time + duration;
    } else {
        this.end_time = -1;
    }
    this.enable_audio = enable_audio;
    this.audio_started = false;

    this.opacity = ((data && data['opacity']) ? data['opacity'] : 1);
    this.composite_mode = ((data && data['composite_mode']) ? data['composite_mode'] : 'source-over');

    this.sprite_scale = ((data && 'sprite_scale' in data) ? SPFX.get_vec_parameter(data['sprite_scale']) : [1,1]);

    this.rotation = (instance_data && 'rotation' in instance_data ? instance_data['rotation'] : (data && data['rotation'] ? data['rotation'] : 0));
    this.rotate_speed = (instance_data && 'rotate_speed' in instance_data ? instance_data['rotate_speed'] : (data && data['rotate_speed'] ? data['rotate_speed'] : 0));

    var old_data = gamedata['art'][assetname]['states']['normal'];
    if('particles' in old_data) {
        var particles = new SPFX.Particles([this.where[0], this.height, this.where[1]], this.start_time, this.end_time, old_data['particles']);
        SPFX.add(particles);
    }

    // alternate HTML5 Image object used for tinting effects
    // NOTE: this is not cached or shared, so use sparingly to avoid resource exhaustion!
    this.special_img = null;
    // disable for now, since we must find some way to guarantee that the affected image is loaded in a CORS-safe way on all browsers
    // (see GameArt.TintedImage)
    if(0 && data && data['tint'] && SPFX.detail > 1 && gamedata['client']['enable_pixel_manipulation']) {
        var img = this.sprite.select_image(0,0);
        // note: if pixels aren't here yet, just punt
        if(img.data_loaded) {
            this.special_img = GameArt.make_tinted_image(img.img, img.origin, img.wh, data['tint']);
        }
    }
};
goog.inherits(SPFX.Explosion, SPFX.Effect);

/** @override */
SPFX.Explosion.prototype.reposition = function(xyz, rotation) {
    this.where = vec_add([xyz[0],xyz[2]], (this.data && 'offset' in this.data ? [this.data['offset'][0], this.data['offset'][2]] : [0,0]));
    this.height = xyz[1] + (this.data && 'offset' in this.data ? this.data['offset'][1] : 0.5);
    if(typeof(rotation) != 'undefined') { this.rotation = rotation; }
};

SPFX.Explosion.prototype.draw = function() {
    if(SPFX.time < this.start_time) {
        return;
    }

    if(this.enable_audio && !this.audio_started && this.sprite.audio) {
        this.sprite.audio.play(SPFX.time);
        this.audio_started = true;
    }

    if(this.end_time >= 0 && SPFX.time >= this.end_time) {
        SPFX.remove(this);
        return;
    }

    var t = (SPFX.time - this.start_time) / (this.end_time-this.start_time);

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

    xy = [Math.floor(xy[0]), Math.floor(xy[1])];

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
  * @extends SPFX.Effect
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

// note: references canvas_width/canvas_height from main.js

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.OffscreenArrow = function() {
    goog.base(this, null);
    this.where = null;
    this.sprite = null;
};
goog.inherits(SPFX.OffscreenArrow, SPFX.Effect);
SPFX.OffscreenArrow.prototype.reset = function(where) {
    this.where = where;
};

SPFX.OffscreenArrow_data = [
    // [min_angle, max_angle, sprite, draw_location]
    [0, Math.PI/8, 'n', [0.5, 0.15]],
    [Math.PI/8, 3*Math.PI/8, 'ne', [0.95, 0.15]],
    [3*Math.PI/8, 5*Math.PI/8, 'e', [0.95, 0.5]],
    [5*Math.PI/8, 7*Math.PI/8, 'se', [0.95, 0.65]],
    [7*Math.PI/8, 9*Math.PI/8, 's', [0.5, 0.70]],
    [9*Math.PI/8, 11*Math.PI/8, 'sw', [0.05, 0.65]],
    [11*Math.PI/8, 13*Math.PI/8, 'w', [0.05, 0.5]],
    [13*Math.PI/8, 15*Math.PI/8, 'nw', [0.05, 0.15]],
    [15*Math.PI/8, 2*Math.PI, 'n', [0.5, 0.1]]
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
    var dir = 'n', draw_loc = [0,0];
    for(var i = 0; i < SPFX.OffscreenArrow_data.length; i++) {
        var data = SPFX.OffscreenArrow_data[i];
        if(angle >= data[0] && angle <= data[1]) {
            dir = data[2];
            draw_loc = data[3];
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
    SPFX.ctx.setTransform(1,0,0,1,0,0); // reset to null transform
    // blinking arrow
    if(Math.floor(2.0*SPFX.time) % 2 === 0) {
        sprite.draw([Math.floor(draw_loc[0]*canvas_width),
                     Math.floor(draw_loc[1]*canvas_height)], 0, 0);
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
  * @extends SPFX.Effect
  * @param {{solid_for: (number|undefined),
             rise_speed: (number|undefined),
             drop_shadow: (boolean|undefined),
             font_size: (number|undefined), font_leading: (number|undefined), text_style: (string|undefined),
             is_ui: (boolean|undefined)}=} props
  */
SPFX.CombatText = function(where, altitude, str, col, start_time, end_time, props) {
    goog.base(this, null);
    this.where = where;
    this.altitude = altitude;
    this.str = str;
    this.solid_for = props.solid_for || 0.4; // alpha remains 1 for this portion of the start-end interval
    this.color = SPUI.make_colorv(SPUI.low_fonts ? [1,1,0,1] : col);
    this.shadow_color = new SPUI.Color(0, 0, 0, col[3]);
    this.start_time = start_time;
    this.speed = props.rise_speed || 40; // pixels per second
    this.end_time = end_time;
    this.drop_shadow = props.drop_shadow || false;
    this.font = SPUI.make_font(props.font_size || 15, props.font_leading || 15, props.text_style || 'normal');
    this.is_ui = props.is_ui || false; // "is_ui" means "this is a UI dialog effect, not a 3D playfield effect"
};
goog.inherits(SPFX.CombatText, SPFX.Effect);
SPFX.CombatText.prototype.draw = function() {
    if(SPFX.time < this.start_time) {
        return;
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
    xy[0] = Math.floor(xy[0] - dims.width/2);
    xy[1] = Math.floor(xy[1] - (15 + this.speed*(SPFX.time - this.start_time)));

    // don't let it go off-screen horizontally
    if(xy[0] > roi[1][0] - dims.width) {
        xy[0] = roi[1][0] - dims.width;
    }
    if(xy[0] < roi[0][0]) { xy[0] = roi[0][0]; }

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
    @param {number} start_time
    @param {number} end_time
*/
SPFX.FeedbackEffect = function(col, start_time, end_time) {
    goog.base(this, null);
    this.base_col = col;
    this.color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    this.start = new SPFX.When(start_time, null);
    this.end = new SPFX.When(end_time, null);
};
goog.inherits(SPFX.FeedbackEffect, SPFX.Effect);
SPFX.FeedbackEffect.prototype.do_draw = goog.abstractMethod;
SPFX.FeedbackEffect.prototype.draw = function() {
    if(SPFX.time_lt(this.start)) { return; }
    if(SPFX.time_gte(this.end)) {
        SPFX.remove(this);
        return;
    }
    var fade = SPFX.time_lerp(this.start, this.end);
    this.color.a = this.base_col[3] * (1 - fade*fade);
    this.do_draw();
};

/** @constructor
    @struct
    @extends SPFX.FeedbackEffect
    @param {!Array.<number>} pos
    @param {!Array.<number>} col
    @param {number} start_time
    @param {number} end_time
  */
SPFX.ClickFeedback = function(pos, col, start_time, end_time) {
    goog.base(this, col, start_time, end_time);
    this.pos = [Math.floor(pos[0]), Math.floor(pos[1])];
};
goog.inherits(SPFX.ClickFeedback, SPFX.FeedbackEffect);
SPFX.ClickFeedback.prototype.do_draw = function() {
    var radius = 20.0 * SPFX.time_lerp(this.start, this.end);

    SPFX.ctx.save();
    SPFX.ctx.strokeStyle = this.color.str();
    SPFX.ctx.lineWidth = 2;
    var xy = ortho_to_draw(this.pos);
    SPFX.ctx.beginPath();

    SPFX.ctx.transform(1, 0, 0, 0.5, Math.floor(xy[0]), Math.floor(xy[1]));
    SPFX.ctx.arc(0, 0, Math.floor(radius), 0, 2*Math.PI, false);

    SPFX.ctx.stroke();
    SPFX.ctx.restore();
};

/** @constructor
  * @extends SPFX.Effect
  */
SPFX.Shockwave = function(where, altitude, start_time, data) {
    goog.base(this, data);
    this.where = where;
    this.altitude = altitude;
    this.speed = (data['speed'] || 500);
    this.thickness = Math.min(Math.max((data['thickness'] || 0.5),0.0),1.0);
    var col;
    if('color' in data) {
        col = data['color'];
    } else {
        col = [1,1,1];
    }
    this.center_color = new SPUI.Color(col[0], col[1], col[2], 0.0);
    this.edge_color = new SPUI.Color(col[0], col[1], col[2], data['opacity'] || 1.0);
    this.start_time = start_time;
    this.end_time = start_time + Math.max(data['duration'] || 0.5, 0.0);
    this.composite_mode = data['composite_mode'] || 'source-over';
};
goog.inherits(SPFX.Shockwave, SPFX.Effect);

SPFX.Shockwave.prototype.draw = function() {
    if(SPFX.time < this.start_time) {
        return;
    } else if(SPFX.time > this.end_time) {
        SPFX.remove(this);
        return;
    }
    var t = SPFX.time - this.start_time;
    var u = t / (this.end_time - this.start_time);

    var xy = ortho_to_draw_3d([this.where[0], this.altitude, this.where[1]]);
    xy[0] = Math.floor(xy[0]), xy[1] = Math.floor(xy[1]);

    var rad, opacity;
    if(this.speed > 0) {
        rad = Math.floor(t * this.speed);
        opacity = 1-u;
    } else {
        rad = Math.floor((this.end_time-this.start_time - t)*(-this.speed));
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
  * @extends SPFX.Effect
  */
SPFX.PhantomUnit = function(pos, altitude, orient, time, data, instance_data) {
    goog.base(this, data);

    instance_data = instance_data || {};

    // allow override of spawn position for more precision when spawning from moving objects
    // since the phantom will appear at the NEXT combat tick
    if('my_next_pos' in instance_data && 'tick_offset' in instance_data) {
        pos = vec_add(pos, vec_scale(instance_data['tick_offset'], vec_sub(instance_data['my_next_pos'], pos)));
    }

    this.start_time = time;
    this.end_time = (!('duration' in data) || data['duration'] >= 0) ? (time + data['duration'] || 3.0) : -1;
    this.end_at_dest = (('end_at_dest' in data) ? data['end_at_dest'] : true);

    this.obj = new Mobile();
    this.obj.id = GameObject.DEAD_ID;
    this.obj.spec = gamedata['units']['spec' in instance_data ? instance_data['spec'] : data['spec']];
    this.obj.x = pos[0]; this.obj.y = pos[1];
    this.obj.hp = this.obj.max_hp = 0;
    this.obj.team = 'none';
    this.obj.level = (instance_data ? instance_data['level'] : null) || 1;
    this.obj.update_stats();
    this.obj.combat_stats.maxvel *= (data['maxvel'] || 1);
    this.obj.ai_state = ai_states.AI_MOVE; // no AI

    // movement destination
    var dest = null;
    var path = null;
    if('dest' in instance_data) {
        dest = instance_data['dest'];
    } else if('heading' in instance_data) {
        // compute heading relative to that given with instance data
        var heading = instance_data['heading'] + (Math.PI/180) * (data['heading'] || 0); // add heading to original spawn orientation
        dest = vec_add(pos, vec_scale((this.end_time-this.start_time) * this.obj.combat_stats.maxvel * 1.1, [Math.cos(heading), Math.sin(heading)]));
    } else if('path' in instance_data) {
        path = instance_data['path'];
        dest = path[path.length - 1];
    }

    this.obj.ai_dest = dest;
    this.obj.dest = this.obj.ai_dest;
    if(path) {
        this.obj.path = path;
        this.obj.path_valid = true;
    } else {
        this.obj.path_valid = false;
    }

    this.start_halted = instance_data['start_halted'] || this.data['start_halted'] || 0; // start_halted will be used as the delay after start time at which to begin moving
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
SPFX.PhantomUnit.prototype.get_phantom_object = function() {
    if(this.end_time >= 0 && SPFX.time >= this.end_time) { return null; } // timed out

    if(SPFX.time < this.start_time) {
        this.obj.cur_opacity = 0;
        this.obj.last_opacity = 0;
    } else {
        if(this.start_halted && (SPFX.time - this.start_time) > this.start_halted) { // get moving now
            this.obj.control_state = control_states.CONTROL_MOVING;
        }

        // fade out after the specified duration or after reaching destination
        if(this.end_time > 0) {
            this.obj.cur_opacity = 0;
            this.obj.last_opacity = 1;
            this.obj.last_opacity_time = this.end_time - gamedata['client']['unit_fade_time'];
        } else if(this.end_at_dest && vec_equals(this.obj.pos, this.obj.dest)) {
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
   @param {Array.<number>} pos
   @param {number} altitude
   @param {Array.<number>} orient
   @param {number} time
   @param {Object} data
   @param {boolean} allow_sound
   @param {Object=} instance_data
   */
SPFX.add_visual_effect = function(pos, altitude, orient, time, data, allow_sound, instance_data) {
    if(data['require_detail'] > SPFX.detail) { return null; }
    if(('max_detail' in data) && SPFX.detail >= data['max_detail']) { return null; }

    if(data['random_chance'] && (Math.random() >= data['random_chance'])) { return null; }

    if('delay' in data) { time += data['delay']; }
    if('translate' in data) { pos = v3_add(pos, data['translate']); }

    var add_func = SPFX.add;
    if(data['layer'] === 'under') {
        add_func = SPFX.add_under;
    } else if(data['layer'] === 'ui') {
        add_func = SPFX.add_ui;
    } else if(data['type'] === 'phantom_unit') {
        add_func = SPFX.add_phantom;
    }

    if(data['type'] === 'shockwave') {
        return add_func(new SPFX.Shockwave(pos, altitude, time, data));
    } else if(data['type'] === 'combine') {
        var ret = new SPFX.CombineEffect();
        var effects = data['effects'] || [];
        for(var i = 0; i < effects.length; i++) {
            var child = SPFX.add_visual_effect(pos, altitude, orient, time, effects[i], allow_sound, instance_data);
            if(child) {
                ret.effects.push(child);
            }
        }
        return ret;
    } else if(data['type'] === 'random') {
        var effects = data['effects'] || [];
        if(effects.length > 0) {
            var total_weight = 0;
            var breakpoints = [];
            goog.array.forEach(data['effects'], function(fx) {
                total_weight += ('random_weight' in fx ? fx['random_weight'] : 1);
                breakpoints.push(total_weight);
            });
            var r = Math.random() * total_weight;
            var index = -goog.array.binarySearch(breakpoints, r) - 1;
            return SPFX.add_visual_effect(pos, altitude, orient, time, effects[index], allow_sound, instance_data);
        }
    } else if(data['type'] === 'library') {
        var ref = gamedata['client']['vfx'][data['name']];
        return SPFX.add_visual_effect(pos, altitude, orient, time, ref, allow_sound, instance_data);
    } else if(data['type'] === 'explosion') {
        return add_func(new SPFX.Explosion(pos, altitude, data['sprite'], time, false, data, instance_data));
    } else if(data['type'] === 'particles') {
        var particles = new SPFX.Particles([pos[0], altitude, pos[1]], time, time + (data['max_age'] || 1.0), data, instance_data);
        return add_func(particles);
    } else if(data['type'] === 'particle_magnet') {
        return SPFX.add_field(new SPFX.MagnetField([pos[0], altitude, pos[1]], orient, time, data, instance_data));
    } else if(data['type'] === 'drag_field') {
        return SPFX.add_field(new SPFX.DragField([pos[0], altitude, pos[1]], orient, time, data, instance_data));
    } else if(data['type'] === 'camera_shake') {
        SPFX.shake_camera(time, data['amplitude'] || 100, data['decay_time'] || 0.4);
        return null;
    } else if(data['type'] === 'combat_text') {
        return add_func(new SPFX.CombatText(pos, 0, data['ui_name'], data['text_color']||[1,1,1], time, time + (data['duration']||3),
                                            {drop_shadow: !!data['drop_shadow'], font_size: data['font_size'] || 20, text_style: data['text_style']||'thick'}));
    } else if(data['type'] === 'sound') {
        if(allow_sound) {
            return add_func(new SPFX.SoundCue(data, time));
        } else {
            return null;
        }
    } else if(data['type'] === 'phantom_unit') {
        return add_func(new SPFX.PhantomUnit(pos, altitude, orient, time, data, instance_data));
    } else {
        console.log('unhandled visual effect type "'+data['type']+'"!');
    }
    return null;
};
