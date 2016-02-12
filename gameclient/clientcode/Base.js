goog.provide('Base');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    References a lot of stuff from main.js :(
*/

/** parallel to the Base class in gameserver
    @constructor
    @param {string} id
    @param {Object|null=} base_data */
Base.Base = function(id, base_data) {
    this.base_id = id;
    this.base_landlord_id = -1;
    this.base_size = 0;
    this.base_ncells = null;
    /** @type {string|null} */
    this.base_climate = null;
    /** @type {!Object} */
    this.base_climate_data = {};
    this.base_map_loc = null;
    this.base_expire_time = -1;
    this.base_last_attack_time = -1;
    this.base_ui_name = 'Unknown';
    this.base_type = null;
    this.deployment_buffer = 1;

    this.power_state = [0,0]; // power [produced,consumed]
    this.power_factor_cache = 0; // must be reset when power_state changes

    /** @type {!Climate} */
    this.climate = new Climate(this.base_climate_data); // initialize to blank climate

    if(base_data) {
        this.receive_state(base_data);
    }
};

Base.Base.prototype.set_climate = function(new_climate_name) {
    this.base_climate = new_climate_name;
    this.base_climate_data = (gamedata['climates'][this.base_climate] || {});
    this.climate = new Climate(this.base_climate_data);
};

Base.Base.prototype.receive_state = function(base_data) {
    this.deployment_buffer = ('deployment_buffer' in base_data ? base_data['deployment_buffer'] : 1);
    this.base_landlord_id = base_data['base_landlord_id'];
    this.set_climate(base_data['base_climate']);
    this.base_map_loc = ('base_map_loc' in base_data ? base_data['base_map_loc'] : null);
    this.base_expire_time = ('base_expire_time' in base_data ? base_data['base_expire_time'] : -1);
    this.base_ui_name = base_data['base_ui_name'];
    this.base_type = base_data['base_type'];
    this.base_ncells = ('base_ncells' in base_data ? base_data['base_ncells'] : null);
    this.base_last_attack_time = base_data['base_last_attack_time'] || -1;
};

Base.Base.prototype.ncells = function() {
    if(this.base_ncells !== null) { return this.base_ncells; }
    return gamedata['map']['default_ncells'];
};

Base.Base.prototype.midcell = function() {
    return vec_floor(vec_scale(0.5, this.ncells()));
};

Base.compute_power_factor = function(power) {
    if(power[1] <= power[0]) {
        return 1;
    } else {
        return power[0]/(1.0*power[1]);
    }
};

Base.Base.prototype.update_power_state = function(newstate) {
    this.power_state = newstate;
    this.power_factor_cache = Base.compute_power_factor(this.power_state);
};

Base.Base.prototype.power_factor = function() { return this.power_factor_cache; };

Base.Base.prototype.get_base_radius = function() {
    var size = this.base_size;
    if(size < 0 || size > gamedata['map']['base_perimeter'].length) {
        throw Error('invalid base_size '+size);
    }
    return Math.floor(gamedata['map']['base_perimeter'][size]/2);
};

Base.Base.prototype.has_deployment_zone = function() {
    return (this.deployment_buffer && typeof(this.deployment_buffer) != 'boolean' && typeof(this.deployment_buffer) != 'number');
};

Base.Base.prototype.deployment_zone_centroid = function() {
    if(!this.has_deployment_zone()) { return null; }
    if(this.deployment_buffer['type'] != 'polygon') { throw Error('unhandled deployment buffer type'+this.deployment_buffer['type'].toString()); }
    var centroid = [0,0];
    for(var i = 0; i < this.deployment_buffer['vertices'].length; i++) {
        centroid = vec_add(centroid, this.deployment_buffer['vertices'][i]);
    }
    centroid = vec_scale(1.0/this.deployment_buffer['vertices'].length, centroid);
    return centroid;
};

// returns whether combat units can be deployed (by the player) at this location
Base.Base.prototype.is_deployment_location_valid = function(xy) {
    var ncells = this.ncells();

    // check against play area bounds
    if(xy[0] < 0 || xy[0] >= ncells[0] || xy[1] < 0 || xy[1] >= ncells[1]) {
        return false;
    }

    if(this.base_landlord_id === session.user_id) {
        return true; // landlord can deploy anywhere
    }

    // check against base perimeter or deployment zone
    if(this.has_deployment_zone()) {
        // Gangnam style
        if(this.deployment_buffer['type'] != 'polygon') { throw Error('unhandled deployment buffer type'+this.deployment_buffer['type'].toString()); }
        // point-in-polygon test via winding order
        var sign = 0;
        for(var i = 0; i < this.deployment_buffer['vertices'].length; i++) {
            var iend = ((i+1) % this.deployment_buffer['vertices'].length);
            var start = this.deployment_buffer['vertices'][i];
            var end = this.deployment_buffer['vertices'][iend];
            var seg = vec_sub(end, start);
            var point = vec_sub(xy, start);
            var k = seg[0]*point[1] - seg[1]*point[0];
            var sign_k = (k >= 0 ? 1 : -1);
            if(sign == 0) {
                sign = sign_k;
            } else if(sign_k != sign) {
                return false;
            }
        }
    } else if(gamedata['map']['deployment_buffer'] >= 0) {
        // old style
        var mid = this.midcell();
        var rad = [this.get_base_radius(), this.get_base_radius()];

        if(this.deployment_buffer) { rad[0] += gamedata['map']['deployment_buffer']; rad[1] += gamedata['map']['deployment_buffer']; }
        rad[0] += Math.max(0, (ncells[0] - gamedata['map']['default_ncells'][0])/2);
        rad[1] += Math.max(0, (ncells[1] - gamedata['map']['default_ncells'][1])/2);
        if(xy[0] >= mid[0]-rad[0] && xy[0] <= mid[0]+rad[0] && xy[1] >= mid[1]-rad[1] && xy[1] <= mid[1]+rad[1]) {
            return false;
        }
    }

    // check against blockage from buildings
    if(astar_map.is_blocked(vec_floor(xy))) {
        return false;
    }

    // check building deployment buffer
    if((gamedata['map']['building_deployment_buffer']||0) > 0) {
        var buf = gamedata['map']['building_deployment_buffer'];
        for(var id in session.cur_objects.objects) {
            var obj = session.cur_objects.objects[id];
            if(obj.is_building() && obj.team != 'player') {
                var hisbound = get_grid_bounds([obj.x,obj.y], obj.spec['gridsize']);
                if(xy[0] >= hisbound[0][0]-buf && xy[0] < hisbound[0][1]+buf &&
                   xy[1] >= hisbound[1][0]-buf && xy[1] < hisbound[1][1]+buf) {
                    return false;
                }
            }
        }
    }
    return true;
};

// stroke a path outlining the base area perimeter
// optionally shade either the inside or outside to indicate invalid locations
Base.Base.prototype.draw_base_perimeter = function(purpose) {
    var ncells = this.ncells();
    var mid = this.midcell();
    var rad = [this.get_base_radius(), this.get_base_radius()];
    var old_deployment_buffer = (!!this.deployment_buffer && !this.has_deployment_zone());
    var new_deployment_buffer = this.has_deployment_zone();
    var open_deployment = gamedata['map']['deployment_buffer'] < 0;

    var shade_inside = (purpose === 'deploy' && (this.base_landlord_id !== session.user_id) && !open_deployment);
    var stroke_inside = (purpose === 'pre_deploy' && !open_deployment); // purpose.indexOf('deploy') >= 0);
    var shade_outside = (purpose === 'build');
    var stroke_outside = !stroke_inside && (purpose != 'build_ignore_perimeter' && !(purpose.indexOf('deploy') >= 0 && open_deployment) && !new_deployment_buffer);
    var shade_offmap = (purpose !== 'dev_edit');

    //console.log('shade_inside '+shade_inside.toString()+' stroke_inside '+stroke_inside.toString()+' shade_outside '+shade_outside.toString()+' stroke_outside '+stroke_outside.toString());

    if(purpose.indexOf('deploy') >= 0 && old_deployment_buffer) {
        if(gamedata['map']['deployment_buffer'] >= 0) {
            rad[0] += gamedata['map']['deployment_buffer'];
            rad[1] += gamedata['map']['deployment_buffer'];
        }
        rad[0] += Math.max(0, (ncells[0] - gamedata['map']['default_ncells'][0])/2);
        rad[1] += Math.max(0, (ncells[1] - gamedata['map']['default_ncells'][1])/2);
    }

    // vertices of base perimeter
    var v = [draw_quantize(ortho_to_draw([mid[0]-rad[0], mid[1]-rad[1]])),
             draw_quantize(ortho_to_draw([mid[0]+rad[0], mid[1]-rad[1]])),
             draw_quantize(ortho_to_draw([mid[0]+rad[0], mid[1]+rad[1]])),
             draw_quantize(ortho_to_draw([mid[0]-rad[0], mid[1]+rad[1]]))];

    SPUI.ctx.save();
    SPUI.ctx.fillStyle = 'rgba(255,0,0,0.25)';
    var deploy_zone_outline_color = 'rgba(255,255,0,0.25)';
    var deploy_zone_outline_width = 7;

    if(shade_inside || stroke_inside) {
        SPUI.ctx.save();

        if(new_deployment_buffer) {
            // Gangnam style
            if(this.deployment_buffer['type'] != 'polygon') { throw Error('unhandled deployment buffer type'+this.deployment_buffer['type'].toString()); }
            SPUI.ctx.beginPath();

            if(shade_inside) {
                // vertices of entire play area
                var outer = [ortho_to_draw([0, 0]),
                             ortho_to_draw([ncells[0], 0]),
                             ortho_to_draw([ncells[0], ncells[1]]),
                             ortho_to_draw([0, ncells[1]])];
                for(var i = 0; i < outer.length; i++) {
                    var vtx = outer[i];
                    if(i == 0) {
                        SPUI.ctx.moveTo(vtx[0], vtx[1]);
                    } else {
                        SPUI.ctx.lineTo(vtx[0], vtx[1]);
                    }
                }
                SPUI.ctx.closePath();
            }

            // add the deployment zone as a subpath with reverse winding order to make a "hole"
            for(var i = 0; i < this.deployment_buffer['vertices'].length; i++) {
                var vtx = this.deployment_buffer['vertices'][this.deployment_buffer['vertices'].length - i - 1];
                var loc = ortho_to_draw(vtx);
                if(i == 0) {
                    SPUI.ctx.moveTo(loc[0], loc[1]);
                } else {
                    SPUI.ctx.lineTo(loc[0], loc[1]);
                }

            }
            SPUI.ctx.closePath();

            if(shade_inside) {
                SPUI.ctx.fill();
                SPUI.ctx.strokeStyle = 'rgba(255,255,255,1)';
            }
            if(stroke_inside) { // override stroke color
                SPUI.ctx.strokeStyle = deploy_zone_outline_color;
                SPUI.ctx.lineWidth = deploy_zone_outline_width;
            }
            SPUI.ctx.stroke();

        } else {
            if(shade_inside) {
                shade_quad(v);
            }
            if(stroke_inside) {
                SPUI.ctx.beginPath();
                SPUI.add_quad_to_path(v);
                SPUI.ctx.strokeStyle = deploy_zone_outline_color;
                SPUI.ctx.lineWidth = deploy_zone_outline_width;
                SPUI.ctx.stroke();
            }
        }
        SPUI.ctx.restore();
    }

    if(shade_outside) {
        // all across the top
        shade_quad_quantize([ortho_to_draw([0,0]), ortho_to_draw([ncells[0], 0]), ortho_to_draw([ncells[0], mid[1]-rad[1]]), ortho_to_draw([0, mid[1]-rad[1]])]);
        // left side
        shade_quad_quantize([ortho_to_draw([0,mid[1]-rad[1]]), ortho_to_draw([mid[0]-rad[0], mid[1]-rad[1]]), ortho_to_draw([mid[0]-rad[0], mid[1]+rad[1]]), ortho_to_draw([0, mid[1]+rad[1]])]);
        // right side
        shade_quad_quantize([ortho_to_draw([mid[0]+rad[0],mid[1]-rad[1]]), ortho_to_draw([ncells[0], mid[1]-rad[1]]), ortho_to_draw([ncells[0], mid[1]+rad[1]]), ortho_to_draw([mid[0]+rad[0], mid[1]+rad[1]])]);
        // all across the bottom
        shade_quad_quantize([ortho_to_draw([0,mid[1]+rad[1]]), ortho_to_draw([ncells[0], mid[1]+rad[1]]), ortho_to_draw([ncells[0], ncells[1]]), ortho_to_draw([0, ncells[1]])]);
    }

    /* XXX this is broken in view_is_zoomed case
    if(shade_offmap) {
        var top = ortho_to_draw([0,0]), right = ortho_to_draw([ncells[0], 0]), bottom = ortho_to_draw([ncells[0], ncells[1]]), left = ortho_to_draw([0, ncells[1]]);
        // bar across the top
        if(top[1] > 0) { shade_quad_quantize([[0,0], [canvas_width,0], [canvas_width, top[1]], [0, top[1]]]); }
        // upper-left quad
        shade_quad_quantize([[0,top[1]], top, left, [0,left[1]]]);
        // lower-left quad
        shade_quad_quantize([[0,left[1]], left, bottom, [0,bottom[1]]]);
        // upper-right quad
        shade_quad_quantize([top, [canvas_width,top[1]], [canvas_width,right[1]], right]);
        // lower-right quad
        shade_quad_quantize([right, [canvas_width,right[1]], [canvas_width,bottom[1]], bottom]);
        // bar across the bottom
        if(bottom[1] < canvas_height) { shade_quad_quantize([[0,bottom[1]], [canvas_width,bottom[1]], [canvas_width,canvas_height], [0,canvas_height]]); }
    }
    */

    // draw thin outline, for guiding building placement
    if(stroke_outside) {
        SPUI.ctx.beginPath();
        SPUI.add_quad_to_path(v);
        SPUI.ctx.strokeStyle = 'rgba(255,255,255,1)';
        SPUI.ctx.stroke();
    }

    SPUI.ctx.restore();
};
