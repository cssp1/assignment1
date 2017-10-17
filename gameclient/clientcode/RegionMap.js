goog.provide('RegionMap');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('SPUI');
goog.require('SPFX');
goog.require('GameArt');
goog.require('ItemDisplay');
goog.require('SquadControlDialog');
goog.require('PlayerInfoDialog');
goog.require('Region');
goog.require('goog.array');
goog.require('goog.string');

// note: this references some stuff from main.js (player.travel_state etc)

/** @constructor @struct
    @param {!RegionMap.RegionMap} map */
RegionMap.Cursor = function(map) {
    this.map = map;
};
RegionMap.Cursor.prototype.on_mousemove = function(cell) { return false; };
RegionMap.Cursor.prototype.allow_drag = function() { return true; };
RegionMap.Cursor.prototype.allow_label = function(cell) { return true; };

/** @param {Array.<number>} cell
    @param {string} text_str
    @param {string} text_color
    @param {number} text_size
    @param {Array.<number>=} extra_offset */
RegionMap.Cursor.prototype.draw_text_at_cell = function(cell, text_str, text_color, text_size, extra_offset) {
    if(!extra_offset) { extra_offset = [0,0]; }
    var cell_xy = this.map.cell_to_field(cell);
    this.map.draw_feature_label(vec_add(vec_add(cell_xy, vec_add(vec_scale(0.5, gamedata['territory']['cell_size']), [0,0.3*this.map.font.leading*text_size])), vec_scale(1.0/this.map.zoom, extra_offset)),
                                [text_str], text_color, text_size);
};

/** @constructor @struct
  * @extends RegionMap.Cursor */
RegionMap.DeployCursor = function(map, from_loc, squad_id, icon_assetname) {
    goog.base(this, map);
    this.from_loc = from_loc;
    this.squad_id = squad_id;
    this.icon_assetname = icon_assetname;
};
goog.inherits(RegionMap.DeployCursor, RegionMap.Cursor);
RegionMap.DeployCursor.prototype.allow_drag = function() { return false; };
RegionMap.DeployCursor.prototype.allow_label = function(cell) { return !(vec_equals(cell, this.from_loc) || hex_distance(cell, this.from_loc) <= 1); };

RegionMap.DeployCursor.prototype.draw = function() {
    var squad_data = player.squads[this.squad_id.toString()];
    if(!squad_data) {
        this.map.cursor = null;
        console.log('DeployCursor: no data for squad '+this.squad_id.toString());
        return;
    }

    SPUI.ctx.save();
    var text_size = 1.5;

    // draw RED cancel on from_loc
    SPUI.ctx.fillStyle = SPUI.ctx.strokeStyle = 'rgba(255,0,0,0.3)';
    this.map.make_hex_outline_path(this.map.cell_to_field(this.from_loc));
    SPUI.ctx.fill();
    SPUI.ctx.stroke();
    this.draw_text_at_cell(this.from_loc, gamedata['strings']['regional_map']['cancel_deployment'],
                           'rgba(255,0,0,' + (this.map.hovercell && vec_equals(this.from_loc, this.map.hovercell) ? '1.0' : '0.75') + ')',
                           text_size);

    // draw neighbor cells
    var neighbors = this.map.region.get_neighbors(this.from_loc);
    goog.array.forEach(neighbors, function(loc) {
        var is_obstacle = this.map.region.obstructs_squads(loc);
        var is_blocked = this.map.region.occupancy.is_blocked(loc, player.make_squad_cell_checker());
        var text_color = null, text_str = null;
        var text_alpha = (this.map.hovercell && vec_equals(loc, this.map.hovercell) ? '1.0 ' : '0.7');
        var cell_alpha = (this.map.hovercell && vec_equals(loc, this.map.hovercell) ? '0.4' : '0.2');

        if(is_obstacle || is_blocked) {
            var blocker = this.map.region.find_feature_at_coords(loc);
            if(blocker && blocker['base_type'] == 'squad' && blocker['base_landlord_id'] != session.user_id && player.squad_combat_enabled() && !this.map.region.feature_is_moving(blocker)) {
                text_color = 'rgba(255,255,0,';
                text_str = gamedata['strings']['regional_map']['fight_to_escape'];
            } else {
                text_color = 'rgba(255,0,0,';
                text_str = gamedata['strings']['regional_map']['deployment_blocked'];
            }
        } else {
            text_color = 'rgba(0,255,0,';
            text_str = gamedata['strings']['regional_map'][(('map_loc' in squad_data) ? 'withdraw' : 'do_deployment')];
        }

        SPUI.ctx.fillStyle = SPUI.ctx.strokeStyle = text_color+cell_alpha+')';
        this.map.make_hex_outline_path(this.map.cell_to_field(loc));
        SPUI.ctx.fill(); SPUI.ctx.stroke();
        this.draw_text_at_cell(loc, text_str, text_color+text_alpha+')', text_size);

    }, this);

    // transparent unit icon
    if(this.map.hovercell && hex_distance(this.map.hovercell, this.from_loc) == 1) {
        if(!this.map.region.occupancy.is_blocked(this.map.hovercell, player.make_squad_cell_checker())) {
            var hover_xy = this.map.cell_to_field(this.map.hovercell);
            SPUI.ctx.globalAlpha = 0.8;
            GameArt.assets[this.icon_assetname].states['normal'].draw(vec_add(hover_xy, vec_scale(0.5,gamedata['territory']['cell_size'])), 0, 0);
            SPUI.ctx.globalAlpha = 1;
        }
    }

    SPUI.ctx.restore();
};
RegionMap.DeployCursor.prototype.on_mouseup = function(cell, button) {
    if(!cell) { return false; }
    var squad_data = player.squads[this.squad_id.toString()];

    if((cell[0] == this.from_loc[0] && cell[1] == this.from_loc[1]) ||
       button.get_button(SPUI.MouseButton.RIGHT)) {
        // cancel
        this.map.cursor = null;
        return true;
    }
    if(hex_distance(cell, this.from_loc) == 1) {
        if(this.map.region.obstructs_squads(cell)) { return true; } // obstructed

        if(this.map.region.occupancy.is_blocked(cell, player.make_squad_cell_checker())) {
            var blocker = this.map.region.find_feature_at_coords(cell);
            if(blocker && blocker['base_type'] == 'squad' && blocker['base_landlord_id'] != session.user_id && !this.map.region.feature_is_moving(blocker)) {
                if(player.squad_combat_enabled()) {
                    do_visit_base(-1, {base_id: blocker['base_id']});
                }
                this.map.cursor = null;
                return true;
            }
            return true;
        }

        // valid deployment location
        if('map_loc' in squad_data) {
            // squad already deployed - withdrawing from quarry
            player.squad_move(this.squad_id, [cell]);
        } else {
            squad_data['pending'] = true;
            send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "SQUAD_ENTER_MAP", this.squad_id, cell, null]);
        }
        this.map.cursor = null;
        return true;
    }
    return true;
};

/** @constructor @struct
  * @extends RegionMap.Cursor */
RegionMap.MoveCursor = function(map, from_loc, squad_id, icon_specname) {
    goog.base(this, map);
    this.from_loc = from_loc;
    this.squad_id = squad_id;
    this.icon_unit_spec = (icon_specname ? gamedata['units'][icon_specname] : null);
    /** @type {Array<!Array<number>>|null} */
    this.path = null;

    this.cached_dest = null;
    this.cached_path = null;
    this.cached_status = null;
};
goog.inherits(RegionMap.MoveCursor, RegionMap.Cursor);

RegionMap.MoveCursor.prototype.on_mousemove = function(cell) {
    if(!cell) { return false; }
    if(this.cached_dest && !vec_equals(cell, this.cached_dest)) {
        this.cached_dest = null; // clear cache
    }
    return false;
};

RegionMap.MoveCursor.prototype.get_path = function(cell) {
    if(this.cached_dest && vec_equals(cell, this.cached_dest)) {
        this.path = this.cached_path;
    } else {
        this.cached_status = this.do_get_path(cell);
        this.cached_dest = cell;
        this.cached_path = this.path;
    }
    return this.cached_status;
};

RegionMap.MoveCursor.prototype.do_get_path = function(cell) {
    this.path = null;

    if(this.map.region.in_bounds(cell)) {
        if(cell[0] == this.from_loc[0] && cell[1] == this.from_loc[1]) {
            return {'action':'cancel',
                    'ui_name': gamedata['strings']['regional_map']['cancel_movement'],
                    'text_color': 'rgba(255,0,0,1.0)'};
        }

        var feature_list;
        var is_my_home = false, is_my_quarry = false, is_blocked = false, is_bumpable = false;

        if(this.map.region.obstructs_squads(cell)) { // mountain?
            is_blocked = true; feature_list = [];
        } else {
            feature_list = this.map.region.find_features_at_coords(cell);
        }

        goog.array.forEach(feature_list, function(f) {
            if(f['base_type'] == 'home' && f['base_landlord_id'] == session.user_id) {
                is_my_home = true;
            } else if(f['base_type'] == 'quarry' && f['base_landlord_id'] == session.user_id) {
                is_my_quarry = true;
                if(!player.quarry_guards_enabled() || feature_list.length >= 2) {
                    is_blocked = true; // your own quarry, and a second feature is already there, so no additional guard is allowed
                }
            } else if(f['base_type'] == 'squad' && f['base_landlord_id'] == session.user_id && parseInt(f['base_id'].split('_')[1],10) == this.squad_id) {
                return; // don't block ourself
            } else if(this.map.region.feature_blocks_map(f)) {
                if(f['base_type'] == 'squad' && this.map.region.feature_is_moving(f) && player.squad_bumping_enabled()) {
                    is_bumpable = true;
                } else {
                    is_blocked = true;
                }
            }
        }, this);

        if(is_my_home || (is_my_quarry && !is_blocked)) {
            // see if we have a path that leads up to it
            if(hex_distance(player.squads[this.squad_id.toString()]['map_loc'], cell) == 1) {
                this.path = []; // 1 step away
            } else {
                // not good path, try another adjacent destination
                this.path = player.squad_find_path_adjacent_to(this.squad_id, cell);
            }

            if(this.path !== null) {
                if(is_my_quarry || (is_my_home && player.squad_is_raid(this.squad_id))) {
                    // have to add the final jump manually
                    this.path.push(cell);
                }
                return {'action': (is_my_home ? 'recall' : 'move'),
                        'ui_name': gamedata['strings']['regional_map'][(is_my_home ? 'recall' : 'guard')],
                        'text_color': (is_my_home ? 'rgba(128,255,128,1.0)' : 'rgba(128,200,255,1.0)')};
            } else {
                // cannot get to home or friendly quarry
                return {'action':'blocked',
                        'ui_name': gamedata['strings']['regional_map']['movement_blocked'],
                        'text_color': 'rgba(255,0,0,1.0)'};
            }
        } else if(is_blocked) {
            // destination occupied
            this.path = player.squad_find_path_adjacent_to(this.squad_id, cell); // show path as far as we can go
            return {'action':'blocked',
                    'ui_name': gamedata['strings']['regional_map']['movement_blocked'],
                    'text_color': 'rgba(255,0,0,1.0)'};
        } else {
            // allow you to bump your own moving squads only when using manual cursor movement
            this.path = player.squad_find_path_adjacent_to(this.squad_id, cell, {bump_self: true});
            if(!this.path || this.path.length<1 || !vec_equals(this.path[this.path.length-1], cell)) {
                return {'action':'blocked',
                        'ui_name': gamedata['strings']['regional_map']['movement_blocked'],
                        'text_color': 'rgba(255,0,0,1.0)'};
            } else {
                return {'action':'move',
                        'ui_name': gamedata['strings']['regional_map']['do_movement'],
                        'text_color': 'rgba(128,255,128,1.0)'};
            }
        }
    }
    return null;
};

RegionMap.MoveCursor.prototype.draw = function() {
    // avoid race condition that causes crash in get_path() when squad is already in motion
    // (MoveCursor should not be able to be used when squad is already moving)
    if(!player.squad_is_deployed(this.squad_id) || player.squad_is_moving(this.squad_id)) {
        this.map.cursor = null;
        return;
    }

    SPUI.ctx.save();

    // draw RED cancel on from_loc
    SPUI.ctx.fillStyle = 'rgba(255,0,0,0.33)';
    this.map.make_hex_outline_path(this.map.cell_to_field(this.from_loc));
    SPUI.ctx.fill();

    if(this.map.hovercell) {
        var status = this.get_path(this.map.hovercell);
        if(status) {
            if(this.path && this.path.length >= 1) {
                ctx.save();
                ctx.strokeStyle = gamedata['client']['unit_control_colors'][(status['action'] == 'blocked' ? 'amove_now' : 'move_now')];
                ctx.lineWidth = 2;
                var drawn_path = [this.map.cell_to_field(this.from_loc)];
                for(var i = 0; i < this.path.length; i++) { drawn_path.push(this.map.cell_to_field(this.path[i]));  }
                if(status['action'] == 'recall') {
                    // add extra segment to home base
                    drawn_path.push(this.map.cell_to_field(this.map.hovercell));
                }
                this.map.draw_movement_path(drawn_path);
                ctx.restore();
            }

            if(status['action'] == 'move' && this.icon_unit_spec) {
                // draw transparent unit icon
                var hover_xy = this.map.cell_to_field(this.map.hovercell);
                SPUI.ctx.globalAlpha = 0.5;
                GameArt.assets[get_leveled_quantity(this.icon_unit_spec['art_asset'],1)].states['normal'].draw(vec_add(hover_xy, vec_scale(0.5,gamedata['territory']['cell_size'])), 0, 0);
                SPUI.ctx.globalAlpha = 1;
            }
            this.draw_text_at_cell(this.map.hovercell, status['ui_name'], status['text_color'], 1.5);

            // draw travel time
            if(this.path && this.path.length >= 1) {
                var travel_time = player.squad_travel_time(this.squad_id, this.path);
                var txt = pretty_print_time_brief(travel_time);
                var dims = SPUI.ctx.measureText(txt);
                this.draw_text_at_cell((status['action'] == 'recall' ? this.map.hovercell : this.path[this.path.length-1]), txt, status['text_color'], 1.0, [0,16]);
            }
        }
    }

    SPUI.ctx.restore();
};

RegionMap.MoveCursor.prototype.on_mouseup = function(cell, button) {
    if(!player.squad_is_deployed(this.squad_id) || player.squad_is_moving(this.squad_id)) {
        this.map.cursor = null;
        return false;
    }

    if(!cell) { return false; }
    var status = this.get_path(cell);
    if(!status) { return false; }

    if(status['action'] == 'cancel' || button.get_button(SPUI.MouseButton.RIGHT)) {
        this.map.cursor = null;
        return true;
    } else if(status['action'] == 'move' || status['action'] == 'recall' || (status['action'] == 'blocked' && this.path && this.path.length >= 1)) {

        // note: when blocked, treat a click as a move to the end of the current path
        if(status['action'] == 'move' || status['action'] == 'blocked') {
            player.squad_move(this.squad_id, this.path);
        } else if(status['action'] == 'recall') {
            player.squad_recall(this.squad_id, this.path);
        }

        // play movement sound
        if(this.icon_unit_spec && 'sound_destination' in this.icon_unit_spec) {
            GameArt.play_canned_sound(this.icon_unit_spec['sound_destination']);
        }

        this.map.cursor = null;
    } else {
        // invalid movement location
    }

    return true;
};


/** @constructor @struct
  * @extends RegionMap.Cursor */
RegionMap.RelocateCursor = function(map) {
    goog.base(this, map);
};
goog.inherits(RegionMap.RelocateCursor, RegionMap.Cursor);

RegionMap.RelocateCursor.prototype.relocate_status = function(cell) {
    if(this.map.region.in_bounds(cell)) {
        // check home base
        if(vec_equals(cell, player.home_base_loc)) {
            return {'action':'cancel',
                    'ui_name': gamedata['strings']['regional_map']['cancel_movement'],
                    'text_color': 'rgba(255,0,0,1.0)'};
        }

        // check map boundary
        var BORDER = gamedata['territory']['border_zone_player'];
        var map_dims = this.map.region.data['dimensions'];
        if(cell[0] < BORDER || cell[0] >= map_dims[0]-BORDER ||
           cell[1] < BORDER || cell[1] >= map_dims[1]-BORDER) {
            return {'action':'blocked',
                    'ui_name': gamedata['strings']['regional_map']['too_close_to_border'],
                    'text_color': 'rgba(255,0,0,1.0)'};
        }

        // check for interfering bases
        var too_close_to_object = false;
        var exclusive = gamedata['territory']['exclusive_zone_player'];
        if(exclusive > 0) {
            for(var y = cell[1]-exclusive; y <= cell[1]+exclusive; y++) {
                for(var x = cell[0]-exclusive; x <= cell[0]+exclusive; x++) {
                    if(this.map.region.occupancy.is_blocked([x,y])) {
                        too_close_to_object = true;
                        break;
                    }
                }
            }
        }

        if(too_close_to_object) {
            return {'action':'blocked',
                    'ui_name': gamedata['strings']['regional_map']['too_close_to_player'],
                    'text_color': 'rgba(255,0,0,1.0)'};
        }

        return {'action':'relocate',
                'ui_name': gamedata['strings']['regional_map']['relocate'],
                'text_color': 'rgba(128,255,128,1.0)'};
    }
    return null;
};


RegionMap.RelocateCursor.prototype.draw = function() {
    SPUI.ctx.save();

    // draw RED cancel on from_loc
    SPUI.ctx.fillStyle = 'rgba(255,0,0,0.33)';
    this.map.make_hex_outline_path(this.map.cell_to_field(player.home_base_loc));
    SPUI.ctx.fill();

    if(this.map.hovercell) {
        var status = this.relocate_status(this.map.hovercell);
        if(status) {
            if(status['action'] == 'relocate') {
                // draw transparent base icon
                var hover_xy = this.map.cell_to_field(this.map.hovercell);
                var cover = gamedata['territory']['cell_overlap'];
                SPUI.ctx.globalAlpha = 0.5;
                GameArt.assets['region_tiles'].states['base'].draw_topleft(vec_sub(hover_xy, cover), 0, 0);
                SPUI.ctx.globalAlpha = 1;
            }
            this.draw_text_at_cell(this.map.hovercell, status['ui_name'], status['text_color'], 1.5);
        }
    }

    SPUI.ctx.restore();
};

RegionMap.RelocateCursor.prototype.on_mouseup = function(cell, button) {
    if(!cell) { return false; }
    var status = this.relocate_status(cell);
    if(!status) { return false; }
    if(status['action'] == 'cancel' || button.get_button(SPUI.MouseButton.RIGHT)) {
        this.map.cursor = null;
    } else if(status['action'] == 'relocate') {
        this.map.cursor = null;
        change_region(this.map.region.data['id'], cell);
        return true;
    }
    return true;
};


// COORDINATE SYSTEMS
// "cell"/"loc" = hexagonal grid squares
// "field" = pixels AT ZOOM=1, where [0,0] is the upper-left corner of the MAP (cell 0,0)
// "widget" = post zoom and pan, where [0,0] is the upper-left corner of the widget

// NOTE: ALL CANVAS DRAWING IS DONE IN "FIELD" COORDINATES!
// the field->widget transform is done on the Canvas transform stack

/** @constructor @struct
    @extends SPUI.DialogWidget
    @param {!SPFX.FXWorld} fxworld */
RegionMap.RegionMap = function(data, fxworld) {
    goog.base(this, data);
    this.gfx_detail = 99;
    /** @type {Region.Region|null} */
    this.region = null;
    this.time = -1; // the caller should update this per-frame
    this.hstar_context = null;

    // input goes to zoom_linear but is then passed through exp() to control the actual zoom,
    // so that expansion/contraction is linear in mousewheel movement

    this.zoom_linear = 0;
    this.zoom = Math.exp(this.zoom_linear);

    this.pan = [0,0]; // location displayed at center of widget, in "field" coordinates
    this.pan_limits = [[0,0],[0,0]]; // in "field" coordinates
    this.pan_goal = null; // if non-null, goal for slow pan movement

    this.zoom_limits = goog.array.clone(gamedata['territory']['zoom_limits']);

    this.selection_loc = null; // coordinates of selected cell
    this.selection_feature = null; // feature at selected cell
    this.hovercell = null; // coordinates of cell under mouse pointer
    this.hover_alliance = -1; // alliance ID to highlight on map
    this.popup = null; // UI associated with the selection
    this.drag_start = null;
    this.drag_full = false;
    this.follow_travel = true;
    this.zoom_in_button = null;
    this.zoom_out_button = null;
    this.font = SPUI.make_font(14, 17, 'thick');
    this.cursor = null;

    if(!fxworld) {
        throw Error('constructed RegionMap with bad fxworld');
    }
    this.fxworld = fxworld;
    this.spfx_list = [];

    this.zoom_to_default();
};
goog.inherits(RegionMap.RegionMap, SPUI.DialogWidget);

/** @override */
RegionMap.RegionMap.prototype.destroy = function() {
    // kill any ongoing SPFX instances
    goog.array.forEach(this.spfx_list, function(fx) { this.fxworld.remove(fx); }, this);
};

// save/restore state, for reloading the map after session changes
RegionMap.RegionMap.prototype.get_state = function() {
    return {'pan':this.pan, 'zoom_linear':this.zoom_linear};
};
RegionMap.RegionMap.prototype.set_state = function(state) {
    this.pan = state['pan']; this.set_zoom_linear(state['zoom_linear']);
    this.follow_travel = false;
};

RegionMap.RegionMap.prototype.set_popup = function(newui) {
    if(!this.parent) { return; } // dialob was closed
    if(this.popup) { this.parent.remove(this.popup); }
    this.popup = newui;
    if(this.popup) { this.parent.add(this.popup); }
};

/** @param {Region.Region|null} region */
RegionMap.RegionMap.prototype.set_region = function(region) {
    this.region = region;
    this.hstar_context = region.hstar_context;
    this.go_home();
    this.zoom_to_default();
};

RegionMap.RegionMap.prototype.set_zoom_buttons = function(zoom_in_button, zoom_out_button) {
    this.zoom_in_button = zoom_in_button; this.zoom_out_button = zoom_out_button;
    this.zoom_in_button.onclick = (function (_this) { return function(w) { _this.zoom_in(); }; })(this);
    this.zoom_out_button.onclick = (function (_this) { return function(w) { _this.zoom_out(); }; })(this);
    this.set_zoom_button_states();
};
RegionMap.RegionMap.prototype.zoom_in = function() {
    this.set_zoom_linear(this.zoom_linear + 0.3);
};
RegionMap.RegionMap.prototype.zoom_out = function() {
    this.set_zoom_linear(this.zoom_linear - 0.3);
};
RegionMap.RegionMap.prototype.set_zoom_linear = function(new_value) {
    this.set_popup(null);
    this.follow_travel = false;
    this.zoom_linear = clamp(new_value, this.zoom_limits[0], this.zoom_limits[1]);
    this.zoom = Math.exp(this.zoom_linear);
    //console.log('ZOOM '+this.zoom_linear+' -> '+this.zoom);
    this.set_zoom_button_states();
};
RegionMap.RegionMap.prototype.set_zoom_button_states = function() {
    if(!this.zoom_in_button || !this.zoom_out_button) { return; }
    this.zoom_in_button.state = (this.zoom_linear >= this.zoom_limits[1] ? 'disabled' : 'normal');
    this.zoom_out_button.state = (this.zoom_linear <= this.zoom_limits[0] ? 'disabled' : 'normal');
};
RegionMap.RegionMap.prototype.zoom_all_the_way_in = function() {
    this.set_zoom_linear(this.zoom_limits[1]);
};
RegionMap.RegionMap.prototype.zoom_to_default = function() {
    this.set_zoom_linear(gamedata['territory']['default_zoom'+(this.region && this.region.data && this.region.data['storage'] == 'nosql' ? '_nosql' : '')]);
};
RegionMap.RegionMap.prototype.invoke_deploy_cursor = function(from_loc, squad_id, icon_assetname) {
    this.cursor = new RegionMap.DeployCursor(this, from_loc, squad_id, icon_assetname);
    this.follow_travel = false;
    this.pan_to_cell(from_loc);
    this.zoom_all_the_way_in();
};

/**
 *  @param {{do_select:(boolean|undefined),
 *           with_zoom:(boolean|undefined),
 *           slowly:(boolean|undefined)}=} options
 */
RegionMap.RegionMap.prototype.go_home = function(options) {
    var home_loc = player.home_base_loc;
    if(home_loc) {
        this.pan_to_cell(home_loc, options);
        if(options && options.do_select) {
            this.select_feature_at(home_loc);
        }
    } else {
        this.pan_to_cell([this.region.data['dimensions'][0]/2, this.region.data['dimensions'][1]/2], options);
    }
    if(!this.cursor && this.follow_travel) {
        this.zoom_to_default();
    }
};

/**
 *  @param {Array.<number>} loc
 *           with_zoom:(boolean|undefined),
 *  @param {{slowly:(boolean|undefined)}=} options
 */
RegionMap.RegionMap.prototype.pan_to_cell = function(loc, options) {
    var fxy = this.cell_to_field(loc);
    this.pan_to_field([fxy[0] + gamedata['territory']['cell_size'][0]/2,
                       fxy[1] + gamedata['territory']['cell_size'][1]/2], options);
};

/**
 *  @param {Array.<number>} fxy
 *           with_zoom:(boolean|undefined),
 *  @param {{slowly:(boolean|undefined)}=} options
 */
RegionMap.RegionMap.prototype.pan_to_field = function(fxy, options) {
    if(options && options.slowly) {
        this.pan_goal = [fxy[0], fxy[1]];
    } else {
        this.pan_goal = null;
        this.pan = [fxy[0], fxy[1]];
    }
};

// returns field coordinate of upper-left corner of the cell
RegionMap.RegionMap.prototype.cell_to_field = function(cxy) {
    return [cxy[0]*gamedata['territory']['cell_size'][0] + (cxy[1]&1 ? gamedata['territory']['cell_rowoffset'][0]:0),
            cxy[1]*gamedata['territory']['cell_rowoffset'][1]];
};

// the "non-precise" field_to_cell treats cells as rectangles,
// whereas the "precise" version takes into account the actual hex shape

RegionMap.RegionMap.prototype.field_to_cell_unclamped = function(fxy) {
    var row = Math.floor(fxy[1]/gamedata['territory']['cell_rowoffset'][1]);
    var col = Math.floor((fxy[0]-(row&1 ? gamedata['territory']['cell_rowoffset'][0]:0))/gamedata['territory']['cell_size'][0]);
    return [col, row];
};

RegionMap.RegionMap.prototype.field_to_cell = function(fxy) {
    var col_row = this.field_to_cell_unclamped(fxy);
    col_row[0] = clamp(col_row[0], 0, this.region.data['dimensions'][0]-1);
    col_row[1] = clamp(col_row[1], 0, this.region.data['dimensions'][1]-1);
    return col_row;
};

RegionMap.RegionMap.prototype.field_to_cell_precise = function(fxy) {
    var cxy = this.field_to_cell(fxy);

    // may need to kick it up or down a row due to the triangular corners
    var cel = this.cell_to_field(cxy);
    var rel = [fxy[0]-cel[0], fxy[1]-cel[1]];
    var side = (rel[0] < gamedata['territory']['cell_size'][0]/2 ? 0 : 1);

    var delta = Math.abs((gamedata['territory']['cell_size'][0]/2) - rel[0]) / (gamedata['territory']['cell_size'][0]/2);
    delta *= gamedata['territory']['cell_hexinset'];
    if(rel[1] < gamedata['territory']['cell_size'][1]/2) {
        var move = rel[1] < delta;
        if(move) {
            //console.log('UPPER');
            cxy[1] -= 1;
            cxy[0] += side + (cxy[1] & 1 ? -1 : 0);
        }
    } else {
        // hmm this case never gets triggered
        var move = (gamedata['territory']['cell_size'][1]-rel[1]) < delta;
        if(move) {
            //console.log('LOWER');
            cxy[1] += 1;
            cxy[0] += side + (cxy[1] & 1 ? -1 : 0);
        }
    }

    cxy[0] = clamp(cxy[0], 0, this.region.data['dimensions'][0]-1);
    cxy[1] = clamp(cxy[1], 0, this.region.data['dimensions'][1]-1);
    return cxy;
};

RegionMap.RegionMap.prototype.field_to_widget = function(fxy) {
    return [this.zoom*(fxy[0] - this.pan[0])+this.wh[0]/2,
            this.zoom*(fxy[1] - this.pan[1])+this.wh[1]/2];
};
RegionMap.RegionMap.prototype.widget_to_field = function(wxy) {
    return [(wxy[0]-this.wh[0]/2)/this.zoom + this.pan[0],
            (wxy[1]-this.wh[1]/2)/this.zoom + this.pan[1]];
};

RegionMap.RegionMap.prototype.cell_to_widget = function(cxy) {
    return this.field_to_widget(this.cell_to_field(cxy));
};

RegionMap.RegionMap.prototype.widget_to_cell = function(wxy) {
    return this.field_to_cell(this.widget_to_field(wxy));
};
RegionMap.RegionMap.prototype.widget_to_cell_unclamped = function(wxy) {
    return this.field_to_cell_unclamped(this.widget_to_field(wxy));
};
RegionMap.RegionMap.prototype.widget_to_cell_precise = function(wxy) {
    return this.field_to_cell_precise(this.widget_to_field(wxy));
};

// returns [in_bounds, new_selection_loc]
RegionMap.RegionMap.prototype.detect_hit = function(uv, offset) {
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        var cell = null;
        if(this.region) {
            cell = this.widget_to_cell_precise([uv[0]-(this.xy[0]+offset[0]), uv[1]-(this.xy[1]+offset[1])]);
        }
        return [true, cell];
    }
    return [false, null];
};

// can pass null loc to deselect
RegionMap.RegionMap.prototype.select_feature_at = function(loc) {
    this.selection_loc = loc;
    this.selection_feature = null;

    if(this.selection_loc) {
        this.follow_travel = false;

        var ls = this.region.find_features_at_coords(this.selection_loc, {include_moving_squads:true});

        if(ls.length < 1) {
            // select empty ground?
            if(!this.region.obstructs_squads(this.selection_loc)) {
                this.selection_feature = {'base_type': 'empty', 'base_map_loc': loc, 'base_climate': this.region.read_climate(this.selection_loc)['name']};
            }
        } else if(ls.length == 1) {
            this.selection_feature = ls[0];
        } else if(ls.length > 1) {
            // select first non-squad
            for(var i = 0; i < ls.length; i++) {
                if(ls[i]['base_type'] != 'squad') {
                    this.selection_feature = ls[i];
                    break;
                }
            }
            // feature might still be null if there are just multiple squads here

            // if there are only squads remaining, filter out moving ones
            if(!this.selection_feature) {
                ls = goog.array.filter(ls, function(f) { return !this.region.feature_is_moving(f, this.time); }, this);
            }
        }

        if(this.selection_feature) {
            if(!this.popup || this.popup.user_data['feature'] != this.selection_feature) {
                this.set_popup(this.make_feature_popup(this.selection_feature, this.selection_loc));
            }
            if(this.popup) {
                this.make_feature_popup_menu();
                // play button-click sound
                GameArt.play_canned_sound(gamedata['dialogs']['region_map_popup_menu']['widgets']['button']['bg_image']);
            }
        } else if(ls.length > 1) {
            // multi-selector
            this.set_popup(this.make_multi_select_popup(ls, this.selection_loc, true));
            return;
        }
    }

    if(!this.selection_feature) {
        this.set_popup(null);
    }
};

RegionMap.RegionMap.prototype.on_mousedown = function(uv, offset, button) {
    if(!this.show) { return false; }
    return this.detect_hit(uv, offset)[0];
};

RegionMap.RegionMap.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.show) {
        return false;
    }

    if(button.get_button(SPUI.MouseButton.RIGHT)) {
        this.set_popup(null);
        return true;
    }

    if(this.drag_full) {
        this.drag_start = null;
        this.drag_full = false;
        return true;
    }

    var hit = this.detect_hit(uv, offset);

    if(this.cursor && this.cursor.on_mouseup(hit[1], button)) { return true; }

    this.select_feature_at(hit[1]);

    return hit[0];
};

RegionMap.RegionMap.prototype.on_mousemove = function(uv, offset) {
    var hit = this.detect_hit(uv, offset);

    if(this.cursor && this.cursor.on_mousemove(hit[1])) { return true; }

    this.hovercell = hit[1];
    this.hover_alliance = -1;

    var hovertext;

    if(this.hovercell) {
        var ls = this.region.find_features_at_coords(this.hovercell, {include_moving_squads:true});
        var feature = null;
        if(ls.length === 1) {
            feature = ls[0];
        } else if(ls.length > 1) {
            // select first non-squad
            for(var i = 0; i < ls.length; i++) {
                if(ls[i]['base_type'] != 'squad') {
                    feature = ls[i];
                    break;
                }
            }
            // feature might still be null if there are just multiple squads here

            // if there are only squads remaining, filter out moving ones
            if(!feature) {
                ls = goog.array.filter(ls, function(f) { return !this.region.feature_is_moving(f, this.time); }, this);
            }
        }

        if(feature && feature['base_landlord_id'] && !is_ai_user_id_range(feature['base_landlord_id'])) {
            var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
            if(info && ('alliance_id' in info) && info['alliance_id'] >= 0) {
                this.hover_alliance = info['alliance_id'];
            }
        }

        if(this.popup) {
            if(((this.popup.user_data['feature'] === null) || (this.popup.user_data['feature'] != feature)) &&
               !this.popup.user_data['sticky']) {
                this.set_popup(null);
            }
        }
        if(!this.popup && !this.cursor) {
            if(feature) {
                this.set_popup(this.make_feature_popup(feature, this.hovercell));
            } else if(ls.length > 1) {
                this.set_popup(this.make_multi_select_popup(ls, this.hovercell, false));
            }
        }
        hovertext = this.hovercell[0].toString()+','+this.hovercell[1].toString();
    } else {
        hovertext = '-,-';
    }

    if(mouse_state.button.get_button(SPUI.MouseButton.LEFT) || mouse_state.spacebar) {
        if(!this.drag_start) {
            if(hit[0] && (!this.cursor || this.cursor.allow_drag())) {
                this.drag_start = [this.xy[0]+uv[0]+offset[0], this.xy[1]+uv[1]+offset[1]];
                this.follow_travel = false;
                this.pan_goal = null;
            }
            return hit[0];
        } else {
            var wxy = [this.xy[0]+uv[0]+offset[0],
                       this.xy[1]+uv[1]+offset[1]];
            var DEADZONE = 5;
            if(this.drag_full ||
               Math.abs(wxy[0]-this.drag_start[0]) >= DEADZONE ||
               Math.abs(wxy[1]-this.drag_start[1]) >= DEADZONE) {

                this.drag_full = true;
                this.set_popup(null);
                this.pan = [this.pan[0] - (wxy[0]-this.drag_start[0])/(this.zoom),
                            this.pan[1] - (wxy[1]-this.drag_start[1])/(this.zoom)];
                this.drag_start = wxy;

                player.record_feature_use('region_map_scrolled');
            }
            return true;
        }
    } else {
        this.drag_start = null;
        this.drag_full = false;
        if(mouse_state.button.get_button(SPUI.MouseButton.RIGHT)) {
            return true; // handle here, so the event won't go to the desktop
        }
    }
    return this.drag_full;
};

RegionMap.RegionMap.prototype.on_mousewheel = function(uv, offset, delta) {
    var hit = this.detect_hit(uv, offset);
    if(!hit[0]) { return false; }

    if(delta != 0) {
        this.set_zoom_linear(this.zoom_linear + 0.03*delta);
        this.on_mousemove(uv, offset); // to update hovercell
    }
    return true;
}

// return value is fed into "buttons" down below
RegionMap.RegionMap.prototype.make_nosql_spy_buttons = function(feature) {
    var ret = [];

    if(feature['base_type'] === 'squad' && !player.squad_combat_enabled()) { return ret; }
    if(feature['base_type'] === 'home' && !player.map_home_combat_enabled()) { return ret; }

    var info = PlayerCache.query_sync(feature['base_landlord_id']);
    var same_alliance = info && info['alliance_id'] && session.is_in_alliance() && info['alliance_id'] == session.alliance_id && gamedata['prevent_same_alliance_attacks'];
    var can_pre_attack = player.get_any_abtest_value('squad_pre_attack', gamedata['client']['squad_pre_attack']) && feature['base_type'] == 'squad' && feature['base_landlord_id'] != session.user_id && !same_alliance && (info || is_ai_user_id_range(feature['base_landlord_id']));
    var squads_nearby = this.region.squads_nearby(feature['base_map_loc']);

    var will_lose_protection = player.resource_state['protection_end_time'] > server_time &&
        !is_ai_user_id_range(feature['base_landlord_id']) &&
        (feature['base_type'] != 'squad' || gamedata['territory']['squads_affect_protection']) &&
        (feature['base_type'] != 'quarry'|| gamedata['territory']['quarries_affect_protection']);

    // looking at an enemy home base that we can attack
    var can_attack_home = (feature['base_type'] === 'home' && feature['base_landlord_id'] != session.user_id && !same_alliance &&
                           info &&
                           (!this.region.pvp_level_gap_enabled() || player.in_attackable_level_range(info['player_level']||0) ||
                            player.cooldown_active('revenge_defender:'+feature['base_landlord_id'].toString())));

    // looking at an enemy home base that we can raid-guard
    var can_guard_home = (feature['base_type'] === 'home' && feature['base_landlord_id'] != session.user_id && same_alliance &&
                          player.alliance_raids_enabled());

    // SPY button
    if(feature['base_type'] !== 'raid') {

        var verb = gamedata['strings']['regional_map'][(feature['base_landlord_id'] == session.user_id ? (feature['base_type'] == 'quarry' ? 'instant_visit_quarry' : 'instant_visit_base') : 'spy')];

        if(('base_map_path' in feature) && feature['base_map_path'] && (feature['base_map_path'][feature['base_map_path'].length-1]['eta'] > this.time)) {
            ret.push([verb, (function(_mapwidget, _feature) { return function() {
                _mapwidget.set_popup(null);
                var msg = gamedata['errors']['CANNOT_SPY_ON_MOVING_SQUAD'];
                invoke_squad_error(msg['ui_title'], msg['ui_name']);
            }; })(this, feature), 'disabled_clickable', gamedata['errors']['CANNOT_SPY_ON_MOVING_SQUAD']['ui_name'], SPUI.error_text_color]);
        } else if(squads_nearby.length < 1 && hex_distance(player.home_base_loc, feature['base_map_loc']) !== 1) {
            ret.push([verb, (function(_mapwidget, _feature) { return function() {
                _mapwidget.set_popup(null);
                var msg = gamedata['errors']['CANNOT_SPY_NO_NEARBY_SQUADS'];
                invoke_squad_error(msg['ui_title'], msg['ui_name']);
            }; })(this, feature), 'disabled_clickable',
                      SPUI.break_lines(gamedata['errors']['CANNOT_SPY_NO_NEARBY_SQUADS']['ui_name'], SPUI.desktop_font, [300,0])[0],
                      SPUI.error_text_color]);
        } else {
            // SPY (and if can_pre_attack is true, then ATTACK as well)
            var make_cb = function(_mapwidget, _feature, _pre_attack) { return function() {
                _mapwidget.set_popup(null);
                do_visit_base(-1, {base_id:_feature['base_id'], pre_attack:_pre_attack, short_loading_timeout:true});
            }; };
            var spy_cb = make_cb(this, feature, 0);
            ret.push([verb, spy_cb]);

            if(can_pre_attack) {
                // do not show pre_attack option if player has no units deployable into this climate
                var climate = new Climate(gamedata['climates'][(feature['base_climate'] && feature['base_climate'] in gamedata['climates'] ? feature['base_climate'] : gamedata['default_climate'])]);
                var found_unit = false;
                for(var id in player.my_army) {
                    var o = player.my_army[id];
                    if(goog.array.contains(squads_nearby, o['squad_id'])) {
                        if(army_unit_hp(o)[0] > 0 && climate.can_deploy_unit_of_spec(gamedata['units'][o['spec']])) {
                            found_unit = true; break;
                        }
                    }
                }
                if(found_unit) {
                    // pre-attack button
                    var attack_cb = make_cb(this, feature, 1); // pass pre_attack = 1 for auto-attack
                    var wrapped_attack_cb = (will_lose_protection ? (function(_attack_cb) { return function() { invoke_attack_through_protection_message(_attack_cb); }; })(attack_cb) : attack_cb);
                    ret.push([gamedata['strings']['regional_map']['attack'], wrapped_attack_cb, 'attack']);

                    // pre-attack-and-resolve button
                    if(gamedata['territory']['enable_pre_resolve'] && player.auto_resolve_enabled()) {
                        var resolve_cb = make_cb(this, feature, 2); // pass pre_attack = 2 for auto-attack-and-resolve
                        var wrapped_resolve_cb = (will_lose_protection ? (function(_resolve_cb) { return function() { invoke_attack_through_protection_message(_resolve_cb); }; })(resolve_cb) : resolve_cb);
                        ret.push([gamedata['strings']['regional_map']['auto_resolve'], wrapped_resolve_cb, 'attack']);
                    }
                }
            }
        }
    } // END is not raid site

    // CALL SQUAD
    if((feature['base_type'] === 'home' && player.map_home_combat_enabled()) ||
       (feature['base_type'] === 'squad' && player.squad_combat_enabled()) ||
       goog.array.contains(['empty','hive','quarry'], feature['base_type'])) {
        ret.push([gamedata['strings']['regional_map']['call'],
                  (function(_mapwidget, _feature) { return function() {
                      _mapwidget.set_popup(null);
                      SquadControlDialog.invoke_call(_feature['base_map_loc'], _feature);
                  }; })(this, feature), 'passive']);
    }

    // LAUNCH RAID
    if(player.raids_enabled() &&
       (feature['base_type'] === 'raid' ||
        (feature['base_type'] === 'home' && (can_attack_home || can_guard_home)))) {
        var raid_cb = (function(_mapwidget, _feature) { return function() {
            _mapwidget.set_popup(null);
            SquadControlDialog.invoke_raid(_feature['base_map_loc'], _feature);
        }; })(this, feature);
        var wrapped_raid_cb = (can_attack_home && will_lose_protection ? (function(_raid_cb) { return function() { invoke_attack_through_protection_message(_raid_cb); }; })(raid_cb) : raid_cb);

        if(feature['base_type'] === 'home' && can_guard_home) {
            ret.push([gamedata['strings']['regional_map']['guard'], wrapped_raid_cb, 'normal']);
        } else if(feature['base_type'] === 'home' && can_attack_home && player.raid_pvp_attempts_left() < 1) {
            ret.push([gamedata['strings']['regional_map']['call_raid'], null, 'disabled', gamedata['strings']['regional_map']['next_raid_in'].replace('%s', pretty_print_time(player.raid_pvp_attempt_next_in())), SPUI.error_text_color]);
        } else if(feature['base_type'] === 'home' && can_attack_home && ('protection_end_time' in feature) && (feature['protection_end_time'] === 1 || feature['protection_end_time'] >= this.time)) {
            ret.push([gamedata['strings']['regional_map']['call_raid'], null, 'disabled', gamedata['strings']['regional_map']['under_protection'], SPUI.error_text_color]);
        } else {
            ret.push([gamedata['strings']['regional_map']['call_raid'], wrapped_raid_cb, 'normal']);
        }
    }
    return ret;
};

RegionMap.RegionMap.prototype.make_bookmark_button = function(feature) {
    var already_bookmarked = !!player.map_bookmark_find(this.region.data['id'], feature['base_map_loc']) ;
    return [gamedata['strings']['regional_map'][already_bookmarked ? 'already_bookmarked' : 'add_bookmark'],
            (!already_bookmarked ? (function (_this, _feature) { return function() {
                var bm_name;
                if(_feature['base_type'] == 'quarry') {
                    bm_name = gamedata['strings']['regional_map']['quarry'].replace('%s',_feature['base_ui_name']);
                } else if(_feature['base_landlord_id'] && PlayerCache.query_sync(_feature['base_landlord_id'])) {
                    bm_name = _this.pcache_to_name(PlayerCache.query_sync(_feature['base_landlord_id']), 0, true);
                } else if(_feature['base_ui_name']) {
                    bm_name = _feature['base_ui_name'];
                } else {
                    bm_name = gamedata['strings']['regional_map']['unknown_base'];
                }
                player.map_bookmark_create(_this.region.data['id'], bm_name, _feature['base_map_loc']);
                _this.set_popup(null);
            }; })(this, feature) : null),
            already_bookmarked ? 'disabled_passive' : 'passive'];
};

// context menu:

RegionMap.RegionMap.update_feature_popup_menu = function(dialog) {
    var mapwidget = dialog.user_data['mapwidget'];
    var infowidget = dialog.user_data['info_dialog'];
    var feature = dialog.user_data['feature'];
    var owned = (feature['base_landlord_id'] === session.user_id);
    var lock_state = feature['LOCK_STATE'] || 0;
    var lock_owner = feature['LOCK_OWNER'] || -1;

    var buttons = [];

    if(lock_state != 0 && (lock_owner != session.user_id) &&
       !(player.raids_enabled() && lock_state == 1 && feature['base_type'] == 'home')) {
        // locked, can't do anything

        //buttons.push([gamedata['strings']['regional_map']['under_attack'], function() {}, 'disabled']);
        if(feature['base_type'] !== 'squad') {
            buttons.push(mapwidget.make_bookmark_button(feature));
        }

    } else if(owned) {

        // OWN SQUAD
        if(feature['base_type'] == 'squad') {
            var squad_sid = feature['base_id'].split('_')[1]
            var squad_id = parseInt(squad_sid,10);
            var squad_data = player.squads[squad_sid];
            if(squad_data && player.squad_is_deployed(squad_id)) {
                // HALT button
                if(player.squad_is_moving(squad_id) && !feature['raid']) {
                    buttons.push([gamedata['strings']['regional_map']['halt'], (function(_mapwidget, _feature, _squad_data) { return function() {
                        _mapwidget.set_popup(null);
                        player.squad_halt(_squad_data['id']);
                    }; })(mapwidget, feature, squad_data), ((squad_data['pending'] || player.squad_get_client_data(squad_data['id'], 'halt_pending')) ? 'disabled' : 'normal')]);
                }
                // SPEED UP (movement) button
                if(player.squad_is_moving(squad_id) && player.squad_speedups_enabled()) {
                    buttons.push([gamedata['spells']['SQUAD_MOVEMENT_SPEEDUP_FOR_MONEY']['ui_name'], (function(_mapwidget, _squad_id) { return function() {
                        _mapwidget.set_popup(null);
                        RegionMap.invoke_squad_speedup_dialog(_squad_id);
                    }; })(mapwidget, squad_id), 'normal']);
                }
                if(player.squad_is_moving(squad_id) && player.squad_speedup_items_enabled()) {
                    var spell = gamedata['spells']['SQUAD_MOVEMENT_SPEEDUP_FOR_ITEM'];
                    var has_it = player.has_item(spell['currency'].split(':')[1]);
                    buttons.push([spell['ui_name'], (function(_mapwidget, _squad_id) { return function() {
                        _mapwidget.set_popup(null);
                        RegionMap.invoke_squad_speedup_item_dialog(_squad_id);
                    }; })(mapwidget, squad_id),
                                  (has_it ? 'normal' : 'disabled'),
                                  (has_it ? spell['ui_description'] : spell['ui_insufficient']),
                                  (has_it ? SPUI.default_text_color : SPUI.error_text_color)]);
                }

                // VISIT button
                if(!player.squad_is_moving(squad_id) && player.squad_combat_enabled() && !feature['raid']) {
                    var togo = player.cooldown_togo('squad_order:'+squad_data['id'].toString());
                    if(togo > 0) {
                        buttons.push([gamedata['strings']['regional_map']['instant_visit_own_squad'],
                                      null, 'disabled',
                                      gamedata['errors']['CANNOT_SPY_SQUAD_ON_COOLDOWN']['ui_name_cooldown'].replace('%togo', pretty_print_time(togo)),
                                      SPUI.error_text_color]);
                    } else {
                        buttons.push([gamedata['strings']['regional_map']['instant_visit_own_squad'],
                                      (function(_feature) { return function() {
                                          do_visit_base(-1, {base_id:_feature['base_id']});
                                      }; })(feature)]);
                    }
                }

                // MOVE button
                if(!player.squad_is_moving(squad_id) && !feature['raid']) {
                    buttons.push([gamedata['strings']['regional_map']['move'], (function(_mapwidget, _feature, _squad_data) { return function() {
                        _mapwidget.set_popup(null);
                        _mapwidget.cursor = new RegionMap.MoveCursor(_mapwidget, _squad_data['map_loc'], _squad_data['id'], _feature['base_icon']);
                    }; })(mapwidget, feature, squad_data),
                                  ((squad_data['pending'] || player.squad_get_client_data(squad_data['id'], 'move_pending') || player.cooldown_active('squad_order:'+squad_data['id'].toString())) ? 'disabled' : 'normal'),
                                  (player.cooldown_active('squad_order:'+squad_data['id'].toString()) ? gamedata['errors']['CANNOT_MOVE_SQUAD_ON_COOLDOWN']['ui_name_cooldown'].replace('%togo', pretty_print_time(player.cooldown_togo('squad_order:'+squad_data['id'].toString()))) : null),
                                  SPUI.error_text_color
                                 ]);
                }

                // RECALL button
                if(!player.squad_is_moving(squad_id) ||
                   (feature['raid'] && !vec_equals(feature['base_map_loc'], player.home_base_loc))) {
                    buttons.push([gamedata['strings']['regional_map']['recall'], (function(_mapwidget, _feature, _squad_data) { return function() {
                        _mapwidget.set_popup(null);
                        player.squad_recall(_squad_data['id']);
                    }; })(mapwidget, feature, squad_data), ((squad_data['pending'] || player.squad_get_client_data(squad_data['id'], 'move_pending')) ? 'disabled' : 'passive')]);
                }
            }

        // OWN NOT-SQUAD (BASE OR QUARRY)
        } else {

            // BASE WE'RE LOOKING AT NOW
            if(session.viewing_base.base_id === feature['base_id']) {

                buttons.push([gamedata['strings']['regional_map']['instant_visit_'+(feature['base_type'] == 'quarry' ? 'quarry' : 'base')],
                              (function(_feature) { return function() {
                                  if(_feature['base_id'] == player.home_base_id) {
                                      // special case to prevent hangs
                                      if(session.viewing_base.base_id === feature['base_id']) {
                                          change_selection_ui(null); // here already
                                      } else {
                                          visit_base(session.user_id);
                                      }
                                  } else {
                                      do_visit_base(-1, {base_id:_feature['base_id']});
                                  }
                              }; })(feature)]);

                if(mapwidget.region.data['storage'] == 'nosql') {
                    // DEPLOY
                    if(feature['base_id'] == player.home_base_id) {
                        buttons.push([gamedata['strings']['regional_map']['deploy'],
                                      (function(_mapwidget, _feature) { return function() {
                                          _mapwidget.set_popup(null);
                                          SquadControlDialog.invoke_deploy(_feature['base_map_loc']);
                                      }; })(mapwidget, feature), 'passive']);
                    }
                }

            } else {
                buttons.push([gamedata['strings']['regional_map']['instant_visit_'+(feature['base_type'] == 'quarry' ? 'quarry' : 'base')], (function(_feature) { return function() {
                    if(_feature['base_id'] == player.home_base_id) {
                        // special case to prevent hangs
                        visit_base(session.user_id);
                    } else {
                        do_visit_base(-1, {base_id:_feature['base_id']});
                    }
                }; })(feature)]);

                // do we have a squad stationed here?
                var guard_squad_data = null, guard_squad_icon = null, guard_squad_icon_space = -1;
                goog.object.forEach(player.squads, function(squad) {
                    if(('map_loc' in squad) && vec_equals(squad['map_loc'], feature['base_map_loc'])) {
                        guard_squad_data = squad;
                        goog.object.forEach(player.my_army, function(obj) {
                            if(obj['squad_id'] == guard_squad_data['id']) {
                                if(army_unit_space(obj) > guard_squad_icon_space) {
                                    guard_squad_icon_space = army_unit_space(obj);
                                    guard_squad_icon = get_leveled_quantity(gamedata['units'][obj['spec']]['art_asset'], 1);
                                }
                            }
                        });
                    }
                });
                if(guard_squad_data) {
                    buttons.push([gamedata['strings']['regional_map']['withdraw'], (function(_mapwidget, _feature, _guard_squad_data, _guard_squad_icon) { return function() {
                        _mapwidget.set_popup(null);
                        _mapwidget.cursor = new RegionMap.DeployCursor(_mapwidget, _guard_squad_data['map_loc'], _guard_squad_data['id'],
                                                                       _guard_squad_icon);
                    }; })(mapwidget, feature, guard_squad_data, guard_squad_icon), (guard_squad_data['pending'] ? 'disabled' : 'passive')]);
                } else {
                    if(mapwidget.region.data['storage'] == 'nosql') {
                        // CALL SQUAD
                        buttons.push([gamedata['strings']['regional_map']['call'],
                                      (function(_mapwidget, _feature) { return function() {
                                          _mapwidget.set_popup(null);
                                          SquadControlDialog.invoke_call(_feature['base_map_loc'], _feature);
                                      }; })(mapwidget, feature), 'passive']);
                    }
                }
            }

            if(feature['base_type'] === 'quarry') {
                buttons.push(mapwidget.make_bookmark_button(feature));
            }

        }

    } else if(feature['base_type'] == 'home') {

        // OTHER HUMAN HOME BASE - NOSQL
        if(mapwidget.region.data['storage'] == 'nosql') {
            // SPY/CALL
            buttons = buttons.concat(mapwidget.make_nosql_spy_buttons(feature));
            buttons.push(mapwidget.make_bookmark_button(feature));
        } else {
            // OTHER HUMAN HOME BASE - LEGACY
            if(gamedata['enable_muffin_on_map']) {
                buttons.push([gamedata['strings']['regional_map']['spy'], (function(_feature) { return function() {
                    visit_base(_feature['base_landlord_id']);
                }; })(feature)]);
            }
        }

        buttons.push([gamedata['strings']['regional_map']['get_info'],
                      (function (_mapwidget, _feature) { return function() {
                          _mapwidget.set_popup(null);
                          PlayerInfoDialog.invoke(_feature['base_landlord_id']);
                      }; })(mapwidget, feature), 'passive']);

    } else if(feature['base_type'] == 'squad') {
        // OTHER PLAYER'S SQUAD
        // SPY/CALL
        buttons = buttons.concat(mapwidget.make_nosql_spy_buttons(feature));

        // GET INFO
        buttons.push([gamedata['strings']['regional_map']['get_info'],
                      (function (_mapwidget, _feature) { return function() {
                          _mapwidget.set_popup(null);
                          PlayerInfoDialog.invoke(_feature['base_landlord_id']);
                      }; })(mapwidget, feature), 'passive']);

    } else if(!player.is_cheater && goog.array.contains(['hive','raid','quarry'], feature['base_type']) && ('base_template' in feature) && (feature['base_template'] in gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates']) &&
              ('activation' in gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]) &&
              !read_predicate(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['activation']).is_satisfied(player,null)) {
        var rpred = read_predicate(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['activation']);
        var pred_text = rpred.ui_describe(player);
        buttons.push([gamedata['strings']['regional_map']['locked'], get_requirements_help(rpred), 'disabled_clickable',
                      gamedata['strings']['regional_map']['to_unlock'].replace('%s',pred_text), SPUI.error_text_color]);
        buttons.push(mapwidget.make_bookmark_button(feature));
    } else {
        if(mapwidget.region.data['storage'] == 'nosql' || player.travel_satisfied(feature['base_map_loc'])) {
            if(mapwidget.region.data['storage'] == 'nosql') {
                if(feature['base_type'] === 'empty') {
                    // CALL SQUAD
                    buttons.push([gamedata['strings']['regional_map']['call'],
                                  (function(_mapwidget, _feature) { return function() {
                                      _mapwidget.set_popup(null);
                                      SquadControlDialog.invoke_call(_feature['base_map_loc'], _feature);
                                  }; })(mapwidget, feature), 'passive']);
                } else {
                    // SPY/CALL
                    buttons = buttons.concat(mapwidget.make_nosql_spy_buttons(feature));
                }

            } else {
                buttons.push([gamedata['strings']['regional_map']['spy'],  (function(_mapwidget, _feature) { return function() {
                    _mapwidget.set_popup(null);
                    do_visit_base(-1, {base_id:_feature['base_id']});
                }; })(mapwidget, feature)]);
            }

            if(feature['base_type'] !== 'empty') {
                buttons.push(mapwidget.make_bookmark_button(feature));
            }

        } else if(player.travel_state['dest_loc'] && vec_equals(player.travel_state['dest_loc'], feature['base_map_loc'])) {
            buttons.push([gamedata['strings']['regional_map']['cancel_travel'], (function (_mapwidget) { return function() {
                send_to_server.func(["TRAVEL_BEGIN", null, 0]);
                _mapwidget.set_popup(null);
            }; })(mapwidget)]);
        } else {
            buttons.push([gamedata['strings']['regional_map']['go_here'].replace('%s',pretty_print_time(player.travel_time_to(feature['base_map_loc']))),
                          (function(_mapwidget, _feature) { return function(w) {
                              send_to_server.func(["TRAVEL_BEGIN", _feature['base_map_loc'], player.travel_time_to(_feature['base_map_loc'])]);
                              _mapwidget.follow_travel = true;
                              _mapwidget.set_popup(null);
                          }; })(mapwidget, feature), 'passive']);
        }
    }

    if(feature['base_type'] == 'quarry' && feature['base_template'] in gamedata['quarries_client']['templates'] &&
       gamedata['quarries_client']['templates'][feature['base_template']]['info_tip'] &&
       'map_feature_'+gamedata['quarries_client']['templates'][feature['base_template']]['info_tip'] in gamedata['strings']) {
        // GET INFO
        buttons.push([gamedata['strings']['regional_map']['get_info'],
                      (function (_mapwidget, _feature) { return function() {
                          var tip_name = 'map_feature_'+gamedata['quarries_client']['templates'][_feature['base_template']]['info_tip'];
                          var tip = gamedata['strings'][tip_name];
                          _mapwidget.set_popup(null);
                          invoke_child_message_dialog(tip['ui_title'], tip['ui_description'], {'dialog':'message_dialog_big'});
                      }; })(mapwidget, feature), 'passive']);
    }

    // fill in buttons
    dialog.widgets['bgrect'].show = (buttons.length > 0);

    var MAXBUT = dialog.data['widgets']['button']['array'][1];
    if(buttons.length > MAXBUT) {
        mapwidget.set_popup(null);
        throw Error('unhandled # of buttons '+buttons.length.toString());
    }

    var i;
    for(i = 0; i < buttons.length; i++) {
        dialog.widgets['button'+i].show = true;
        dialog.widgets['button'+i].str = buttons[i][0];
        dialog.widgets['button'+i].onclick = buttons[i][1];
        dialog.widgets['button'+i].state = (buttons[i].length > 2 ? buttons[i][2] : 'normal');
        dialog.widgets['button'+i].tooltip.str = (buttons[i].length > 3 ? buttons[i][3] : null);
        dialog.widgets['button'+i].tooltip.text_color = (buttons[i].length > 4 ? buttons[i][4] : SPUI.default_text_color);
    }
    while(i < MAXBUT) {
        dialog.widgets['button'+i].show = false; i += 1;
    }

    dialog.wh = dialog.widgets['bgrect'].wh = [dialog.data['widgets']['bgrect']['dimensions'][0],
                                               4 + 36 * buttons.length];

    var anim_progress = Math.min((client_time - dialog.user_data['anim_start']) / 0.2, 1);

    dialog.xy = [Math.floor(infowidget.wh[0]/2 - dialog.wh[0]/2),
                 Math.floor(infowidget.wh[1] - dialog.widgets['bgrect'].wh[1]*(1-anim_progress))];
    dialog.clip_to = [-9999, infowidget.wh[1], 29999, 29999];
};

RegionMap.RegionMap.prototype.make_feature_popup_menu = function() {
    if(!this.popup) { return; }
    if(this.popup.user_data['menu']) { return; }

    var feature = this.popup.user_data['feature'];

    if(!goog.array.contains(['quarry','home','hive','raid','squad','empty'], feature['base_type'])) { return; } // decorative base

    var dialog = new SPUI.Dialog(gamedata['dialogs']['region_map_popup_menu']);
    this.popup.user_data['menu'] = dialog; // reference from dialog to menu
    dialog.user_data['info_dialog'] = this.popup; // reference to popup info dialog
    dialog.user_data['anim_start'] = client_time;
    dialog.user_data['mapwidget'] = this;
    dialog.user_data['feature'] = feature;

    dialog.ondraw = RegionMap.RegionMap.update_feature_popup_menu;

    this.popup.user_data['sticky'] = true;
    this.popup.add_under(dialog);
};

// XXX hack until we fix tooltips showing underneath modal dialogs
RegionMap.RegionMap.prototype.has_modal_child_dialog = function() {
    return this.parent.children[this.parent.children.length-1].user_data &&
        this.parent.children[this.parent.children.length-1].user_data['dialog'] &&
        !goog.array.contains(['region_map_scroll_help','region_map_popup','region_map_multi_select'],
                             this.parent.children[this.parent.children.length-1].user_data['dialog']);
};

RegionMap.RegionMap.prototype.make_feature_popup = function(feature, click_map_loc) {

    if(this.has_modal_child_dialog()) {
        // covered by a modal dialog
        return null;
    }

    var ui = new SPUI.Dialog(gamedata['dialogs']['region_map_popup']);
    ui.transparent_to_mouse = true;
    ui.clip_children = false;
    ui.user_data['dialog'] = 'region_map_popup';
    ui.user_data['mapwidget'] = this;
    ui.user_data['feature'] = feature;
    ui.user_data['sticky'] = false;
    ui.user_data['menu'] = null;
    ui.user_data['open_time'] = client_time; // for blinking effect
    ui.user_data['selectable'] = false; // for multi-selector only

    // store original click location here (to handle moving squads) - position is updated in update_feature_popup
    ui.user_data['original_map_loc'] = click_map_loc;
    ui.user_data['xy_offset'] = [0,0];

    ui.ondraw = RegionMap.RegionMap.update_feature_popup;
    ui.ondraw(ui); // call to set initial xy position in case this is immediately followed by make_feature_popup_menu()
    return ui;
};

RegionMap.RegionMap.update_feature_popup = function(dialog) {
    var ui = dialog;
    var feature = dialog.user_data['feature'];
    var mapwidget = dialog.user_data['mapwidget'];
    var base_wxy = mapwidget.cell_to_widget(dialog.user_data['original_map_loc']);
    var ftype = feature['base_type'];
    var owned = (feature['base_landlord_id'] === session.user_id);

    if(!mapwidget.region.feature_shown(feature)) { // the feature got moved off the map
        mapwidget.set_popup(null);
        return;
    }

    // when panning in from well off-screen, wait until the base is in view before showing popup
    var BUFFER = vec_scale(0.5, dialog.wh);
    if(base_wxy[0] < -BUFFER[0] || base_wxy[0] >= mapwidget.wh[0]+BUFFER[0] ||
       base_wxy[1] < -BUFFER[1] || base_wxy[1] >= mapwidget.wh[1]+BUFFER[1]) {
        dialog.show = false;
        return;
    } else {
        dialog.show = true;
    }

    dialog.xy = vec_add(dialog.user_data['xy_offset'],
                        [Math.floor(mapwidget.xy[0] + base_wxy[0] + mapwidget.zoom*(gamedata['territory']['cell_size'][0]/2) - dialog.wh[0]/2),
                         Math.floor(mapwidget.xy[1] + base_wxy[1] + mapwidget.zoom*(gamedata['territory']['cell_size'][1] - 4))]);

    // selectability
    dialog.widgets['bgrect_selected'].show = (dialog.user_data['selectable']);
    var is_active = (dialog.user_data['selectable'] && dialog.mouse_enter_time > 0);
    dialog.widgets['bgrect_selected'].alpha = dialog.data['widgets']['bgrect_selected'][is_active ? 'alpha_active' : 'alpha'];

    dialog.widgets['name'].onclick = function(w) {
        var _dialog = w.parent;
        var _this = _dialog.user_data['mapwidget'];
        if(_dialog.parent && _dialog.parent.user_data && _dialog.parent.user_data['dialog'] === 'region_map_multi_select' &&
           _dialog.user_data['selectable'] && _dialog.mouse_enter_time > 0) {
            // perform the selection
            _this.set_popup(_this.make_feature_popup(_dialog.user_data['feature'], _dialog.user_data['feature']['base_map_loc']));
            if(_this.popup) {
                _this.make_feature_popup_menu();
            }
        }
    };

    // name/portrait
    ui.widgets['portrait'].show = ui.widgets['climate_tile'].show = false;

    if('base_landlord_id' in feature) {
        ui.widgets['portrait'].show = true;
        ui.widgets['portrait'].set_user(feature['base_landlord_id']);
        if(is_ai_user_id_range(feature['base_landlord_id'])) {
            var base_info = gamedata['ai_bases_client']['bases'][feature['base_landlord_id'].toString()];
            ui.widgets['name'].str = (base_info ? base_info['ui_name'] : gamedata['strings']['regional_map']['unknown_base']);
        } else {
            var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
            if(!info) {
                ui.widgets['name'].str = ui.data['widgets']['name']['ui_name_pending'];
                ui.widgets['portrait_pending'].show = true;
            } else {
                ui.widgets['portrait_pending'].show = false;
                // don't show player level on quarries
                ui.widgets['name'].str = mapwidget.pcache_to_name(info, 0, (feature['base_type'] !== 'quarry'));
                ui.widgets['portrait'].onclick = (function (_info) { return function(w) {
                    PlayerInfoDialog.invoke(_info['user_id']);
                }; })(info);
            }
        }
    } else if(feature['base_type'] === 'empty') {
        if(feature['base_climate'] && feature['base_climate'] in gamedata['climates']) {
            var climate_data = gamedata['climates'][feature['base_climate']];
            var tile_data = gamedata['territory']['tiles'][mapwidget.region.read_terrain(feature['base_map_loc'])];
            ui.widgets['name'].str = gamedata['strings']['regional_map']['empty_hex'].replace('%s', climate_data['ui_name']);
            ui.widgets['climate_tile'].show = true;
            ui.widgets['climate_tile'].state = tile_data['sprite'];
        } else {
            ui.widgets['name'].str = gamedata['strings']['regional_map']['unknown_base'];
        }
    } else {
        ui.widgets['name'].str = gamedata['strings']['regional_map']['unknown_base'];
    }

    // quarry/hive status widgets
    ui.widgets['qstat'].show = ui.widgets['qicon'].show = ui.widgets['qsize'].show = (ftype == 'quarry');
    ui.widgets['hloot_label'].show =  ui.widgets['hloot'].show = false;

    if(ftype == 'quarry') {
        ui.widgets['qicon'].bg_image = 'resource_icon_'+feature['base_icon'];

        var TIMELEFT = [[1, 'low'], [3600, 'medium'], [43200, 'full']];
        var fullness_state;
        if(mapwidget.region.data['quarry_show_depleting']) {
            fullness_state = 'low';
        } else {
            if(feature['base_expire_time'] < 0) {
                fullness_state = 'full';
            } else {
                fullness_state = 'empty';
                for(var r = 0; r < TIMELEFT.length; r++) {
                    if((feature['base_expire_time'] - mapwidget.time) >= TIMELEFT[r][0]) {
                        fullness_state = TIMELEFT[r][1];
                    } else { break; }
                }
            }
        }

        var rich_str = quarry_richness_ui_str(feature['base_richness']);

        ui.widgets['qstat'].state = fullness_state;

        var qtip;
        if(1) {
            var data = ui.data['widgets']['qstat'];
            var ui_res = '';
            if(feature['base_icon'] in gamedata['resources']) {
                ui_res = gamedata['resources'][feature['base_icon']]['ui_name'];
            } else if(feature['base_icon'] in gamedata['strings']['regional_map']) {
                ui_res = goog.string.trim(gamedata['strings']['regional_map'][feature['base_icon']].replace('%s',''));
            }
            var ui_long_rich_str = (rich_str in data['ui_tooltip_sizes'] ? data['ui_tooltip_sizes'][rich_str] : rich_str);
            qtip = data['ui_tooltip_'+fullness_state].replace('%SIZE', ui_long_rich_str).replace('%RESOURCE', ui_res);
        }

        ui.widgets['qsize'].str = rich_str;

        ui.widgets['name'].tooltip.str = qtip;
        /*
            ui.widgets['description'].tooltip.str =
            ui.widgets['qstat'].tooltip.str =
            ui.widgets['qicon'].tooltip.str =
            ui.widgets['qsize'].tooltip.str = qtip;
            */

        ui.widgets['qstat'].onclick =
            ui.widgets['qicon'].onclick =
            ui.widgets['qsize'].onclick = function() { invoke_ingame_tip('map_quarries_tip', {frequency:GameTipFrequency.ALWAYS}); };

    } else if(ftype == 'hive') {
        var s = '';
        if(('base_template' in feature) && (feature['base_template'] in gamedata['hives_client']['templates'])) {
            var template = gamedata['hives_client']['templates'][feature['base_template']];
            if('ui_loot_rarity' in template && template['ui_loot_rarity'] >= 0) {
                s = ui.data['widgets']['hloot']['ui_name_rarity'][template['ui_loot_rarity']];
                ui.widgets['hloot_label'].show = ui.widgets['hloot'].show = true;

                var col = gamedata['client']['loot_rarity_colors'][template['ui_loot_rarity']+1];
                ui.widgets['hloot'].text_color = new SPUI.Color(col[0], col[1], col[2], 1);
            }
        }
        ui.widgets['hloot'].str = s;
    }

    // description text
    var descr;
    if(ftype == 'quarry') {
        var template = (('base_template' in feature) ? (gamedata['quarries_client']['templates'][feature['base_template']] || null) : null);
        if(template && template['turf_points']) {
            descr = gamedata['strings']['regional_map']['strongpoint'].replace('%s',feature['base_ui_name']).replace('%TURF_POINTS', pretty_print_number(template['turf_points']));
        } else {
            descr = gamedata['strings']['regional_map']['quarry'].replace('%s',feature['base_ui_name']);
        }
    } else if(goog.array.contains(['hive','raid'], ftype)) {
        var template = (('base_template' in feature) ? (gamedata[ftype+'s_client']['templates'][feature['base_template']] || null) : null);
        if(template) {
            // default
            descr = gamedata['strings']['regional_map'][ftype+'_descr'].replace('%s',feature['base_ui_name']);
            var ls = [];
            if(template['ui_tokens2']) {
                var spec = ItemDisplay.get_inventory_item_spec(template['ui_tokens2']['spec']);
                if(template['ui_tokens2']['stack'] >= 500) {
                    var thousands = template['ui_tokens2']['stack']/1000.0;
                    ls.push(thousands.toFixed(1)+'k '+ItemDisplay.get_inventory_item_ui_name(spec));
                } else {
                    ls.push(pretty_print_number(template['ui_tokens2']['stack'])+'x '+ItemDisplay.get_inventory_item_ui_name(spec));
                }
            }
            if(template['kill_points']) {
                var points = template['kill_points'];
                if('hive_kill_point_scale' in mapwidget.region.data) {
                    points = Math.max(1, Math.floor(points * mapwidget.region.data['hive_kill_point_scale']));
                }
                if(points > 0) {
                    ls.push(gamedata['strings']['regional_map']['with_kill_points'].replace('%d', pretty_print_number(points)));
                }
            }
            if(ls.length > 0) {
                descr = descr + ' ('+ls.join(', ')+')';
            }
        }
    } else if(ftype == 'base') {
        descr = gamedata['strings']['regional_map']['mystery'];
    } else if(ftype == 'squad') {
        var squad_sid = feature['base_id'].split('_')[1];
        if(owned && squad_sid in player.squads) {
            descr = gamedata['strings']['squads']['squad']+' '+player.squads[squad_sid]['ui_name'];
        } else {
            descr = gamedata['strings']['squads']['squad']; // +' #'+squad_sid;
        }
    } else if('base_ui_name' in feature) {
        descr = feature['base_ui_name'];
    } else if(ftype == 'empty') {
        descr = null;
    } else {
        descr = gamedata['strings']['regional_map']['unknown_name'];
    }
    ui.widgets['description'].set_text_with_linebreaking_and_shrink_font_to_fit(descr);
    // only clip description if quarry stat widgets are showing
    ui.widgets['description'].clip_to = ui.data['widgets']['description'][ui.widgets['qstat'].show ?  'clip_to_qstat' : 'clip_to'];

    // set squad health/space widgets
    if(feature['base_type'] == 'squad' && feature['base_landlord_id'] == session.user_id) {
        var squad_id = parseInt(feature['base_id'].split('_')[1],10);
        var stats = player.get_squad_hp_and_space(squad_id);
        dialog.widgets['squad_space_bar'].show = dialog.widgets['squad_hp_bar'].show = true;
        dialog.widgets['squad_space_bar'].progress = stats['cur_space'] / Math.max(stats['max_space'],1);
        dialog.widgets['squad_hp_bar'].progress = (stats['max_hp'] > 0 ? (stats['cur_hp']/stats['max_hp']) : 0);
    } else {
        dialog.widgets['squad_space_bar'].show = dialog.widgets['squad_hp_bar'].show = false;
    }

    var lock_state = feature['LOCK_STATE'] || 0;
    var lock_owner = feature['LOCK_OWNER'] || -1;

    if(lock_owner == session.user_id) {
        lock_state = 0;
    }

    // attackability status
    // can show one solid line, or blink through several lines
    var blink_list = [];
    var out_of_level_range = false;

    // out-of-level-range should always be shown if applicable
    if(feature['base_type'] == 'home' && !is_ai_user_id_range(feature['base_landlord_id'])) {
        var info = ('base_landlord_id' in feature ? PlayerCache.query_sync_fetch(feature['base_landlord_id']) : null);
        if(info && !player.in_attackable_level_range(info['player_level']||0) &&
           !player.cooldown_active('revenge_defender:'+feature['base_landlord_id'].toString()) &&
           mapwidget.region.pvp_level_gap_enabled()) {
            blink_list.push({'status':((info['player_level']||0) > player.level() ? 'level_too_high' : 'level_too_low')});
            out_of_level_range = true;
        }
    }

    if(lock_state != 0) {
        if(lock_state == 2) {
            // actually under attack
            if(!player.raids_enabled() && (!feature['base_type'] || feature['base_type'] == 'home')) {
                // for non-raidable home bases, never show them as under attack, only the mysterious "protection or home"
                blink_list.push({'status':'home_or_protection'});
            } else {
                blink_list.push({'status':'under_attack'});
            }
        } else if(lock_state == 1) { // actually at home
            if(player.raids_enabled()) {
                blink_list.push({'status':'home'});
            } else {
                blink_list.push({'status':'home_or_protection'});
            }
        }

    } else if(feature['base_type'] == 'squad' && feature['base_landlord_id'] != session.user_id && mapwidget.region.feature_is_moving(feature, mapwidget.time)) {
        blink_list.push({'status':'moving'});

    } else if(mapwidget.region.data['show_precise_quarry_expiration'] && feature['base_type'] == 'quarry' &&
              ('base_expire_time' in feature) && feature['base_expire_time'] > 0) {
        var togo = feature['base_expire_time'] - mapwidget.time;
        var stat, str;
        if(mapwidget.region.data['show_precise_quarry_expiration'] == 1 || togo < mapwidget.region.data['show_precise_quarry_expiration']) {
            if(togo < 7200) { // less than 1 hour (but really 0-2h because map maintenance script runs hourly)
                stat = 'depletes_soon_';
            } else if(togo < 86400) { // less than 1 day - show hour count only, not minutes
                stat = 'depletes_in_';
                str = pretty_print_time_very_brief(Math.max(togo, 7200));
            } else {
                stat = 'depletes_in_';
                str = pretty_print_time_brief(togo);
            }
        } else {
            // say "good for 6d+" rather than giving the exact time
            stat = 'lasts_for_';
            str = pretty_print_time_brief(mapwidget.region.data['show_precise_quarry_expiration']);
        }
        blink_list.push({'status': stat + (feature['base_landlord_id'] == session.user_id ? 'friendly' : 'hostile'), 'str':str});

    } else if(feature['base_landlord_id'] == session.user_id) {
        if(feature['base_last_conquer_time'] && feature['base_last_conquer_time'] > 0) {
            blink_list.push({'status':'owned_since', 'str':pretty_print_time_brief(mapwidget.time - feature['base_last_conquer_time'])});
        } else {
            blink_list.push({'status':'owned'});
        }
    } else if(('protection_end_time' in feature) && (feature['protection_end_time'] == 1 || feature['protection_end_time'] > mapwidget.time)) {
        blink_list.push({'status':(player.raids_enabled() ? 'protection' : 'home_or_protection')});
    } else if(!player.is_cheater && goog.array.contains(['hive','raid','quarry'], feature['base_type']) && ('base_template' in feature) && (feature['base_template'] in gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates']) &&
              ('activation' in gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]) &&
              !read_predicate(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['activation']).is_satisfied(player,null)) {
        blink_list.push({'status':'locked'});
    } else if(goog.array.contains(['hive','raid'], feature['base_type']) && ('base_expire_time' in feature) && (feature['base_expire_time'] > 0) &&
              (feature['base_expire_time'] - mapwidget.time) < gamedata['territory']['escaping_soon_time']) {
        blink_list.push({'status':'escaping_soon'});
    } else if(goog.array.contains(['hive','raid'], feature['base_type']) && ('base_template' in feature) && (feature['base_template'] in gamedata[{'hive':'hives_client','raid':'raids_client'}[feature['base_type']]]['templates']) && ('ui_difficulty_comment' in gamedata[{'hive':'hives_client','raid':'raids_client'}[feature['base_type']]]['templates'][feature['base_template']])) {
        var comment = eval_cond_or_literal(gamedata[{'hive':'hives_client','raid':'raids_client'}[feature['base_type']]]['templates'][feature['base_template']]['ui_difficulty_comment'], player, null);
        if(comment) {
            blink_list.push({'status':'open_with_difficulty_comment', 'str':comment});
        }
    } else if(feature['base_last_conquer_time'] && feature['base_last_conquer_time'] > 0) {
        blink_list.push({'status':'open_since', 'str':pretty_print_time_brief(mapwidget.time - feature['base_last_conquer_time'])});
    } else if(feature['base_type'] == 'home' && !is_ai_user_id_range(feature['base_landlord_id'])) {
        var info = ('base_landlord_id' in feature ? PlayerCache.query_sync_fetch(feature['base_landlord_id']) : null);
        if(!out_of_level_range) {
            // figure out if any ladder points can be won
            // (should match can_ladder_battle_on_map() in server)
            var win_points = mapwidget.winnable_ladder_points(feature);
            if(win_points > 0) {
                blink_list.push({'status':'open_with_trophies', 'str': win_points.toString()});
            } else {
                blink_list.push({'status':'open'});
            }
        }
    } else {
        blink_list.push({'status':'open'});
    }

    // when bases are shows as home/protection/unattackable, blink last defense time
    if(feature['base_type'] == 'home' && !is_ai_user_id_range(feature['base_landlord_id'])) {
        if(goog.array.contains(['home', 'home_or_protection', 'protection', 'level_too_low', 'level_too_high'], blink_list[0]['status'])) {
            var info = ('base_landlord_id' in feature ? PlayerCache.query_sync_fetch(feature['base_landlord_id']) : null);
            if(info && ('last_defense_time' in info) && (info['last_defense_time'] > 0)) {
                blink_list.unshift({'status': 'home_last_defended', 'str': pretty_print_time_brief(mapwidget.time - info['last_defense_time'])});
            }
        }
    }

    var index;
    if(blink_list.length < 2) {
        index = 0;
    } else {
        var period = gamedata['territory']['last_defended_blink_period'];
        index = Math.floor(((client_time - dialog.user_data['open_time'])/period) % blink_list.length);
    }
    dialog.widgets['attackability'].text_color = SPUI.make_colorv(dialog.data['widgets']['attackability']['text_color_'+blink_list[index]['status']]);

    var final_str = dialog.data['widgets']['attackability']['ui_name_'+blink_list[index]['status']].replace('%s', blink_list[index]['str']||'');
    dialog.widgets['attackability'].set_text_with_linebreaking_and_shrink_font_to_fit(final_str);
};

/** @param {!Object<string,?>} feature
    @return {number} */
RegionMap.RegionMap.prototype.winnable_ladder_points = function(feature) { return this.winnable_ladder_points_detailed(feature)[0]; };

/** @param {!Object<string,?>} feature
    @return {!Array} [amount, reason code] */
RegionMap.RegionMap.prototype.winnable_ladder_points_detailed = function(feature) {
    if(!this.region.data['ladder_on_map_if'] || !read_predicate(this.region.data['ladder_on_map_if']).is_satisfied(player, null)) { return [0, 'ladder_on_map_if false']; }
    if(is_ai_user_id_range(feature['base_landlord_id'] || 0)) { return [0, 'feature base_landlord_id is AI']; }
    if(feature['base_landlord_id'] == session.user_id) { return [0, 'feature is owned by us']; }
    if(feature['base_type'] != 'home') { return [0, 'feature is not a home base']; }
    if(('LOCK_STATE' in feature) && feature['LOCK_STATE'] != 0 && !(player.raids_enabled() && feature['LOCK_STATE'] == 1)) { return [0, 'feature is locked']; }
    if(('protection_end_time' in feature) && (feature['protection_end_time'] == 1 || feature['protection_end_time'] > this.time)) { return [0, 'feature is protected']; }
    var info = ('base_landlord_id' in feature ? PlayerCache.query_sync_fetch(feature['base_landlord_id']) : null);
    if(!info) { return [0, 'no PlayerCache for base_landlord_id']; }
    var player_info = PlayerCache.query_sync_fetch(session.user_id); // for own trophy count
    if(!player_info) { return [0, 'no PlayerCache for self']; }
    if(!player.in_attackable_level_range(info['player_level']||0) &&
       !player.cooldown_active('revenge_defender:'+feature['base_landlord_id'].toString()) &&
       this.region.pvp_level_gap_enabled()) { return [0, 'level range restriction']; }
    if(player.cooldown_active('ladder_fatigue:'+feature['base_landlord_id'].toString())) { return [0, 'ladder_fatigue cooldown']; }
    var win_points = 0;
//  if!(('trophies_pvp' in info)) { return [0, 'no self trophy count']; } ???
    if(!('base_damage' in info) || info['base_damage'] >= gamedata['matchmaking']['ladder_win_damage']) { return [0, 'no base_damage, or damaged above ladder win threshold']; }
    if(('base_repair_time' in info) && info['base_repair_time'] >= this.time) { return [0, 'player under repair']; }
    if(session.is_in_alliance() && ('alliance_id' in info) && info['alliance_id'] == session.alliance_id) { return [0, 'same alliance now']; }
    if(('alliance_id' in info) && player.cooldown_active('alliance_sticky:'+info['alliance_id'].toString())) { return [0, 'same alliance sticky']; }

    var attacker_count = player_info['trophies_pvp'] || 0;
    var defender_count = info['trophies_pvp'] || 0;
    var tbl = gamedata['matchmaking']['ladder_point_on_map_table'];
    var delta = defender_count - attacker_count;
    win_points = Math.min(Math.max(Math.floor(tbl['attacker_victory']['base'] + delta * tbl['attacker_victory']['delta']), tbl['attacker_victory']['min']), tbl['attacker_victory']['max']);
    var scale_points = this.region.data['ladder_point_scale'] || 1;
    win_points = Math.max(Math.floor(scale_points * win_points), 1);

    return [win_points, null];
};

/** @param {!Array.<!Object>} feature_list - list of map features
    @param {!Array.<number>} click_map_loc - hex that was clicked to produce this popup
    @param {boolean} sticky - whether this should persist after mouse moves away from the hex */
RegionMap.RegionMap.prototype.make_multi_select_popup = function(feature_list, click_map_loc, sticky) {

    if(this.has_modal_child_dialog()) {
        // covered by a modal dialog
        return null;
    }

    var ui = new SPUI.Dialog(gamedata['dialogs']['region_map_multi_select']);
    ui.transparent_to_mouse = true;
    ui.clip_children = false;
    ui.user_data['dialog'] = 'region_map_multi_select';
    ui.user_data['mapwidget'] = this;
    ui.user_data['feature'] = null; // in case other code checks for this
    ui.user_data['feature_list'] = feature_list;
    ui.user_data['sticky'] = sticky;

    var feature_i = 0;
    for(var y = 0; y < ui.data['widgets']['feature']['array'][1]; y++) {
        for(var x = 0; x < ui.data['widgets']['feature']['array'][0]; x++) {
            var wname = SPUI.get_array_widget_name('feature', ui.data['widgets']['feature']['array'], [x,y]);
            var w = ui.widgets[wname];

            if(feature_i < feature_list.length) {
                w.show = true;
                w.transparent_to_mouse = true;
                w.clip_children = false;
                w.user_data['mapwidget'] = this;
                w.user_data['feature'] = feature_list[feature_i];
                w.user_data['sticky'] = sticky;
                w.user_data['menu'] = null;
                w.user_data['open_time'] = client_time; // for blinking effect
                w.user_data['selectable'] = sticky;

                // store original click location here (to handle moving squads) - position is updated in update_feature_popup
                w.user_data['original_map_loc'] = click_map_loc;
                w.user_data['xy_offset'] = vec_mul([x,y], ui.data['widgets']['feature']['array_offset']);
                w.ondraw = RegionMap.RegionMap.update_feature_popup;
                w.ondraw(w); // call to set initial xy position in case this is immediately followed by make_feature_popup_menu()
            } else {
                w.show = false;
            }
            feature_i += 1;
        }
    }

    return ui;
};

RegionMap.RegionMap.prototype.draw_movement_path = function(path) {
    var offset = vec_scale(0.5, gamedata['territory']['cell_size']);
    var xy;
    ctx.beginPath();
    xy = vec_add(path[0], offset);
    ctx.moveTo(xy[0], xy[1]);
    for(var i = 1; i < path.length; i++) {
        xy = vec_add(path[i], offset);
        ctx.lineTo(xy[0], xy[1]);
    }
    ctx.stroke();

    // draw little circle at end of path
    xy = vec_add(path[path.length-1], offset);
    ctx.save();
    ctx.beginPath();
    ctx.transform(1, 0, 0, 0.5, xy[0], xy[1]);
    ctx.arc(0, 0, 6, 0, 2*Math.PI, false);
    ctx.stroke();
    ctx.restore();
};

RegionMap.RegionMap.prototype.make_hex_outline_path = function(xy) {
    var ins = gamedata['territory']['cell_hexinset'];
    var vtx = [[gamedata['territory']['cell_size'][0]/2, 0],
               [gamedata['territory']['cell_size'][0], ins],
               [gamedata['territory']['cell_size'][0], gamedata['territory']['cell_size'][1]-ins],
               [gamedata['territory']['cell_size'][0]/2, gamedata['territory']['cell_size'][1]],
               [0, gamedata['territory']['cell_size'][1]-ins],
               [0, ins],
               [gamedata['territory']['cell_size'][0]/2, 0]];

    SPUI.ctx.beginPath();
    SPUI.ctx.moveTo(xy[0]+vtx[0][0], xy[1]+vtx[0][1]);
    for(var i = 1; i < vtx.length; i++) {
        SPUI.ctx.lineTo(xy[0]+vtx[i][0], xy[1]+vtx[i][1]);
    }
};

RegionMap.RegionMap.prototype.draw_reticle = function(xy, size) {
    xy = [xy[0] + gamedata['territory']['cell_size'][0]/2,
          xy[1] + gamedata['territory']['cell_size'][1]/2];
    SPUI.ctx.beginPath();
    SPUI.ctx.lineWidth = 2;
    SPUI.ctx.beginPath();
    // old, needs draw_quantize()
    SPUI.ctx.arc(Math.floor(xy[0]), Math.floor(xy[1]), size, 0, 2*Math.PI, false);
    SPUI.ctx.moveTo(Math.floor(xy[0]-size), Math.floor(xy[1]));
    SPUI.ctx.lineTo(Math.floor(xy[0]-1.8*size), Math.floor(xy[1]));
    SPUI.ctx.moveTo(Math.floor(xy[0]+size), Math.floor(xy[1]));
    SPUI.ctx.lineTo(Math.floor(xy[0]+1.8*size), Math.floor(xy[1]));
    SPUI.ctx.moveTo(Math.floor(xy[0]), Math.floor(xy[1]-size));
    SPUI.ctx.lineTo(Math.floor(xy[0]), Math.floor(xy[1]-1.8*size));
    SPUI.ctx.moveTo(Math.floor(xy[0]), Math.floor(xy[1]+size));
    SPUI.ctx.lineTo(Math.floor(xy[0]), Math.floor(xy[1]+1.8*size));
    SPUI.ctx.stroke();
};

RegionMap.RegionMap.prototype.draw_travel = function() {
    if(this.region.data['storage'] == 'nosql') { return; }

    var home_feature = this.region.find_home_feature();
    if(!home_feature) { return; }

    var dest_loc = player.travel_state['dest_loc'] || home_feature['base_map_loc'];
    var feature = this.region.find_feature_at_coords(dest_loc);
    if(!feature || feature === home_feature) { return; }
    var home_pos = home_feature['base_map_loc'];
    var dest_pos = feature['base_map_loc'];

    var progress;
    if(this.time > player.travel_state['end_time']) {
        progress = 1;
    } else {
        progress = (this.time - player.travel_state['start_time'])/(player.travel_state['end_time']-player.travel_state['start_time']);
    }
    var flash = false; // (progress < 1);

    var home_xy = this.cell_to_field(home_pos);
    var dest_xy = this.cell_to_field(dest_pos);

    var cur_xy = [home_xy[0] + progress*(dest_xy[0]-home_xy[0]),
                  home_xy[1] + progress*(dest_xy[1]-home_xy[1])];

    SPUI.ctx.lineWidth = 2;

    if(!flash || (client_time % 0.66 >= 0.33)) {
        SPUI.ctx.strokeStyle = (progress < 1 ? 'rgba(255,255,255,0.33)' : 'rgba(255,255,255,0.8)');
        SPUI.ctx.beginPath();
        SPUI.ctx.moveTo(home_xy[0]+gamedata['territory']['cell_size'][0]/2, home_xy[1]+gamedata['territory']['cell_size'][1]/2);
        SPUI.ctx.lineTo(cur_xy[0]+gamedata['territory']['cell_size'][0]/2, cur_xy[1]+gamedata['territory']['cell_size'][1]/2);
        SPUI.ctx.stroke();
    }

    SPUI.ctx.lineWidth = 3;
    SPUI.ctx.strokeStyle = (progress < 1 ? 'rgba(255,255,255,0.8)' : 'rgba(255,255,255,1.0)');
    //this.draw_reticle(cur_xy, (progress < 1 ? 10 : 15));
    this.make_hex_outline_path(cur_xy);
    SPUI.ctx.stroke();

    if(progress < 1) {
        var txt = gamedata['strings']['regional_map']['arriving_in'].replace('%s', pretty_print_time_brief(player.travel_state['end_time'] - this.time));
        var dims = SPUI.ctx.measureText(txt);
        var txy = [cur_xy[0]+gamedata['territory']['cell_size'][0]/2+10,
                   cur_xy[1]+gamedata['territory']['cell_size'][1]/2+42];
        SPUI.ctx.fillStyle = 'rgba(0,0,0,0.75)';
        SPUI.ctx.fillRect(txy[0]-4, txy[1]-1-this.font.size, dims.width+8, this.font.size+8);
        SPUI.ctx.fillStyle = 'rgba(200,200,200,1.0)';
        SPUI.ctx.fillText(txt, txy[0], txy[1]);
    }
};

RegionMap.RegionMap.prototype.draw_hovercell = function() {
    if(!this.hovercell) { return; }
    this.make_hex_outline_path(this.cell_to_field(this.hovercell));
    SPUI.ctx.strokeStyle = 'rgba(255,255,255,0.33)';
    SPUI.ctx.lineWidth = 2;
    SPUI.ctx.stroke();
};

RegionMap.RegionMap.prototype.draw_feature_strength = function(feature, wxy) {
    // query stats
    var unit_strength_by_manuf_category = null;
    if(feature['base_landlord_id'] === session.user_id && feature['base_type'] === 'squad') {
        // horrible temporary deep query
        unit_strength_by_manuf_category = {};
        var squad_id = parseInt(feature['base_id'].split('_')[1], 10);
        goog.object.forEach(player.my_army, function(obj, obj_id) {
            if(obj['squad_id'] === squad_id) {
                var spec = gamedata['units'][obj['spec']];
                var catname = spec['manufacture_category'];
                var cur_max = army_unit_hp(obj);
                var space = army_unit_space(obj);
                var contribution = space * (cur_max[0]/cur_max[1]); // scale contribution by unit health
                unit_strength_by_manuf_category[catname] = (unit_strength_by_manuf_category[catname]||0) + contribution;
            }
        });
    }
    if(!unit_strength_by_manuf_category) { return; }
    var n_categories = goog.object.getCount(gamedata['strings']['manufacture_categories']);
    // max contribution = full squad of largest possible space
    var provides_squad_space = gamedata['buildings'][gamedata['squad_building']]['provides_squad_space'];
    var max_contribution = provides_squad_space[provides_squad_space.length-1];
    var total_width = 40;
    var spacing = 2;
    var bar_width = Math.floor(total_width/n_categories) - spacing;
    var max_height = 60;
    var i = 0;
    goog.object.forEach(gamedata['strings']['manufacture_categories'], function(catdata, catname) {
        var height = (unit_strength_by_manuf_category[catname]||0)/max_contribution * max_height;
        if(height > 0) {
            var xy = [wxy[0] + i * (bar_width+spacing), wxy[1] - height];
            var wh = [bar_width, height];
            if(true /* SPFX.detail >= 2*/) { // drop shadow
                SPUI.ctx.fillStyle = 'rgba(0,0,0,1)';
                SPUI.ctx.fillRect(xy[0]+1/this.zoom, xy[1]+1/this.zoom, wh[0], wh[1]);
            }
            SPUI.ctx.fillStyle = SPUI.make_colorv(catdata['ui_color']).str();
            SPUI.ctx.fillRect(xy[0], xy[1], wh[0], wh[1]);
        }
        i += 1;
    }, this);
};

RegionMap.RegionMap.prototype.draw_feature_label = function(wxy, str, color_str, size) {
    var has_state = false;
    if(size != 1) {
        SPUI.ctx.save(); has_state = true;
        SPUI.ctx.font = SPUI.make_font(Math.floor(this.font.size*size), Math.floor(this.font.leading*size), 'thick').str();
    }

    // adds drop shadow
    if(true /* SPFX.detail >= 2 */) {
        SPUI.ctx.fillStyle = 'rgba(0,0,0,1)';
        this.do_draw_feature_label([wxy[0]+1/this.zoom,wxy[1]+1/this.zoom], str, size);
    }

    SPUI.ctx.fillStyle = (SPUI.low_fonts && color_str != gamedata['territory']['label_colors']['owned'] ? 'rgba(255,255,255,1)' : color_str);
    var ret = this.do_draw_feature_label(wxy, str, size);

    if(has_state) {
        SPUI.ctx.restore();
    }
    return ret;
};

RegionMap.RegionMap.prototype.do_draw_feature_label = function(wxy, lines, size) {
    var height = 0;
    for(var i = 0; i < lines.length; i++) {
        if(lines[i].length > 0) {
            var dims = SPUI.ctx.measureText(lines[i]);
            var offset = [-dims.width/2, 1.5*i*size*this.font.leading];
            var pos = vec_add(wxy, offset);
            SPUI.ctx.fillText(lines[i], pos[0], pos[1]);
            height = Math.max(height, offset[1]);
        }
    }
    return height;
};

RegionMap.RegionMap.prototype.draw_feature_influence = function(roi, feature, influence_alpha) {
    if(!this.region.feature_shown(feature)) { return; }
    var loc = feature['base_map_loc'];
    var base_xy = this.cell_to_field(loc);
    // convert from pixels to cells
    var MAX_RADIUS = vec_div([gamedata['territory']['influence_max_radius'],gamedata['territory']['influence_max_radius']],gamedata['territory']['cell_size']);

    if(loc[0]+MAX_RADIUS[0] >= roi[0][0] && loc[0]-MAX_RADIUS[0] <= roi[1][0] && loc[1]+MAX_RADIUS[1] >= roi[0][1] && loc[1]-MAX_RADIUS[1] <= roi[1][1]) {
        // classify_feature is expensive, so only do it if potentially in ROI
        var color = this.classify_feature(feature);

        // override classification for strongpoints
        if(feature['base_type'] == 'quarry' && feature['base_template'] in gamedata['quarries_client']['templates'] &&
           gamedata['quarries_client']['templates'][feature['base_template']]['turf_points']) {
            if(feature['base_landlord_id'] == session.user_id) {
                color = 'turf_control_friendly';
            } else if(feature['base_landlord_id']) {
                if(is_ai_user_id_range(feature['base_landlord_id'])) {
                    color = 'turf_control_hostile';
                } else if(session.is_in_alliance()) {
                    var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
                    if(info && ('alliance_id' in info)) {
                        if(info['alliance_id'] == session.alliance_id) {
                            color = 'turf_control_friendly';
                        } else {
                            color = 'turf_control_hostile';
                        }
                    }
                }
            }
        }

        // override normal influence with hover
        if(this.hover_alliance >= 0 && color != 'owned' && color != 'your_home' && color != 'your_squad') {
            if(feature['base_landlord_id'] && !is_ai_user_id_range(feature['base_landlord_id'])) {
                var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
                if(info && ('alliance_id' in info)) {
                    if(info['alliance_id'] == this.hover_alliance) {
                        if(this.hover_alliance == session.alliance_id) {
                            color = 'hover_alliance_friendly';
                        } else {
                            color = 'hover_alliance_hostile';
                        }
                        if(feature['base_type'] == 'squad') { color += '_squad'; }
                    }
                }
            }
        }

        var params = gamedata['territory']['influence'][color];
        if(!params) { return; }

        var radius = params['radius'];
        var alpha = params['alpha'];
        var color_str = params['color'];

        alpha *= influence_alpha;
        alpha = Math.max(alpha, params['min_alpha'] || 0);

        if(alpha > 0) {
            var grad = SPUI.ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
            grad.addColorStop(0.0, color_str+alpha.toString()+')');
            grad.addColorStop(1.0, color_str+'0.0)');
            SPUI.ctx.save();
            SPUI.ctx.fillStyle = grad;
            SPUI.ctx.transform(1, 0, 0, 1,
                               base_xy[0] + gamedata['territory']['cell_size'][0]/2,
                               base_xy[1] + gamedata['territory']['cell_size'][1]/2);
            SPUI.ctx.fillRect(-radius, -radius, 2*radius, 2*radius);
            SPUI.ctx.restore();
        }
    }
};

RegionMap.RegionMap.prototype.sort_features_for_draw = function(roi, feature_list) {
    var draw_list = [];
    var sort_keys = {};
    goog.array.forEach(feature_list, function(feature) {
        // do not draw expired bases
        if(!this.region.feature_shown(feature) ||
           !feature['base_map_loc']) { return; }
        var loc = feature['base_map_loc'];
        var owned = (feature['base_landlord_id'] === session.user_id);

        // also check current location against roi (for moving objects), and never cull own squads (because the movement trail line might cross the window)
        var loc2 = (this.region.feature_is_moving(feature, this.time) ? this.region.feature_interpolate_pos(feature, this.time)[1] : null);

        if((loc[0] >= roi[0][0] && loc[0] <= roi[1][0] && loc[1] >= roi[0][1] && loc[1] <= roi[1][1]) ||
           (loc2 && (loc2[0] >= roi[0][0] && loc2[0] <= roi[1][0] && loc2[1] >= roi[0][1] && loc2[1] <= roi[1][1])) ||
           (owned && feature['base_type'] == 'squad')) {
            // feature is visible, and should be drawn
            draw_list.push(feature);
            // sort squads on top of non-squads, then by depth (Y) order
            sort_keys[feature['base_id']] = (feature['base_type'] == 'squad' ? 99999 : 0) + loc[1];
        }
    }, this);
    draw_list.sort(function(a,b) {
        var ka = sort_keys[a['base_id']], kb = sort_keys[b['base_id']];
        return (ka>kb ? 1 : (ka<kb ? -1 : 0));
    });
    return draw_list;
};

// convert PlayerCache entry to the most specific name we can
/** @param {Object} info
    @param {number} abbreviate (0 = full name, 1 = strip title, 2 = strip title and level) */
RegionMap.RegionMap.prototype.pcache_to_name = function(info, abbreviate, show_level) {
    var name = PlayerCache._get_ui_name(info) || gamedata['strings']['regional_map']['unknown_name'];
    if(abbreviate >= 1) {
        name = PlayerCache.strip_title_prefix(name);
    }
    if(show_level && abbreviate < 2 && ('player_level' in info)) {
        name += ' L'+info['player_level'].toString();
    }
    return name;
};

RegionMap.RegionMap.prototype.draw_feature = function(feature) {
    var loc = feature['base_map_loc'];
    var cover = gamedata['territory']['cell_overlap'];
    var owned = (feature['base_landlord_id'] === session.user_id);

    if(1) {
        var base_xy = this.cell_to_field(loc);
        var moving = this.region.feature_is_moving(feature, this.time);
        var moving_xy = null; // only valid if moving is true
        var selected = (this.selection_feature === feature); // (this.selection_loc && this.selection_loc[0] === loc[0] && this.selection_loc[1] === loc[1]);

        if(gamedata['territory']['clip_features']) { // clip for speed
            if(selected || moving) {
                // don't clip if selected or if a moving feature
                // (could clip moving features if we also check the interpolated location)
            } else {
                var widget = this.field_to_widget(base_xy);
                var size = vec_scale(this.zoom, gamedata['territory']['cell_size']);
                // for safety, add padding equal to the the cell size on all sides
                var pad = vec_scale(this.zoom, gamedata['territory']['cell_size']);
                if(widget[0]-pad[0] >= this.wh[0] || widget[0]+size[0]+pad[0] < 0 ||
                   widget[1]-pad[1] >= this.wh[1] || widget[1]+size[1]+pad[1] < 0) {
                    // clipped
                    return;
                }
            }
        }

        var label_xy = base_xy;
        var show_label = true, is_guard = false;
        var multi_index = 0; // if multiple squads overlap in a hex, this is our index
        var multi_count = 1; // count of features in this hex, including us

        var squad_sid = null, squad_id = -1;
        var squad_pending = false; // own squad has pending orders
        var classification = this.classify_feature(feature);

        if(feature['base_type'] == 'squad') {
            squad_sid = feature['base_id'].split('_')[1];
            squad_id = parseInt(squad_sid,10);

            // is this squad guarding a quarry? does it overlap with another squad?
            if(!moving) {
                var ls = this.region.find_features_at_coords(loc);
                var squad_count = 0;
                for(var i = 0; i < ls.length; i++) {
                    var f = ls[i];
                    if(f['base_type'] == 'quarry') {
                        is_guard = true;
                    } else if(f['base_type'] == 'squad') {
                        if(f['base_id'] === feature['base_id']) {
                            multi_index = squad_count;
                        } else {
                            multi_count += 1;
                            squad_count += 1;
                        }
                    }
                }
            }

            //if(feature['base_landlord_id'] != session.user_id) { show_label = false; } // no labels for enemy squads
            if(owned) {
                var squad_data = player.squads[squad_sid];
                if((squad_data && squad_data['pending']) ||
                   player.squad_get_client_data(squad_id, 'move_pending') ||
                   player.squad_get_client_data(squad_id, 'halt_pending') ||
                   (!moving && player.cooldown_active('squad_order:'+squad_sid))
                  ) {
                    squad_pending = true;
                }
            }
        }

        if(this.zoom > 0.05 && !is_guard && (feature['base_type'] != 'squad' || selected)) {
            // draw hex base
            SPUI.ctx.fillStyle = (owned ? (moving ? 'rgba(0,255,0,0.25)' : (selected ? 'rgba(64,255,64,0.66)' : 'rgba(0,255,0,0.25)')) :
                                  (selected ? 'rgba(255,64,64,0.66)' : 'rgba(255,0,0,0.25)'));
            this.make_hex_outline_path(base_xy);
            SPUI.ctx.fill();
        }

        if(this.zoom > 0.1) {
            // draw base icon
            if(feature['base_type'] == 'squad' && ('base_icon' in feature)) {
                var icon_scale = 0.75, icon_offset = [0.5,0.5];
                var assetname = get_leveled_quantity(gamedata['units'][feature['base_icon']]['art_asset'], 1);

                if(is_guard) {
                    show_label = false;
                    icon_scale = 0.66;
                    icon_offset = [0.33,0.66]; // move off to the side
                } else if(multi_count > 1) {
                    icon_scale = 0.66;

                    // cycle through labels
                    var cycle = Math.floor(client_time % multi_count);
                    if(multi_index !== cycle) {
                        show_label = false;
                    }

                    icon_offset = vec_add(vec_add([0.25, (multi_count >= 5 ? 0.25 : 0.5)],
                                                  vec_scale(multi_index % 4, [0.6/4,0])),
                                                  vec_scale(Math.floor(multi_index/4), [0,0.6/4]));
                }

                SPUI.ctx.save();

                // draw SOLID moving shape

                if(moving) {
                    SPUI.ctx.save();

                    // but raid squads as transparent
                    if(feature['base_type'] === 'squad' && feature['raid']) { SPUI.ctx.globalAlpha = 0.66; }

                    var last_next_progress = this.region.feature_interpolate_pos(feature, this.time);
                    // note: cell_to_field is nonlinear, so we have to do the interpolation after converting to field coordinates
                    var last_xy = this.cell_to_field(last_next_progress[0]);
                    var next_xy = this.cell_to_field(last_next_progress[1]);
                    var delta = vec_sub(next_xy, last_xy);
                    moving_xy = vec_add(last_xy, vec_scale(last_next_progress[2], delta));

                    if(owned) {
                        // draw movement path
                        SPUI.ctx.strokeStyle = gamedata['client']['unit_control_colors']['move_later'];
                        SPUI.ctx.lineWidth = 2;
                        var drawn_path = [];
                        for(var i = 0; i < feature['base_map_path'].length; i++) {
                            if(i >= feature['base_map_path'].length-1 || feature['base_map_path'][i+1]['eta'] >= this.time) {
                                if(feature['base_map_path'][i]['eta'] < this.time) {
                                    drawn_path.push(moving_xy); // current segment
                                } else {
                                    drawn_path.push(this.cell_to_field(feature['base_map_path'][i]['xy']));
                                }
                            }
                        }
                        this.draw_movement_path(drawn_path);
                    }

                    var facing = (Math.atan2(delta[1],delta[0]) + (1.75*Math.PI)) % 360;
                    var moving_origin = vec_add(moving_xy, vec_mul(icon_offset,gamedata['territory']['cell_size']));
                    SPUI.ctx.transform(icon_scale, 0, 0, icon_scale, moving_origin[0], moving_origin[1]);
                    if(1) {
                        // draw sprite, with walk cycle if necessary
                        var state = 'normal';
                        var sprite_data = gamedata['art'][assetname];
                        if('walk_cycle' in sprite_data) {
                            var walk_period = 1.2; // average for a ground unit
                            var cycprog = ((client_time/walk_period)+squad_id) % 1.0;
                            var cycfrm = Math.floor(sprite_data['walk_cycle'].length*cycprog);
                            state = sprite_data['walk_cycle'][cycfrm];
                        }
                        GameArt.assets[assetname].states[state].draw([0,0], facing, client_time);
                    }
                    SPUI.ctx.restore();

                    // show your own pending moves/halts as loading spinners
                    if(squad_pending) {
                        var offset = [0.5,0.4];
                        GameArt.assets['loading_spinner'].states['normal'].draw(vec_add(moving_xy, vec_mul(offset,gamedata['territory']['cell_size'])), 0, client_time);
                    }

                    // draw label at moving location
                    label_xy = moving_xy;
                }

                // draw (faint, if moving) destination shape
                if(moving) { SPUI.ctx.globalAlpha = 0.5; }
                var origin = vec_add(base_xy, vec_mul(icon_offset,gamedata['territory']['cell_size']));
                SPUI.ctx.transform(icon_scale, 0, 0, icon_scale, origin[0], origin[1]);
                GameArt.assets[assetname].states['normal'].draw([0,0], 0, 0);
                SPUI.ctx.restore();

                if(owned && moving && feature['base_map_path'] && feature['base_map_path'].length >= 1) {
                    // draw remaining travel time
                    var path = feature['base_map_path'];
                    var togo = path[path.length-1]['eta'] - this.time;
                    if(togo > 1) {
                        var txt = pretty_print_time_brief(togo);
                        var size = 1.0;
                        this.draw_feature_label([base_xy[0] + gamedata['territory']['cell_size'][0]/2,
                                                 base_xy[1] + gamedata['territory']['cell_size'][1] + -.25*this.font.leading*size],
                                                [txt], (owned ? 'rgba(64,255,64,1)' : 'rgba(255,64,64,1)'), size);
                    }
                }

            } else {
                var icon_type;
                if(feature['base_type'] == 'quarry') {
                    if(!feature['base_icon']) {
                        throw Error('quarry feature is missing base_icon! '+JSON.stringify(feature));
                    }
                    icon_type = 'quarry_'+feature['base_icon'];
                } else {
                    var info = (feature['base_type'] == 'home' && feature['base_landlord_id'] ? PlayerCache.query_sync_fetch(feature['base_landlord_id']) : null);
                    if(info &&
                       (!('show_base_damage' in this.region.data) || this.region.data['show_base_damage']) &&
                       ((('base_damage' in info) && info['base_damage'] >= gamedata['matchmaking']['ladder_win_damage']) ||
                        (('base_repair_time' in info) && (info['base_repair_time'] >= this.time)))
                      ) {
                        icon_type = 'base_destroyed';
                    } else {
                        icon_type = 'base';
                    }
                }

                if(!GameArt.assets['region_tiles'].has_state(icon_type)) {
                    throw Error('region_tiles art asset is missing state "'+icon_type+'" for feature '+JSON.stringify(feature));
                }
                GameArt.assets['region_tiles'].states[icon_type].draw_topleft([base_xy[0]-cover[0], base_xy[1]-cover[1]-2], 0, 0);
            }

            var show_bubble = false, show_padlock = false, token_icon = null, show_strength = false;
            var show_trophy = this.winnable_ladder_points(feature);

            if(feature['LOCK_STATE'] && feature['LOCK_OWNER'] == feature['base_landlord_id'] &&
               !(player.raids_enabled() && feature['base_type'] == 'home') &&
               (feature['base_landlord_id'] != session.user_id || feature['base_type'] == 'home')) {
                show_bubble = true; // owner is here
            }
            if(feature['base_type'] == 'home' && ('protection_end_time' in feature)) {
                // check protection status
                if(feature['protection_end_time'] == 1 || feature['protection_end_time'] > this.time) {
                    show_bubble = true; // under protection
                }
            }

            if(feature['base_type'] == 'home' && feature['base_landlord_id'] && !is_ai_user_id_range(feature['base_landlord_id'])) {
                var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
                if(info && !player.in_attackable_level_range(info['player_level']||0) &&
                   !player.cooldown_active('revenge_defender:'+feature['base_landlord_id'].toString()) &&
                   this.region.pvp_level_gap_enabled()) {
                    show_padlock = true; // player is too low or high level to attack
                }
            }

            if(goog.array.contains(['hive','raid','quarry'], feature['base_type']) && ('base_template' in feature) && (feature['base_template'] in gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'])) {
                if(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['ui_tokens2']) {
                    token_icon = ItemDisplay.get_inventory_item_spec(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['ui_tokens2']['spec'])['store_icon'];
                    // if the template specifies its own token_icon, override the default one here
                    if(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['token_icon']) {
                        token_icon = gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['token_icon'];
                    }
                }
                if(!player.is_cheater && ('activation' in gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]) &&
                   !read_predicate(gamedata[{'hive':'hives_client','raid':'raids_client','quarry':'quarries_client'}[feature['base_type']]]['templates'][feature['base_template']]['activation']).is_satisfied(player,null)) {
                    show_padlock = true; // hive or quarry that player cannot attack
                }
            }

            if(gamedata['territory']['show_feature_strength']) {
                show_strength = true;
            }

            if(token_icon) {
                //var offset = [0.05,-0.20];
                var offset = [0.3,-0.25];
                SPUI.ctx.save();
                var scale = 1.3;
                var xy = vec_add(base_xy, vec_mul(offset,gamedata['territory']['cell_size']));
                SPUI.ctx.transform(scale,0,0,scale,xy[0],xy[1]);
                GameArt.assets[token_icon].states['normal'].draw_topleft([0,0],0,0);
                SPUI.ctx.restore();
            }

            if(show_padlock) {
                SPUI.ctx.save();
                var scale = 1.2;
                SPUI.ctx.transform(scale,0,0,scale,base_xy[0]-cover[0],base_xy[1]-cover[1]);
                GameArt.assets['inventory_padlock'].states['normal'].draw_topleft([48,-28],0,0); // [base_xy[0]-cover[0], base_xy[1]-cover[1]], 0, 0);
                SPUI.ctx.restore();
            }

            if(show_trophy > 0) {
                var offset = [0.37,-0.20];
                GameArt.assets['trophy_15x15'].states['pvp'].draw(vec_add(base_xy, vec_mul(offset,gamedata['territory']['cell_size'])), 0, client_time);
                this.draw_feature_label(vec_add(vec_add(base_xy, vec_mul(offset, gamedata['territory']['cell_size'])), [21,5]),
                                        ['+'+show_trophy.toString()], 'rgba(255,180,0,1)', 1);
            }

            // show time of any incoming raids
            if(player.raids_enabled() && this.zoom >= gamedata['territory']['show_alliance_membership_above_zoom']) { // abuse this option
                var incoming_togo = this.region.feature_incoming_raid_togo(feature);
                if(incoming_togo > 0) {
                    var ui_time = (incoming_togo <= 60 ? gamedata['strings']['regional_map']['incoming_time_1m'] : pretty_print_time_very_brief(incoming_togo));
                    var offset = [0.37,-0.20];
                    this.draw_feature_label(vec_add(vec_add(base_xy, vec_mul(offset, gamedata['territory']['cell_size'])), [10,-12]),
                                            [gamedata['strings']['regional_map']['incoming'].replace('%time', ui_time)], 'rgba(255,255,0,1)', 1);
                }
            }
            var busy_asset = null;

            if(feature['LOCK_STATE'] && feature['LOCK_OWNER'] != session.user_id && (feature['base_type'] != 'home' || feature['LOCK_OWNER'] != feature['base_landlord_id'])) {
                // mutex locked - in combat, or owner manipulating
                if(feature['LOCK_OWNER'] != feature['base_landlord_id']) { // feature locked by player who is not owner - being attacked
                    busy_asset = 'map_flame';
                } else {
                    busy_asset = 'loading_spinner';
                    // might be involved in an attack, but not for sure - check for nearby enemy objects
                    // (this is just a heuristic, not 100% ground truth, but it makes the map look cooler)
                    var neighbors = this.region.get_neighbors(feature['base_map_loc']);
                    for(var i = 0; i < neighbors.length; i++) {
                        var other = this.region.find_feature_at_coords(neighbors[i]);
                        if(other && other['LOCK_STATE'] && other['LOCK_OWNER'] && other['LOCK_OWNER'] != other['base_landlord_id']) { //('base_landlord_id' in other) && other['base_landlord_id'] != feature['base_landlord_id']
                            busy_asset = 'map_flame';
                            break;
                        }
                    }
                }
            }

            // show your own pending moves/halts as loading spinners
            if(!busy_asset && squad_pending && !moving) {
                busy_asset = 'loading_spinner';
            }

            // never show bubble if we're showing a flame
            if(busy_asset == 'map_flame') { show_bubble = false; }

            if(show_bubble) {
                GameArt.assets['map_bubble'].states['normal'].draw_topleft([base_xy[0]-cover[0], base_xy[1]-cover[1]], 0, 0);
            }

            if(busy_asset) {
                var offset = (busy_asset == 'map_flame' ? [0.5,0.15] : [0.5,0.4]);
                GameArt.assets[busy_asset].states['normal'].draw(vec_add(base_xy, vec_mul(offset,gamedata['territory']['cell_size'])), 0, client_time);
            }

            if(show_strength) {
                var offset = [0.70,0.66];
                this.draw_feature_strength(feature, vec_add(moving_xy || base_xy, vec_mul(offset, gamedata['territory']['cell_size'])));
            }
        }

        if(this.popup && this.popup.user_data['feature'] == feature && !moving) {
            // do not draw label when UI is up and the target is stationary
            show_label = false;
        }

        // allow cursor to inhibit label
        if(this.cursor && !this.cursor.allow_label(feature['base_map_loc'])) { show_label = false; }

        if(show_label) {
            var label = null;

            if(feature['base_type'] == 'squad' && owned) {
                var squad_name;
                if(squad_sid in player.squads) {
                    squad_name = player.squads[squad_sid]['ui_name'];
                } else {
                    squad_name = gamedata['strings']['regional_map']['unknown_name'];
                }
                label = /*gamedata['strings']['squads']['squad']+' '+*/ squad_name;
            }

            if(!label && ('base_landlord_id' in feature)) {
                var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
                if(info) {
                    // quarries show the size of the quarry instead of the owner's level
                    var show_level = (feature['base_type'] !== 'quarry');
                    label = this.pcache_to_name(info, (this.zoom < gamedata['territory']['abbreviate_labels_below_zoom'] ? 2 : 1), show_level);
                    if(feature['base_type'] === 'quarry') {
                        label += ' ('+quarry_richness_ui_str(feature['base_richness'])+')';
                    }
                } else {
                    label = gamedata['strings']['regional_map']['loading'];
                }
            }

            if(!label) {
                if(feature['base_type'] == 'squad') {
                    // unowned squads get generic names
                    label = gamedata['strings']['regional_map']['unknown_squad'];
                } else {
                    label = feature['base_ui_name'] || gamedata['strings']['regional_map']['unknown_name'];
                }
            }

            // XXX temporary hack for raids
            if(feature['base_type'] == 'squad' && feature['raid'] && !owned) {
                // other player's raid - only visible to developers
                label = '(DEV-R) '+label;
            } else if(feature['base_type'] == 'raid' || (feature['base_type'] == 'squad' && feature['raid'])) {
                label = '(R) '+label;
            }

            if(classification+'_blink' in gamedata['territory']['label_colors']) {
                if((client_time % gamedata['territory']['label_blink_period']) < gamedata['territory']['label_blink_on']) {
                    classification = classification+'_blink';
                }
            }

            var size = (!SPUI.low_fonts ? (gamedata['territory']['label_sizes'][classification] || 1) : 1);

            var draw_color = gamedata['territory']['label_colors'][classification];
            var label_height = this.draw_feature_label([label_xy[0] + gamedata['territory']['cell_size'][0]/2,
                                                        label_xy[1] + gamedata['territory']['cell_size'][1] + 0.5*this.font.leading*size],
                                                       [label], draw_color, size);
            var subtitle = null;
            if(/*feature['base_type'] == 'home' &&*/ feature['base_landlord_id'] && !is_ai_user_id_range(feature['base_landlord_id']) &&
               this.zoom >= gamedata['territory']['show_alliance_membership_above_zoom']) {
                var info = PlayerCache.query_sync_fetch(feature['base_landlord_id']);
                if(info && ('alliance_id' in info) && info['alliance_id'] >= 0) {
                    var alinfo = AllianceCache.query_info(info['alliance_id']);
                    if(alinfo && ('ui_name' in alinfo)) {
                        var display_name = (('chat_tag' in alinfo) && alinfo['chat_tag'].length > 0 && player.get_any_abtest_value('enable_alliance_chat_tags', gamedata['client']['enable_alliance_chat_tags'])) ? alinfo['chat_tag'] : alinfo['ui_name'];
                        subtitle = display_name;
                    }
                }
            } else if(goog.array.contains(['hive','raid'], feature['base_type']) && ('base_template' in feature) &&
                      gamedata[feature['base_type']+'s_client']['templates'][feature['base_template']]) {
                var template = gamedata[feature['base_type']+'s_client']['templates'][feature['base_template']];
                // default
                subtitle = gamedata['strings']['regional_map'][feature['base_type']+'_label'].replace('%s',feature['base_ui_name']);

                var ls = [];
                if(template['ui_tokens2']) {
                    var spec = ItemDisplay.get_inventory_item_spec(template['ui_tokens2']['spec']);
                    if(template['ui_tokens2']['stack'] >= 500) {
                        var thousands = template['ui_tokens2']['stack']/1000.0;
                        ls.push(thousands.toFixed(1)+'k '+ItemDisplay.get_inventory_item_ui_name(spec));
                    } else {
                        ls.push(pretty_print_number(template['ui_tokens2']['stack'])+'x '+ItemDisplay.get_inventory_item_ui_name(spec));
                    }
                }
                if(template['kill_points']) {
                    var points = template['kill_points'];
                    if('hive_kill_point_scale' in this.region.data) {
                        points = Math.max(1, Math.floor(points * this.region.data['hive_kill_point_scale']));
                    }
                    if(points > 0) {
                        ls.push(gamedata['strings']['regional_map']['with_kill_points'].replace('%d', pretty_print_number(points)));
                    }
                }
                if(ls.length > 0) {
                    subtitle = goog.string.trim(subtitle + ' ' + ls.join(', '));
                }
            }

            if(subtitle) {
                this.draw_feature_label([label_xy[0] + gamedata['territory']['cell_size'][0]/2,
                                         label_xy[1] + gamedata['territory']['cell_size'][1] + 1.25*this.font.leading*size + label_height],
                                        [subtitle], draw_color, 0.75*size);
            }
        }
    }
};

// return a string describing the type of visual parameters to apply to the feature when drawing it on the map
// (see gamedata_main.json/territory)
RegionMap.RegionMap.prototype.classify_feature = function(feature) {
    var info = ('base_landlord_id' in feature ? PlayerCache.query_sync_fetch(feature['base_landlord_id']) : null);
    var owned = (feature['base_landlord_id'] === session.user_id);
    var locked = (feature['LOCK_STATE'] && (feature['LOCK_STATE'] != 0) &&
                  !(player.raids_enabled() && feature['LOCK_STATE'] == 1 && feature['base_type'] == 'home')) ||
        (feature['repeat_attack_cooldown_expire'] && feature['repeat_attack_cooldown_expire'] > this.time);

    if(!owned && feature['base_type'] == 'home') {
        if(('protection_end_time' in feature) && (feature['protection_end_time'] == 1 || feature['protection_end_time'] > this.time)) {
            locked = true;
        }
    }

    // do not show bases as locked, if they are locked by us
    if(owned && feature['LOCK_OWNER'] && feature['LOCK_OWNER'] == session.user_id) { locked = false; }

    var color;
    if(locked) {
        color = 'locked';
    } else if(owned) {
        if(feature['base_type'] == 'home') {
            color = 'your_home';
        } else if(feature['base_type'] == 'squad') {
            color = 'your_squad';
        } else {
            color = 'owned';
        }
    } else if(feature['base_type'] == 'home') {
        if(info && ('alliance_id' in info) && info['alliance_id'] >= 0) {
            if(info['alliance_id'] == session.alliance_id) {
                color = 'alliance_friendly';
            } else {
                color = 'alliance_hostile';
            }
        } else {
            color = 'other_home';
        }

        if(!is_ai_user_id_range(feature['base_landlord_id']) && info &&
           !player.in_attackable_level_range(info['player_level']||0) &&
           !player.cooldown_active('revenge_defender:'+feature['base_landlord_id'].toString()) &&
           this.region.pvp_level_gap_enabled()) {
            color += ((info['player_level']||0) > player.level() ? '_level_too_high' : '_level_too_low');
        }

    } else if(feature['base_type'] == 'squad') {
        if(info && ('alliance_id' in info) && info['alliance_id'] >= 0) {
            if(info['alliance_id'] == session.alliance_id) {
                color = 'alliance_friendly_squad';
            } else {
                color = 'alliance_hostile_squad';
            }
        } else {
            color = 'other_squad';
        }
    } else if(feature['base_type'] == 'quarry') {
        if(info && ('alliance_id' in info) && info['alliance_id'] >= 0) {
            if(info['alliance_id'] == session.alliance_id) {
                color = 'alliance_friendly';
            } else {
                color = 'alliance_hostile';
            }
        } else {
            if((feature['base_icon'] in gamedata['resources']) || ('quarry_'+feature['base_icon'] in gamedata['territory']['label_colors'])) {
                color = 'quarry_'+feature['base_icon'];
            } else {
                color = 'other_home';
            }
        }
        var richness_table = gamedata['strings']['regional_map']['richness'];
        var max_richness = richness_table[richness_table.length-1][0];
        if(feature['base_richness'] >= max_richness) {
            color += '_xl';
        }
    } else if(goog.array.contains(['hive','raid'], feature['base_type'])) {
        color = feature['base_type'];
        if(feature['base_climate'] && feature['base_climate'].indexOf('ice')==0) {
            color += '_ice';
        }
    } else {
        color = 'default';
    }
    return color;
};

RegionMap.RegionMap.prototype.trigger_spfx_at = function(vfx_data, loc) {
    var wxy = this.cell_to_widget(vec_add(loc, [0.5,0.5]));
    // clip
    if(wxy[0] < 0 || wxy[0] >= this.wh[0] || wxy[1] < 0 || wxy[1] >= this.wh[1]) {
        return;
    }
    var absolute_xy = vec_add(wxy, this.get_absolute_xy());
    // XXX leaks - find a way to delete when obsolete
    this.spfx_list.push(this.fxworld.add_visual_effect_at_time(absolute_xy, 0, [0,1,0], client_time, vfx_data, false /* no sound */, {'is_ui': true, 'sprite_scale': [this.zoom,this.zoom]}));
};

RegionMap.RegionMap.prototype.draw = function(offset) {
    if(this.region && this.follow_travel && this.region.data['storage'] != 'nosql') {
        var home_feature = this.region.find_home_feature();
        if(home_feature) {
            var dest_loc = player.travel_state['dest_loc'] || home_feature['base_map_loc'];
            var travel_feature = this.region.find_feature_at_coords(dest_loc);

            //if(travel_feature === home_feature) { travel_feature = null; }
            if(travel_feature) {
                var progress;
                if(this.time > player.travel_state['end_time']) {
                    progress = 1;
                } else {
                    progress = (this.time - player.travel_state['start_time'])/(player.travel_state['end_time']-player.travel_state['start_time']);
                }

                var home_pos = home_feature['base_map_loc'];
                var dest_pos = travel_feature['base_map_loc'];

                var home_xy = this.cell_to_field(home_pos);
                var dest_xy = this.cell_to_field(dest_pos);

                var cur_xy = [home_xy[0] + progress*(dest_xy[0]-home_xy[0]) + gamedata['territory']['cell_size'][0]/2,
                              home_xy[1] + progress*(dest_xy[1]-home_xy[1]) + gamedata['territory']['cell_size'][1]/2];

                this.pan_to_field(cur_xy);
            }
        }
    }

    // update slow pan
    if(this.pan_goal) {
        var delta = vec_sub(this.pan_goal, this.pan);
        var dist = vec_length(delta);
        if(dist < 2) {
            this.pan_goal = null;
        } else {
            var dir = vec_scale(1.0/dist, delta);
            var dpan = vec_scale(gamedata['territory']['pan_speed']*dist, dir);
            this.pan = vec_add(this.pan, dpan);
        }
    }

    SPUI.ctx.save();

    //var BEGIN_SCALE = 1.0, END_SCALE = 0.15;
    //var BEGIN_SIZE = 1.0, END_SIZE = 8.0;

    var font_scale = clamp(1.0/this.zoom, 1, gamedata['territory']['max_label_zoom']);
    this.font = SPUI.make_font(Math.floor(gamedata['territory']['label_font_size'] * font_scale),
                               Math.floor(gamedata['territory']['label_font_leading'] * font_scale), 'thick');

    SPUI.ctx.font = this.font.str();

    if(1) {
        // clip to edges
        SPUI.ctx.beginPath();
        SPUI.ctx.moveTo(this.xy[0]+offset[0], this.xy[1]+offset[1]);
        SPUI.ctx.lineTo(this.xy[0]+offset[0]+this.wh[0], this.xy[1]+offset[1]);
        SPUI.ctx.lineTo(this.xy[0]+offset[0]+this.wh[0], this.xy[1]+offset[1]+this.wh[1]);
        SPUI.ctx.lineTo(this.xy[0]+offset[0], this.xy[1]+offset[1]+this.wh[1]);
        SPUI.ctx.lineTo(this.xy[0]+offset[0], this.xy[1]+offset[1]);
        SPUI.ctx.clip();
    }

    if(this.region) {
        // constrain pan (after zoom is applied)
        this.pan_limits = [[gamedata['territory']['cell_size'][0]/2 + (this.wh[0]/2)/this.zoom - (gamedata['territory']['grid']['edge_margin'][0]*this.wh[0])/this.zoom,
                            this.region.data['dimensions'][0]*gamedata['territory']['cell_size'][0] - gamedata['territory']['cell_size'][0]/2 - (this.wh[0]/2)/this.zoom + (gamedata['territory']['grid']['edge_margin'][0]*this.wh[0])/this.zoom],
                           [gamedata['territory']['cell_size'][1]/2 + (this.wh[1]/2)/this.zoom - (gamedata['territory']['grid']['edge_margin'][1]*this.wh[1])/this.zoom,
                            this.region.data['dimensions'][1]*gamedata['territory']['cell_rowoffset'][1] - gamedata['territory']['cell_size'][1]/2 - (this.wh[1]/2)/this.zoom + (gamedata['territory']['grid']['edge_margin'][1]*this.wh[1])/this.zoom]];

        // prevent ping-pong when zoomed very far out
        if(this.pan_limits[0][1] < this.pan_limits[0][0]) { this.pan_limits[0][1] = this.pan_limits[0][0] = (this.pan_limits[0][1]+this.pan_limits[0][0])/2; }
        if(this.pan_limits[1][1] < this.pan_limits[1][0]) { this.pan_limits[1][1] = this.pan_limits[1][0] = (this.pan_limits[1][1]+this.pan_limits[1][0])/2; }

        this.pan = [clamp(this.pan[0], this.pan_limits[0][0], this.pan_limits[0][1]),
                    clamp(this.pan[1], this.pan_limits[1][0], this.pan_limits[1][1])];


        // set up the field->widget transform
        SPUI.ctx.transform(this.zoom, 0,
                           0, this.zoom,
                           this.xy[0]+offset[0] - this.pan[0]*this.zoom + this.wh[0]/2,
                           this.xy[1]+offset[1] - this.pan[1]*this.zoom + this.wh[1]/2);

        // all drawing below needs to be in field coordinates

        // draw grid background
        if(gamedata['territory']['grid']['line_width'] > 0) {
            // widget coordinates at which corners of map will land
            var ul = this.cell_to_widget([0,0]), lr = this.cell_to_widget([this.region.data['dimensions'][0]-1,this.region.data['dimensions'][1]-1]);
            if(ul[0] > 0 || ul[1] > 0 || lr[0] < this.wh[0] || lr[1] < this.wh[1]) {
                // draw grid
                var line_width = gamedata['territory']['grid']['line_width'];
                var minor_line_width = gamedata['territory']['grid']['minor_line_width'];
                var spacing = gamedata['territory']['grid']['spacing'];
                var minor_spacing = gamedata['territory']['grid']['minor_spacing'];
                var fill_color = gamedata['territory']['grid']['fill_color'];

                var start_cell = this.widget_to_cell_unclamped([0,0]), end_cell = this.widget_to_cell_unclamped(this.wh);
                var start_grid = [Math.floor(start_cell[0]/spacing)-1, Math.floor(start_cell[1]/spacing)-2];
                var end_grid = [Math.ceil(end_cell[0]/spacing), Math.ceil(end_cell[1]/spacing)];

                SPUI.ctx.save();

                SPUI.ctx.strokeStyle = gamedata['territory']['grid']['stroke_color'];
                SPUI.ctx.lineWidth = line_width;

                if(fill_color) {
                    SPUI.ctx.fillStyle = fill_color;
                    SPUI.ctx.fillRect(start_grid[0]*spacing*gamedata['territory']['cell_size'][0],
                                      start_grid[1]*spacing*gamedata['territory']['cell_size'][1],
                                      (end_grid[0]-start_grid[0])*spacing*gamedata['territory']['cell_size'][0],
                                      (end_grid[1]-start_grid[1])*spacing*gamedata['territory']['cell_size'][1]);
                }

                SPUI.ctx.beginPath();
                for(var gy = start_grid[1]; gy <= end_grid[1]; gy++) {
                    SPUI.ctx.moveTo(start_grid[0]*spacing*gamedata['territory']['cell_size'][0],
                                    gy*spacing*gamedata['territory']['cell_size'][1]);
                    SPUI.ctx.lineTo((end_grid[0]+1)*spacing*gamedata['territory']['cell_size'][0],
                                    gy*spacing*gamedata['territory']['cell_size'][1]);
                }
                for(var gx = start_grid[0]; gx <= end_grid[0]; gx++) {
                    SPUI.ctx.moveTo(gx*spacing*gamedata['territory']['cell_size'][0],
                                    start_grid[1]*spacing*gamedata['territory']['cell_size'][1]);
                    SPUI.ctx.lineTo(gx*spacing*gamedata['territory']['cell_size'][0],
                                    (end_grid[1]+1)*spacing*gamedata['territory']['cell_size'][1]);
                }
                SPUI.ctx.stroke();

                if(minor_line_width > 0) {
                    var ratio = spacing/minor_spacing;
                    SPUI.ctx.lineWidth = minor_line_width;
                    SPUI.ctx.beginPath();
                    for(var my = start_grid[1]*ratio; my <= (end_grid[1]+1)*ratio; my++) {
                        SPUI.ctx.moveTo(start_grid[0]*spacing*gamedata['territory']['cell_size'][0],
                                        my*(spacing/ratio)*gamedata['territory']['cell_size'][1]);
                        SPUI.ctx.lineTo((end_grid[0]+1)*spacing*gamedata['territory']['cell_size'][0],
                                        my*(spacing/ratio)*gamedata['territory']['cell_size'][1]);
                    }
                    for(var mx = start_grid[0]*ratio; mx <= (end_grid[0]+1)*ratio; mx++) {
                        SPUI.ctx.moveTo(mx*(spacing/ratio)*gamedata['territory']['cell_size'][0],
                                        start_grid[1]*spacing*gamedata['territory']['cell_size'][1]);
                        SPUI.ctx.lineTo(mx*(spacing/ratio)*gamedata['territory']['cell_size'][0],
                                        (end_grid[1]+1)*spacing*gamedata['territory']['cell_size'][1]);
                    }
                    SPUI.ctx.stroke();
                }

                SPUI.ctx.restore();
            }
        }

        var csize = gamedata['territory']['cell_size'];
        var cover = gamedata['territory']['cell_overlap'];
        var rowoff = gamedata['territory']['cell_rowoffset'];

        var roi = [this.widget_to_cell([(-gamedata['territory']['cell_size'][0]/2)*this.zoom,
                                        (-gamedata['territory']['cell_overlap'][1])*this.zoom]),
                   this.widget_to_cell([this.wh[0]+(gamedata['territory']['cell_size'][0]/2)*this.zoom,
                                        this.wh[1]+(gamedata['territory']['cell_overlap'][1])*this.zoom])];

        var FADE_BEGIN = gamedata['territory']['tile_fade_zoom'][0], FADE_END = gamedata['territory']['tile_fade_zoom'][1];
        var fade_cells = 1.0;

        // fade from individual cells to image sprite at wide zooms
        var bg_img = ('bg_image' in this.region.data ? /** @type {!GameArt.Sprite} */ (GameArt.assets[this.region.data['bg_image']].states['normal']).images[0] : null);

        if(bg_img && this.gfx_detail < 1) {
            fade_cells = 0; // turn off cell drawing entirely in low graphics mode
        }

        // page in the image so it doesn't flicker on first zoom-out
        if(bg_img) { bg_img.check_delay_load(); }

        if((fade_cells <= 0 || this.zoom < FADE_BEGIN) && bg_img) {
            // set transform so that the sprite will draw across the entire play area
            var img_to_field = [csize[0]*this.region.data['dimensions'][0] / bg_img.wh[0],
                                rowoff[1]*this.region.data['dimensions'][1] / bg_img.wh[1]];
            SPUI.ctx.save();
            SPUI.ctx.transform(img_to_field[0], 0,
                               0, img_to_field[1],
                               0, 0);
            bg_img.drawSubImage([0,0], bg_img.wh, [0,0], bg_img.wh);
            SPUI.ctx.restore();
            fade_cells *= 1 - (FADE_BEGIN-this.zoom)/(FADE_BEGIN-FADE_END);
        }

        if(fade_cells > 0.0) {
            SPUI.ctx.save();
            if(fade_cells < 1.0) {
                SPUI.ctx.globalAlpha = fade_cells;
            }

            var sprites = [];
            for(var i = 0; i < gamedata['territory']['tiles'].length; i++) {
                sprites.push(GameArt.assets['region_tiles'].states[gamedata['territory']['tiles'][i]['sprite']]);
            }

            var skip = (this.zoom < 0.15 ? 1 : 1);
            if(skip > 1) {
                roi[0][0] = skip*Math.floor(roi[0][0]/skip);
                roi[0][1] = skip*Math.floor(roi[0][0]/skip);
            }

            for(var cy = roi[0][1]; cy <= roi[1][1]; cy += skip) {
                for(var cx = roi[0][0]; cx <= roi[1][0]; cx += skip) {

                    var xy = this.cell_to_field([cx,cy]);

                    //var tile_type = (cy % 4);
                    var tile_type = this.region.read_terrain([cx,cy]);
                    var sprite = sprites[tile_type];
                    if(!sprite) {
                        throw Error('gamedata.art.region_tiles missing sprite '+tile_type);
                    }

                    /* something is bad about IE performance rendering the little tiles...
                    if((spin_demographics['browser_name'] !== 'Explorer') && false && (this.zoom < 0.15)) {
                        SPUI.ctx.fillStyle = sprite.avg_color;
                        SPUI.ctx.fillRect(xy[0], xy[1], skip*gamedata['territory']['cell_size'][0], skip*gamedata['territory']['cell_size'][1]);
                        continue;
                    } */

                    var tile_xy = [xy[0]-cover[0], xy[1]-cover[1]];

                    if(sprite.wh[0] != csize[0]+2*cover[0] || sprite.wh[1] != csize[1]+2*cover[1]) {
                        throw Error('region tile has unexpected size, got '+sprite.wh[0]+'x'+sprite.wh[1]+' wanted '+(csize[0]+2*cover[0])+'x'+(csize[1]+2*cover[1]));
                    }

                    sprite.draw_topleft(tile_xy, 0, 0);
                }
            }
            SPUI.ctx.restore();
        }

        var influence_alpha = Math.min(Math.max(1-fade_cells, 0), 1);
        for(var i = 0; i < this.region.features.length; i++) {
            var feature = this.region.features[i];
            this.draw_feature_influence(roi, feature, influence_alpha);
        }

        this.draw_hovercell();

        var draw_list = this.sort_features_for_draw(roi, this.region.features);
        goog.array.forEach(draw_list, function(feature) { this.draw_feature(feature); }, this);

        if(PLAYFIELD_DEBUG && this.hstar_context) {
            var scene = this.hstar_context.debug_scene;
            SPUI.ctx.save();
            goog.array.forEach(scene, function(item) {
                var pos = item[0], col_str = item[1];
                var xy = this.cell_to_field([pos[0]+0.5, pos[1]+0.5]);
                SPUI.ctx.fillStyle = col_str;
                SPUI.ctx.fillRect(xy[0], xy[1], 10, 10);
            }, this);
            SPUI.ctx.restore();
        }

        this.draw_travel();

        if(this.cursor) { this.cursor.draw(); }

    } else {
        SPUI.ctx.fillStyle = '#000000';
        SPUI.ctx.fillRect(this.xy[0]+offset[0], this.xy[1]+offset[1], this.wh[0], this.wh[1]);
    }
    SPUI.ctx.restore();
};

/** @param {number} squad_id */
RegionMap.invoke_squad_speedup_dialog = function(squad_id) {
    var squad_data = player.squads[squad_id.toString()];
    if(!squad_data) {
        return null;
    }

    var dialog_data = gamedata['dialogs']['speedup_dialog'];
    var dialog = new SPUI.Dialog(dialog_data);
    dialog.user_data['dialog'] = 'speedup_dialog';
    dialog.user_data['squad_id'] = squad_id;
    dialog.modal = true;
    install_child_dialog(dialog);
    dialog.auto_center();

    dialog.widgets['title_speedup'].show = true;
    dialog.widgets['close_button'].onclick = close_parent_dialog;
    dialog.widgets['ok_button'].onclick =
        dialog.widgets['price_display'].onclick = function(w) {
            var dialog = w.parent;
            var squad_id = dialog.user_data['squad_id'];
            // update price since time may have passed
            var new_price = Store.get_user_currency_price(GameObject.VIRTUAL_ID, gamedata['spells']['SQUAD_MOVEMENT_SPEEDUP_FOR_MONEY'], squad_id);
            if(new_price < 0) {
                // order became invalid, maybe the squad got to its destination already
                close_parent_dialog(w);
            } else {
                if(Store.place_user_currency_order(GameObject.VIRTUAL_ID, "SQUAD_MOVEMENT_SPEEDUP_FOR_MONEY", squad_id,
                                                   (function (_w) { return function() { close_parent_dialog(_w); }; })(w)
                                                  )) {
                    invoke_ui_locker(synchronizer.request_sync());
                    dialog.widgets['ok_button'].str = dialog.data['widgets']['ok_button']['ui_name_pending'];
                    dialog.widgets['ok_button'].state = 'disabled'; dialog.widgets['price_display'].onclick = null;
                }
            }
        };
    dialog.ondraw = RegionMap.update_squad_speedup_dialog;
    dialog.widgets['price_display'].bg_image = player.get_any_abtest_value('price_display_asset', gamedata['store']['price_display_asset']);
    dialog.widgets['price_display'].state = Store.get_user_currency();
    return dialog;
};

/** @param {!SPUI.Dialog} dialog */
RegionMap.update_squad_speedup_dialog = function(dialog) {
    var squad_id = dialog.user_data['squad_id'];
    if(!player.squad_is_deployed(squad_id) || !player.squad_is_moving(squad_id)) {
        close_dialog(dialog);
        return;
    }
    var squad_data = player.squads[squad_id.toString()];

    var path = squad_data['map_path'];
    var time_left = path[path.length-1]['eta'] - server_time;
    if(time_left < 0) {
        close_dialog(dialog);
        return;
    }
    time_left = Math.max(time_left, 1);

    var description_finish = gamedata['strings']['speedup']['finish_squad_movement'].replace('%s', squad_data['ui_name']);
    var description_before = gamedata['strings']['speedup']['before_generic'];
    var description = gamedata['strings']['speedup']['template'].replace('%TIME',pretty_print_time(time_left)).replace('%FINISH', description_finish).replace('%BEFORE', description_before);
    dialog.widgets['description'].set_text_with_linebreaking(description);

    var price = Store.get_user_currency_price(GameObject.VIRTUAL_ID, gamedata['spells']['SQUAD_MOVEMENT_SPEEDUP_FOR_MONEY'], squad_id);
    dialog.widgets['price_display'].str = Store.display_user_currency_price(price); // PRICE
    dialog.widgets['price_display'].tooltip.str = Store.display_user_currency_price_tooltip(price);
};

/** @param {number} squad_id */
RegionMap.invoke_squad_speedup_item_dialog = function(squad_id) {
    var squad_data = player.squads[squad_id.toString()];
    if(!squad_data) {
        return null;
    }

    var do_it = (function (_squad_id) { return function() {
        var spellname = 'SQUAD_MOVEMENT_SPEEDUP_FOR_ITEM';
        var spell = gamedata['spells'][spellname];
        if(Store.place_order(spell['currency'], GameObject.VIRTUAL_ID, spellname, squad_id)) {
            invoke_ui_locker(synchronizer.request_sync());
        }
    }; })(squad_id);

    var tip = gamedata['strings']['squad_speedup_item_confirm'];
    var dialog = invoke_child_message_dialog(tip['ui_title'], tip['ui_description'],
                                             {'dialog':'message_dialog_big',
                                              'ok_button_ui_name': tip['ui_button'],
                                              'cancel_button': true,
                                              'on_ok': do_it});

    return dialog;
};
