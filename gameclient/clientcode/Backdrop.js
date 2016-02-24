goog.provide('Backdrop');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('GameArt');
goog.require('GameObjectCollection');

/** @param {!Array<number>} ncells */
Backdrop.draw_area_bounds = function(ncells) {
    var xy;
    ctx.beginPath();
    xy = ortho_to_draw([0,0]);
    ctx.moveTo(xy[0],xy[1]);
    xy = ortho_to_draw([ncells[0],0]);
    ctx.lineTo(xy[0],xy[1]);
    xy = ortho_to_draw([ncells[0],ncells[1]]);
    ctx.lineTo(xy[0],xy[1]);
    xy = ortho_to_draw([0,ncells[1]]);
    ctx.lineTo(xy[0],xy[1]);
    ctx.closePath();
    ctx.stroke();
};


/** @param {!Base.Base} base
    @param {!GameObjectCollection.GameObjectCollection} cur_objects */
Backdrop.draw_scenery = function(base, cur_objects) {
    // draw scenery objects
    var obj_list = [];
    cur_objects.for_each(function(obj) {
        if(obj.spec['is_scenery'] && obj.spec['draw_flat'] && (SPFX.detail >= 0 || obj.spec['is_debris'])) {
            // would rather not have to pass World here - using null means scenery objects can't move
            obj.update_draw_pos(null);
            obj_list.push(obj);
        }
    });
    // do some Z-sorting
    obj_list.sort(sort_scene_objects);

    // would rather not have to pass World here - using null means scenery objects can't have permanent effects
    goog.array.forEach(obj_list, function(obj) { draw_building_or_inert(null,obj,1); });

    // draw building bases
    if(SPFX.detail >= 2) {
        var climate_data = (base && goog.object.getCount(base.base_climate_data)>0 ? base.base_climate_data : gamedata['climates'][gamedata['default_climate']]);
        if('building_bases' in climate_data) {
            var base_list = [];
            cur_objects.for_each(function(obj) {
                if(obj.is_building()) {
                    var key = obj.spec['gridsize'][0].toString()+'x'+obj.spec['gridsize'][1].toString();
                    if(key in climate_data['building_bases']) {
                        obj.update_draw_pos(null);
                        base_list.push(obj);
                    }
                }
            });
            base_list.sort(sort_scene_objects);
            goog.array.forEach(base_list, function(obj) {
                var key = obj.spec['gridsize'][0].toString()+'x'+obj.spec['gridsize'][1].toString();
                var sprite = GameArt.assets[climate_data['building_bases'][key]];
                var xy = vec_floor(ortho_to_draw([obj.x, obj.y]));
                if(!sprite.prep_for_draw(xy, 0, client_time, 'normal')) {
                    return; // not ready yet, no gray box
                }
                sprite.draw(xy, 0, client_time, 'normal');
            });
        }
    }
}

Backdrop.draw_blank = function() {
    ctx.save();
    set_default_canvas_transform(ctx); // undo playfield transform
    ctx.fillStyle = '#202020';
    ctx.fillRect(0,0,canvas_width,canvas_height);
    ctx.restore();
}

/** @param {!Base.Base} base
    @param {boolean} is_home_base
    @param {boolean} is_friendly_base
    @param {!Object} data - climate backdrop data */
Backdrop.draw_tiled = function(base, is_home_base, is_friendly_base, data) {
    var ncells = base.ncells();
    var assetname = data[is_home_base || is_friendly_base ? 'friendly' : 'hostile'];

    var asset = GameArt.assets[assetname];
    var main_sprite = /** @type {!GameArt.Sprite} */ (GameArt.assets[assetname].states['fullleft']);
    var main_image = main_sprite.images[0];
    if(!main_image.data_loaded) {
        // start it loading
        main_image.prep_for_draw();
        // but draw blank for now
        Backdrop.draw_blank();
        return false;
    }

    ctx.save();
    set_default_canvas_transform(ctx); // undo playfield transform

    // [2,1]*tilesize must evenly divide nells*cellsize/2 in order for the edge tiles to line up
    // tilesize must be even
    if(!main_sprite.wh) { throw Error('background sprite needs specific dimensions'); }
    var tilesize = (view_is_zoomed() ? vec_scale(view_zoom, main_sprite.wh) : main_sprite.wh); // size of a bg tile in pixels
    var maptiles = vec_div(vec_mul(ncells,vec_div(cellsize,[2,2])), main_sprite.wh);
    if(!vec_equals(vec_mod(vec_mul([0.5,1],maptiles), 1), [0,0])) {
        throw Error('background tilesize does not evenly divide '+(ncells[0]*cellsize[0]).toString()+'x'+(ncells[1]*cellsize[1]).toString());
    }
    if(!vec_equals(vec_mod(main_sprite.wh, 2), [0,0])) {
        throw Error('background tilesize is not even: '+tilesize[0]+'x'+tilesize[1]);
    }
    maptiles = vec_floor(maptiles);
    //console.log('maptiles '+maptiles[0]+'x'+maptiles[1]);

    // pixel coordinates of top-left of view relative to game field's [0,0] origin
    // subtract [0,tilesize[1]] to shift the tiles up one-half-height vs the playfield (see TILES photoshop layer to visualize why)
    //var start = vec_sub(vec_sub(view_pos, vec_sub(view_pos, vec_scale(view_zoom, [canvas_width_half,canvas_height_half])), [0,tilesize[1]/2]);
    var start = vec_sub(vec_sub(vec_scale(view_zoom, view_pos), [canvas_width_half, canvas_height_half]), [0, tilesize[1]/2]);
    var end = vec_add(start, [canvas_width, canvas_height]);

    var istart = Math.floor(start[1]/tilesize[1]);
    var iend = Math.floor(end[1]/tilesize[1]);
    var jstart =  Math.floor(start[0]/tilesize[0]);
    var jend = Math.floor(end[0]/tilesize[0]);

    //console.log('jstart '+jstart+' istart '+istart);

    for(var i = istart; i <= iend; i++) {
        for(var j = jstart; j <= jend; j++) {
            var x = j*tilesize[0] - start[0];
            var y = i*tilesize[1] - start[1];

            // 16 possible cases for the tile!
            var state;
            var debug_color = '#ffffff';

            if(j >= 0) {
                // right side
                if(i < 0) {
                    // top
                    if(i < -maptiles[0]+j-1) {
                        state = 'empty';
                    } else if(i == -maptiles[0]+j-1) {
                        if(j == 0) {
                            state = 'corner_nwright'; debug_color='#ff0000';
                        } else if(j == maptiles[0]) {
                            state = 'corner_neright'; debug_color='#ff0000';
                        } else {
                            state = 'edge_nright'; debug_color='#880000';
                        }
                    } else if(i == -maptiles[0]+j) {
                        if(j == maptiles[0]-1) {
                            state = 'corner_neleft'; debug_color='#ff0000';
                        } else {
                            state = 'edge_nleft';  debug_color='#880000';
                        }
                    } else {
                        state = 'full';
                    }
                } else {
                    // bottom
                    if(i < maptiles[0]-j-2) {
                        state = 'full';
                    } else if(i == maptiles[0]-j-2) {
                        state = 'edge_eleft';  debug_color='#008800';
                    } else if(i == maptiles[0]-j-1) {
                        if(j == 0) {
                            state = 'corner_seright'; debug_color='#00ff00';
                        } else {
                            state = 'edge_eright'; debug_color='#008800';
                        }
                    } else {
                        state = 'empty';
                    }
                }
            } else {
                // left side
                if(i < 0) {
                    // top
                    if(i < -maptiles[0]-j-2) {
                        state = 'empty';
                    } else if(i == -maptiles[0]-j-2) {
                        if(j == -1) {
                            state = 'corner_nwleft'; debug_color='#ff0000';
                        } else if(j == -maptiles[0]-1) {
                            state = 'corner_swleft'; debug_color='#ff00ff';
                        } else {
                            state = 'edge_wleft'; debug_color='#000088';
                        }
                    } else if(i == -maptiles[0]-j-1) {
                        if(j == -maptiles[0]) {
                            state = 'corner_swright'; debug_color='#0000ff';
                        } else {
                            state = 'edge_wright'; debug_color='#000088';
                        }
                    } else {
                        state = 'full';
                    }
                } else {
                    // bottom
                    if(i < maptiles[0]+j-1) {
                        state = 'full';
                    } else if(i == maptiles[0]+j-1) {
                        state = 'edge_sright'; debug_color='#888800';
                    } else if(i == maptiles[0]+j) {
                        if(j == -1) {
                            state = 'corner_seleft'; debug_color='#ffff00';
                        } else {
                            state = 'edge_sleft'; debug_color='#888800';
                        }
                    } else {
                        state = 'empty';
                    }
                }
            }

            if(state == 'full') { // alternate left/right
                state = (((i+j)&1) ? 'fullright' : 'fullleft');
                // make use of alternate left/right sprites if available
                if('fullleft3' in asset.states) {
                    var mod = (i+Math.floor((i+j)/2)+maptiles[0]+5)%4;
                    if(mod > 0) {
                        state += mod.toString();
                    }
                }
            }

            if(!(state in asset.states)) {
                console.log("bad backdrop state "+state);
                state = 'fullleft';
            }

            var image = /** @type {!GameArt.Sprite} */ (asset.states[state]).images[0];
            var w = tilesize[0], h = tilesize[1];
            var sx = 0, sy = 0, sw = main_sprite.wh[0], sh = main_sprite.wh[1];

            if(!view_is_zoomed()) {
                // perform clipping
                // left
                if(x < 0) {
                    sx = -x;
                    w += x;
                    sw += x;
                    x = 0;
                }
                // top
                if(y < 0) {
                    sy = -y;
                    h += y;
                    sh += y;
                    y = 0;
                }
                // right
                if((x+w) >= canvas_width) {
                    w = canvas_width-x;
                    sw = canvas_width-x;
                }
                // bottom
                if((y+h) >= canvas_height) {
                    h = canvas_height-y;
                    sh = canvas_height-y;
                }
            }

            if(w > 0 && h > 0) {
                if(view_is_zoomed()) {
                    // enlarge source texture coordinates to hide interpolated pixel seams at the edges
                    var incr = gamedata['client']['view_zoom_tile_border'][view_zoom >= 1.0 ? 1 : 0];
                    sx += incr/view_zoom;
                    sy += incr/view_zoom;
                    sw -= (2/view_zoom)*incr;
                    sh -= (2/view_zoom)*incr;
                }
                image.drawSubImage([sx,sy],[sw,sh],[x,y],[w,h]);
                if(PLAYFIELD_DEBUG && w>2 && h>2) {
                    ctx.strokeStyle = debug_color;
                    ctx.strokeRect(x+1,y+1,w-2,h-2);
                    ctx.fillText('j='+j.toString()+' i='+i.toString()+' '+state, x+13, y+17);
                }
            }
        }
    }
    ctx.restore(); // redo playfield transform
    return true;
}

/** @param {!Base.Base} base
    @param {boolean} is_home_base
    @param {boolean} is_friendly_base
    @param {string} assetname */
Backdrop.draw_whole = function(base, is_home_base, is_friendly_base, assetname) {
    var ncells = base.ncells();
    var backdrop_sprite = /** @type {!GameArt.Sprite} */ (GameArt.assets[assetname].states[is_home_base ? 'home':'other']);
    if(!backdrop_sprite.wh) { throw Error('backdrop sprite needs specific dimensions'); }

    var backdrop_image = backdrop_sprite.images[0];

    if(!backdrop_image.data_loaded || !base) {
        // start it loading
        backdrop_image.prep_for_draw();
        // but draw blank for now
        Backdrop.draw_blank();
        return false;
    } else {
        ctx.save();
        set_default_canvas_transform(ctx); // undo playfield transform

        // pixel coordinates of the subpart of the whole image that will land at the top left of the canvas
        // = 0.5*sprite.wh + view_pos + (1/zoom)*(-canvas_half)
        var start = vec_add(vec_scale(0.5, backdrop_sprite.wh), vec_add(view_pos, vec_scale(1/view_zoom, [-canvas_width_half, -canvas_height_half])));

        // add source pixel size of the subpart of the whole image that will fill the canvas
        var end = vec_add(start, vec_scale(1/view_zoom, [canvas_width, canvas_height]));

        var dest_area = [canvas_width, canvas_height];
        if(view_is_zoomed()) {
            // draw one extra pixel at right/bottom to avoid seams
            dest_area = vec_add(dest_area, [1/view_zoom,1/view_zoom]);
        } else {
            start = vec_floor(start);
            end = vec_floor(end);
        }
        backdrop_image.drawSubImage_clipped(start, vec_sub(end, start), [0,0], dest_area);

        // if the image doesn't fill the entire canvas, draw black borders around the edges
        // with optional gradient fringe
        var fringe = gamedata['client']['backdrop_whole_fringe']*view_zoom;
        var edges = [];
        if(start[0] < 0) {
            edges.push({x:0, y:0, w:-start[0]*view_zoom, h:dest_area[1], v:[1,0]});
        }
        if(start[1] < 0) {
            edges.push({x:0, y:0, w:dest_area[0], h:-start[1]*view_zoom, v:[0,1]});
        }
        if(end[0] >= backdrop_sprite.wh[0]) {
            var w = (end[0]-backdrop_sprite.wh[0])*view_zoom, h = dest_area[1];
            edges.push({x:dest_area[0]-w-0.5, y:0, w:w, h:dest_area[1], v:[-1,0]});
        }
        if(end[1] >= backdrop_sprite.wh[1]) {
            var h = (end[1]-backdrop_sprite.wh[1])*view_zoom;
            edges.push({x:0, y:dest_area[1]-h-0.5, w:dest_area[0], h:h, v:[0,-1]});
        }

        if(edges.length > 0) {
            ctx.fillStyle = '#000000';
            goog.array.forEach(edges, function(edge) {
                ctx.fillRect(Math.floor(edge.x), Math.floor(edge.y), Math.floor(edge.w+0.5), Math.floor(edge.h+0.5));
            });
            goog.array.forEach(edges, function(edge) {
                // firefox doesn't do a great job of clipping very thin gradients, so don't draw if too narrow
                if(fringe > 0 && Math.min(edge.w, edge.h) >= 2) {
                    var grd = ctx.createLinearGradient(Math.floor(edge.x+edge.v[0]*(edge.v[0] > 0 ? edge.w : 0)),
                                                       Math.floor(edge.y+edge.v[1]*(edge.v[1] > 0 ? edge.h : 0)),
                                                       Math.floor(edge.x+edge.v[0]*(edge.v[0] > 0 ? (edge.w+fringe) : fringe)),
                                                       Math.floor(edge.y+edge.v[1]*(edge.v[1] > 0 ? (edge.h+fringe) : fringe)));
                    grd.addColorStop(0, 'rgba(0,0,0,1)');
                    grd.addColorStop(1, 'rgba(0,0,0,0)');
                    ctx.fillStyle = grd;
                    //ctx.fillStyle = '#00ff00'; // for debugging

                    ctx.fillRect(Math.floor(edge.x+edge.v[0]*(edge.v[0] > 0 ? edge.w : fringe)),
                                 Math.floor(edge.y+edge.v[1]*(edge.v[1] > 0 ? edge.h : fringe)),
                                 Math.floor((1-Math.abs(edge.v[0]))*edge.w + Math.abs(edge.v[0])*fringe + 1.5),
                                 Math.floor((1-Math.abs(edge.v[1]))*edge.h + Math.abs(edge.v[1])*fringe + 1.5));
                }
            });
        }

        ctx.restore(); // redo playfield transform
    }
    return true;
}

/** @param {boolean} is_home_base
    @param {boolean} is_friendly_base
    @param {string} assetname */
Backdrop.draw_simple = function(is_home_base, is_friendly_base, assetname) {
    var backdrop_sprite = /** @type {!GameArt.Sprite} */ (GameArt.assets[assetname].states[is_home_base ? 'home':'other']);
    if(!backdrop_sprite.wh) { throw Error('backdrop sprite needs specific dimensions'); }

    var backdrop_image = backdrop_sprite.images[0];

    if(!backdrop_image.data_loaded) {
        // start it loading
        backdrop_image.prep_for_draw();
        // but draw blank for now
        Backdrop.draw_blank();
        return false;
    } else {
        ctx.save();
        set_default_canvas_transform(ctx); // undo playfield transform
        var tilesize = view_is_zoomed() ? vec_scale(view_zoom, backdrop_sprite.wh) : backdrop_sprite.wh;
        var start = [view_pos[0]*view_zoom - canvas_width_half, view_pos[1]*view_zoom - canvas_height_half];
        var end = [start[0]+canvas_width, start[1]+canvas_height];

        var istart = Math.floor(start[1]/tilesize[1]);
        var iend = Math.floor(end[1]/tilesize[1]);
        var jstart =  Math.floor(start[0]/tilesize[0]);
        var jend = Math.floor(end[0]/tilesize[0]);

        for(var i = istart; i <= iend; i++) {
            for(var j = jstart; j <= jend; j++) {
                var x = Math.floor(j*tilesize[0] - start[0]);
                var y = Math.floor(i*tilesize[1] - start[1]);
                var w = tilesize[0], h = tilesize[1];
                var sx = 0, sy = 0, sw = backdrop_sprite.wh[0], sh = backdrop_sprite.wh[1];

                // perform clipping
                if(!view_is_zoomed()) {
                    // left
                    if(x < 0) {
                        sx = -x;
                        sw += x;
                        w += x;
                        x = 0;
                    }
                    // top
                    if(y < 0) {
                        sy = -y;
                        sh += y;
                        h += y;
                        y = 0;
                    }
                    // right
                    if((x+w) >= canvas_width) {
                        w = canvas_width-x;
                        sw = w;
                    }
                    // bottom
                    if((y+h) >= canvas_height) {
                        h = canvas_height-y;
                        sh = h;
                    }
                }
                if(w > 0 && h > 0) {
                    if(view_is_zoomed()) {
                        // draw one extra pixel at left/bottom to avoid seams
                        w += 1/view_zoom; h += 1/view_zoom;
                    }
                    backdrop_image.drawSubImage([sx,sy],[sw,sh],[x,y],[w,h]);
                }
            }
        }
        ctx.restore(); // redo playfield transform
    }
    return true;
}

/** @param {Base.Base|null} base
    @param {!GameObjectCollection.GameObjectCollection} cur_objects
    @param {boolean} is_home_base
    @param {boolean} is_friendly_base
    @param {boolean} want_scenery */
Backdrop.draw = function(base, cur_objects, is_home_base, is_friendly_base, want_scenery) {
    var climate_data = (base && goog.object.getCount(base.base_climate_data) > 0 ?
                        base.base_climate_data : gamedata['climates'][gamedata['default_climate']]);
    var ncells = (base ? base.ncells() : null);

    if(('backdrop_whole' in climate_data) && base && ncells && (ncells[0].toString()+'x'+ncells[1].toString() in climate_data['backdrop_whole'])) {
        var drawn = Backdrop.draw_whole(base, is_home_base, is_friendly_base, climate_data['backdrop_whole'][ncells[0].toString()+'x'+ncells[1].toString()]);
        if(drawn && want_scenery) { Backdrop.draw_scenery(base, cur_objects); }
        if(ncells && (!drawn || PLAYFIELD_DEBUG)) { Backdrop.draw_area_bounds(ncells); }
    } else if('backdrop_tiles' in climate_data && base && (SPFX.detail >= 2)) {
        var drawn = Backdrop.draw_tiled(base, is_home_base, is_friendly_base, climate_data['backdrop_tiles']);
        if(drawn && want_scenery) { Backdrop.draw_scenery(base, cur_objects); }
        if(ncells && (!drawn || PLAYFIELD_DEBUG)) { Backdrop.draw_area_bounds(ncells); }
    } else {
        var drawn = Backdrop.draw_simple(is_home_base, is_friendly_base, climate_data['backdrop']);
        if(drawn && want_scenery && base) { Backdrop.draw_scenery(base, cur_objects); }
        if(ncells) { Backdrop.draw_area_bounds(ncells); }
    }

    if(base && ((!is_home_base && !is_friendly_base) || player.is_cheater) &&
       /* base.deployment_buffer && */
       selection.unit !== player.virtual_units["DEPLOYER"]) {
        base.draw_base_perimeter('pre_deploy');
    }
};
