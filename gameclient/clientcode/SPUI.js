goog.provide('SPUI');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.object');
goog.require('GameArt');
goog.require('SPText');
goog.require('PortraitCache');
goog.require('Dripper');
goog.require('SPFB'); // only for SPUI.FriendPortrait

/** @const */ SPUI.LEFT_MOUSE_BUTTON = 0;
/** @const */ SPUI.RIGHT_MOUSE_BUTTON = 2;

// SPUI.Font - a font of a particular size and style

// do not call directly - use SPUI.make_font() instead
/** @constructor */
SPUI.Font = function(size, leading, style) {
    // vertical height of text font, in pixels
    this.size = size;

    // vertical spacing between lines of text, in pixels
    // (usually slightly more than 'size')
    this.leading = leading;

    // "normal", "bold"
    this.style = style;
};

// return HTML5 representation of this font in string form
SPUI.Font.prototype.str = function() {
    var ret = "sans-serif";
    ret = this.size.toString() + "px " + ret;
    if(this.style != "normal") {
        ret = this.style + " " + ret;
    }
    return ret;
};

// return the pixel width and height of a text string (multi-line OK)
// NOTE: You must first set the context's font to this.str() before calling!
SPUI.Font.prototype.measure_string = function(str) {
    var ret = [0,0];
    if(!str || str.length < 1) { return ret; }
    var lines = str.split('\n');
    if(!lines || lines.length < 1) { return ret; }
    for(var i = 0; i < lines.length; i++) {
        var dims = SPUI.ctx.measureText(lines[i]);
        ret[0] = Math.max(ret[0], dims.width);
        ret[1] += this.leading;
    }
    return ret;
}

// keep a global table of unique fonts so that instances can be shared
SPUI.font_table = {};

// get a Font instance with this size, leading, and style
SPUI.make_font = function(size, leading, style) {

    // for "thick" items, use "bold" instead of "normal" if the browser's native gamma is not thick enough
    if(style === "thick") {
        style = (SPUI.fonts_are_thick ? "normal": "bold");
    }

    if(SPUI.low_fonts) {
        style = "normal";
        // use only odd font sizes
        var new_size = size;
        if((size%2)==0) {
            new_size = size-1;
        }
        if(new_size > 19) { new_size = 19; }
        size = new_size;
    }

    var key = [size, leading, style];
    if(key in SPUI.font_table) {
        return SPUI.font_table[key];
    }
    var font = new SPUI.Font(size, leading, style);
    SPUI.font_table[key] = font;
    //console.log("ADDING FONT "+key.toString()+" HERE "+(size%1).toString());
    return font;
};


// font used for debug graphics and other stuff rendered on the play field
SPUI.desktop_font = null;

SPUI.init = function(canvas, ctx, options) {
    if(!options) { options = {}; }

    SPUI.canvas = canvas;
    SPUI.canvas_width = 100;
    SPUI.canvas_height = 100;
    SPUI.ctx = ctx;
    SPUI.time = 0;
    SPUI.keyboard_focus = null;
    SPUI.fonts_are_thick = options.fonts_are_thick || false;
    SPUI.low_fonts = options.low_fonts || false;
    SPUI.desktop_font = SPUI.make_font(14, 17, 'thick');
};

SPUI.on_resize = function(new_width, new_height) {
    SPUI.canvas_width = new_width;
    SPUI.canvas_height = new_height;
    SPUI.root.wh = [new_width, new_height];
    SPUI.root.on_resize();
};

// range is 0-1, linear light
/** @constructor
 * @param {number} r
 * @param {number} g
 * @param {number} b
 * @param {number=} a
 */
SPUI.Color = function(r,g,b,a) {
    if(typeof(a) == 'undefined') { a = 1; }
    this.r = r; this.g = g; this.b = b; this.a = a;
};

SPUI.Color.mix = function(x, y, a) {
    return new SPUI.Color(x.r+a*(y.r-x.r),
                          x.g+a*(y.g-x.g),
                          x.b+a*(y.b-x.b),
                          x.a+a*(y.a-x.a));
};

SPUI.make_colorv = function(col) { return new SPUI.Color(col[0], col[1], col[2], (col.length >= 4 ? col[3] : 1)); };

SPUI.Color.prototype.str = function() {
    // gamma-encode values passed to HTML Canvas renderer - return as 'rgba(255,255,255,1)' string
    var gamma_r = Math.sqrt(this.r), gamma_g = Math.sqrt(this.g), gamma_b = Math.sqrt(this.b), gamma_a = Math.sqrt(this.a);
    return 'rgba('+Math.floor(255*gamma_r).toString()+','+Math.floor(255*gamma_g).toString()+','+Math.floor(255*gamma_b).toString()+','+this.a.toString()+')';
};
SPUI.Color.prototype.hex_comp = function(comp) {
    var ret = comp.toString(16);
    if(ret.length < 2) {
        ret = '0'+ret;
    }
    return ret;
};
SPUI.Color.prototype.hex = function() {
    // gamma-encode values passed to HTML Canvas renderer - return as 'ffffff' hex string
    var gamma_r = Math.sqrt(this.r), gamma_g = Math.sqrt(this.g), gamma_b = Math.sqrt(this.b), gamma_a = Math.sqrt(this.a);
    return this.hex_comp(Math.floor(255*gamma_r))+this.hex_comp(Math.floor(255*gamma_g))+this.hex_comp(Math.floor(255*gamma_b));
};

SPUI.default_text_color = new SPUI.Color(1,1,1,1);
SPUI.black_color = new SPUI.Color(0,0,0,1);
SPUI.disabled_text_color = new SPUI.Color(0.4,0.4,0.4,1);
SPUI.error_text_color = new SPUI.Color(1,0,0,1);
SPUI.warning_text_color = new SPUI.Color(1,0.33,0,1);
SPUI.good_text_color = new SPUI.Color(0.2,1,0.2,1);
SPUI.modal_bg_color = new SPUI.Color(0,0,0,0.5);

// Element
// base class for all SPUI widgets

/** @constructor */
SPUI.Element = function() {
    /** @type {?SPUI.Element} */
    this.parent = null;
    this.xy = [0,0];
    this.wh = [0,0];
};

// in reflow(), set and return your own width/height
// then the CALLER will set your x/y
SPUI.Element.prototype.reflow = function() { return [0,0]; };
SPUI.Element.prototype.destroy = function() {};
SPUI.Element.prototype.on_resize = function() {};

// for debugging only - return a string that represents this widget's "address" within the scene graph
SPUI.Element.prototype.get_address = function() {
    if(this === SPUI.root) {
        return 'SPUI.root';
    } else if(!this.parent) {
        return 'orphan';
    } else if(!this.parent.widgets) {
        return 'non-dialog-parent';
    } else {
        for(var name in this.parent.widgets) {
            if(this.parent.widgets[name] === this) {
                return this.parent.get_address()+'.'+name;
            }
        }
        return 'not-found-in-parent-widgets';
    }
};

SPUI.Element.prototype.get_absolute_xy = function() {
    var pos = [0,0];
    for(var p = this; p; p = p.parent) {
        pos[0] += p.xy[0]; pos[1] += p.xy[1];
    }
    return pos;
};

SPUI.Element.prototype.is_frontmost = function() { return false; };

// Container
// an Element that contains child Elements

/** @constructor
  * @extends SPUI.Element
  */
SPUI.Container = function() {
    goog.base(this);
    this.children = [];
    this.clip_children = true;
    this.transparent_to_mouse = false;

    // SPUI.time when the mouse entered the container, -1 if never
    this.mouse_enter_time = -1;
};

goog.inherits(SPUI.Container, SPUI.Element);

SPUI.Container.prototype.add = function(elem) {
    this.children.push(elem);
    elem.parent = this;
    if(this.parent != null) {
        this.parent.reflow();
    } else {
        this.reflow();
    }
    return elem;
};

SPUI.Container.prototype.get_z_index = function(elem) {
    for(var i = 0; i < this.children.length; i++) {
        if(this.children[i] === elem) { return i; }
    }
    return -1;
};

SPUI.Container.prototype.add_under = function(elem) {
    this.children.unshift(elem);
    elem.parent = this;
    return elem;
};

SPUI.Container.prototype.add_at_index = function(elem, i) {
    this.children.splice(i, 0, elem);
    elem.parent = this;
    return elem;
};

// add a new child before other child "bef"
// if "bef" is null, add at end of list.
SPUI.Container.prototype.add_before = function(bef, elem) {
    if(!bef) {
        this.add(elem); return;
    }

    for(var i = 0; i < this.children.length; i++) {
        var p = this.children[i];
        if(p === bef) {
            return this.add_at_index(elem, i);
        }
    }
    throw Error("child not found (add_before) "+this.get_address()+" bef "+bef.get_address()+" elem "+elem.get_address());
};
SPUI.Container.prototype.add_after = function(bef, elem) {
    for(var i = 0; i < this.children.length; i++) {
        var p = this.children[i];
        if(p === bef) {
            return this.add_at_index(elem, i+1);
        }
    }
    throw Error("child not found (add_after) "+this.get_address()+" bef "+bef.get_address()+" elem "+elem.get_address());
};

SPUI.Container.prototype.remove = function(elem) {
    var p = this.unparent(elem);
    p.destroy();
};

// like remove, but do not destroy the element
SPUI.Container.prototype.unparent = function(elem) {
    for(var i = 0; i < this.children.length; i++) {
        var p = this.children[i];
        if(p === elem) {
            p.parent = null;
            this.children.splice(i,1);
            return elem;
        }
    }
    throw Error("child not found (unparent) "+this.get_address()+" elem "+elem.get_address());
};

SPUI.Container.prototype.destroy = function() {
    goog.base(this, 'destroy');
    for(var i = 0; i < this.children.length; i++) {
        var p = this.children[i];
        p.parent = null;
        p.destroy();
    }
    this.children = [];
};

SPUI.Container.prototype.clear = function() {
    this.destroy();
};

SPUI.Container.prototype.reflow = function() {
    for(var i = 0; i < this.children.length; i++) {
        this.children[i].reflow();
    }
    return [0,0];
};

SPUI.Container.prototype.onleave = function() {
    this.mouse_enter_time = -1;
    for(var i = 0; i < this.children.length; i++) {
        if(this.children[i].onleave) { this.children[i].onleave(); }
    }
};

SPUI.Container.prototype.do_draw = function(offset) {}

SPUI.Container.prototype.draw = function(offset) {
    this.do_draw(offset);
    for(var i = 0; i < this.children.length; i++) {
        this.children[i].draw([offset[0]+this.xy[0],offset[1]+this.xy[1]]);
    }
};

SPUI.Container.prototype.on_mousedown = function(uv, offset, button) {
    if(!this.clip_children ||
       (uv[0] >= this.xy[0]+offset[0] &&
        uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
        uv[1] >= this.xy[1]+offset[1] &&
        uv[1]  < this.xy[1]+offset[1]+this.wh[1])) {
        // click is inside the area
        // perform search in reverse as a hack to fake z-order hiding

        var my_offset = [offset[0]+this.xy[0],offset[1]+this.xy[1]];
        for(var i = this.children.length-1; i >= 0; i--) {
            if(this.children[i].on_mousedown &&
               this.children[i].on_mousedown(uv, my_offset, button)) {
                //console.log("MY CHILD GOT DOWN - "+this.children[i].get_address()+ " CHILD OF "+this.get_address());
                return true;
            }
        }
        // clicked inside of client area but not on a child element
        if(this.transparent_to_mouse) {
            return false;
        } else {
            //console.log("I GOT DOWN - "+this.get_address());
            return true;
        }
    }
    return false;
};

SPUI.Container.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.clip_children ||
       (uv[0] >= this.xy[0]+offset[0] &&
        uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
        uv[1] >= this.xy[1]+offset[1] &&
        uv[1]  < this.xy[1]+offset[1]+this.wh[1])) {
        // click is inside the area
        // perform search in reverse as a hack to fake z-order hiding

        var my_offset = [offset[0]+this.xy[0],offset[1]+this.xy[1]];
        for(var i = this.children.length-1; i >= 0; i--) {
            if(this.children[i].on_mouseup &&
               this.children[i].on_mouseup(uv, my_offset, button)) {
                //console.log("MY CHILD GOT UP - "+this.children[i].get_address()+ " CHILD OF "+this.get_address());
                return true;
            }
        }
        // clicked inside of client area but not on a child element
        if(this.transparent_to_mouse) {
            return false;
        } else {
            //console.log("I GOT UP - "+this.get_address());
            return true;
        }
    }
    return false;
};

SPUI.Container.prototype.on_mousewheel = function(uv, offset, delta) {
    if(!this.clip_children ||
       (uv[0] >= this.xy[0]+offset[0] &&
        uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
        uv[1] >= this.xy[1]+offset[1] &&
        uv[1]  < this.xy[1]+offset[1]+this.wh[1])) {
        // click is inside the area
        // perform search in reverse as a hack to fake z-order hiding
        for(var i = this.children.length-1; i >= 0; i--) {
            if(this.children[i].on_mousewheel &&
               this.children[i].on_mousewheel(uv, [offset[0]+this.xy[0],offset[1]+this.xy[1]], delta)) {
                return true;
            }
        }
        // inside of client area but not on a child element
        // note: never interfere with mousewheel events by default
        if(1 || this.transparent_to_mouse) {
            return false;
        } else {
            return true;
        }
    }
    return false;
};

SPUI.Container.prototype.on_mousemove = function(uv, offset) {
    if(!this.clip_children ||
       (uv[0] >= this.xy[0]+offset[0] &&
        uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
        uv[1] >= this.xy[1]+offset[1] &&
        uv[1]  < this.xy[1]+offset[1]+this.wh[1])) {
        // mouse is inside the area

        if(this.transparent_to_mouse) {
            // use child elements for hover test
            var found = false;
            for(var i = this.children.length-1; i >= 0; i--) {
                var child = this.children[i];
                if(child.show &&
                   uv[0] >= this.xy[0]+offset[0]+child.xy[0] &&
                   uv[0]  < this.xy[0]+offset[0]+child.xy[0]+child.wh[0] &&
                   uv[1] >= this.xy[1]+offset[1]+child.xy[1] &&
                   uv[1]  < this.xy[1]+offset[1]+child.xy[1]+child.wh[1]) {
                    if(this.mouse_enter_time < 0) {
                        this.mouse_enter_time = SPUI.time;
                    }
                    found = true;
                    break;
                }
            }
            if(!found) {
                this.onleave();
            }
        } else {
            if(this.mouse_enter_time < 0) {
                this.mouse_enter_time = SPUI.time;
            }
        }

        // perform search of child elements in reverse as a hack to fake z-order hiding
        var ret = false;
        for(var i = this.children.length-1; i >= 0; i--) {
            if(this.children[i].show &&
               this.children[i].on_mousemove &&
               this.children[i].on_mousemove(uv, [offset[0]+this.xy[0],offset[1]+this.xy[1]])) {
                // note: continue iterating even when a child handles the event, because other children might want to run onleave()
                ret = true;
            }
        }
        if(ret) { return ret; }

        // moved inside of client area but not on a child element
        if(this.transparent_to_mouse) {
            return false;
        } else {
            return true;
        }
    } else {
        this.onleave();
    }
    return false;
};

SPUI.Container.prototype.on_resize = function() {
    for(var i = this.children.length-1; i >= 0; i--) {
        if(this.children[i].on_resize) {
            this.children[i].on_resize();
        }
    }
};

// parent of all screen UI elements
SPUI.root = new SPUI.Container();
SPUI.root.xy = [0,0]; SPUI.root.wh = [99999,99999];
SPUI.root.transparent_to_mouse = true;

// dripper maintained by SPUI code that is called by main.js
SPUI.dripper = new Dripper.Dripper(null, -1, -1);

// call this function to draw the entire UI
SPUI.draw_all = function() {
    SPUI.root.draw([0,0]);
};
SPUI.draw_active_tooltip = function() {
    if(SPUI.active_tooltip) {
        SPUI.active_tooltip.draw([0,0]);
    }
};

// VLayout

/** @constructor
  * @extends SPUI.Container
  */
SPUI.VLayout = function() {
    goog.base(this);
    this.pad = 5;
};

goog.inherits(SPUI.VLayout, SPUI.Container);

SPUI.VLayout.prototype.reflow = function() {
    var max_w = 0;
    var total_h = this.pad;
    var y = this.pad;
    for(var i = 0; i < this.children.length; i++) {
        var child = this.children[i];
        var child_wh = child.reflow();
        child.xy = [0,y];
        total_h += child_wh[1] + this.pad;
        y += child_wh[1] + this.pad;
        max_w = Math.max(max_w, child_wh[0]);
    }

    var ret = [max_w, total_h];
    this.wh = ret;
    return ret;
};

// Text

/** @constructor
  * @extends SPUI.Element
  * @param {null|string|function(): string} str can be either literal or a function
  * @param {Object=} props
  */
SPUI.Text = function(str, props) {
    goog.base(this);
    this.str = str;
    this.color = (props && props['color']) || SPUI.default_text_color;
    this.pad = (props && props['pad']) || [20,3];
    this.font = (props && props['font']) || SPUI.desktop_font;
};

goog.inherits(SPUI.Text, SPUI.Element);

SPUI.Text.prototype.render_str = function () {
    if(!this.str) {
        return null;
    } else if(typeof this.str == 'string') {
        return this.str;
    } else {
        // assume this.str is a function
        return this.str();
    }
};

SPUI.Text.prototype.draw = function(offset) {
    if(this.str === null) {
        return;
    }

    var s = this.render_str();
    if(!s) { return; }

    SPUI.ctx.save();
    SPUI.ctx.font = this.font.str();
    // drop shadow
    SPUI.ctx.fillStyle = 'rgba(0,0,0,'+this.color.a.toString()+')';//SPUI.black_color.str();
    SPUI.ctx.fillText(s, this.xy[0]+offset[0]+this.pad[0]+1, this.xy[1]+offset[1]+this.pad[1]+this.font.size+1);
    // main text
    SPUI.ctx.fillStyle = this.color.str();
    SPUI.ctx.fillText(s, this.xy[0]+offset[0]+this.pad[0], this.xy[1]+offset[1]+this.pad[1]+this.font.size);
    SPUI.ctx.restore();
};

SPUI.Text.prototype.reflow = function() {
    var ret;
    if(this.str === null) {
        ret = [0, this.font.size+4*this.pad[1]];
    } else {
        var dims = SPUI.ctx.measureText(this.render_str());
        ret = [dims.width + 2*this.pad[0], this.font.size + 4*this.pad[1]];
    }
    this.wh = ret;
    return ret;
};

// ErrorLog

/** @constructor
  * @extends SPUI.VLayout
  */
SPUI.ErrorLog = function(maxlines) {
    goog.base(this);
    this.maxlines = maxlines;
    this.pad = 0;
    var my_font = SPUI.make_font(20, 24, 'thick');
    for(var i = 0; i < this.maxlines; i++) {
        var text = new SPUI.Text(null, {'font': my_font});
        text.pad = [0,2];
        this.add(text);
    }
    this.transparent_to_mouse = true;
};

goog.inherits(SPUI.ErrorLog, SPUI.VLayout);

SPUI.ErrorLog.prototype.msg = function(str, color) {
    for(var i = 0; i < this.maxlines-1; i++) {
        this.children[i].str = this.children[i+1].str;
        this.children[i].color = this.children[i+1].color;
        this.children[i].time = this.children[i+1].time;
    }
    this.children[this.maxlines-1].str = str;
    this.children[this.maxlines-1].color = color;
    this.children[this.maxlines-1].time = SPUI.time;

    this.reflow();
};

SPUI.ErrorLog.prototype.draw = function(offset) {
    // perform color fading
    for(var i = 0; i < this.maxlines; i++) {
        var child = this.children[i];
        if(child.str === null) {
            continue;
        }

        var elapsed = SPUI.time - child.time;
        var alpha;
        if(elapsed < 3) {
            alpha = 1;
        } else {
            alpha = 1 - (elapsed-3)/3;
        }

        if(alpha <= 0) {
            child.str = '';
        } else {
            child.color.a = alpha;
        }
    }

    goog.base(this, 'draw', offset);
};


//
// PARAMETERIZED DIALOG SYSTEM
//

SPUI.instantiate_widget = function(wdata) {
    var widget;
    if(wdata['kind'] === 'ActionButton') {
        widget = new SPUI.ActionButton(wdata);
    } else if(wdata['kind'] === 'TextField') {
        widget = new SPUI.TextField(wdata);
    } else if(wdata['kind'] === 'RichTextField') {
        widget = new SPUI.RichTextField(wdata);
    } else if(wdata['kind'] === 'ScrollingTextField') {
        widget = new SPUI.ScrollingTextField(wdata);
    } else if(wdata['kind'] === 'TextInput') {
        widget = new SPUI.TextInput(wdata);
    } else if(wdata['kind'] === 'StaticImage') {
        widget = new SPUI.StaticImage(wdata);
    } else if(wdata['kind'] === 'FriendPortrait') {
        widget = new SPUI.FriendPortrait(wdata);
    } else if(wdata['kind'] === 'FriendIcon') {
        widget = new SPUI.FriendIcon(wdata);
    } else if(wdata['kind'] === 'SpellIcon') {
        widget = new SPUI.SpellIcon(wdata);
    } else if(wdata['kind'] === 'CooldownClock') {
        widget = new SPUI.CooldownClock(wdata);
    } else if(wdata['kind'] === 'SolidRect') {
        widget = new SPUI.SolidRect(wdata);
    } else if(wdata['kind'] === 'Line') {
        widget = new SPUI.Line(wdata);
    } else if(wdata['kind'] === 'ProgressBar') {
        widget = new SPUI.ProgressBar(wdata);
    } else if(wdata['kind'] === 'Dialog') {
        widget = new SPUI.Dialog(gamedata['dialogs'][wdata['dialog']], wdata);
        // when Dialogs are spawned as a widget of a parent dialog, do
        // not prevent mouse events from reaching sibling widgets
        widget.transparent_to_mouse = true;
    } else if(wdata['kind'] === 'RegionMap') {
        widget = new RegionMap.RegionMap(wdata);
    } else {
        throw Error('unknown widget kind '+wdata['kind']);
    }
    return widget;
};

// return suffixed name for array widgets, like "button0,1"
/** @param {string} array_name
 *  @param {Array.<number>} array_dims
 *  @param {Array.<number>} xy
 */
SPUI.get_array_widget_name = function(array_name, array_dims, xy) {
    if(array_dims[0] > 1 && array_dims[1] > 1) {
        return array_name+xy[0].toString()+','+xy[1].toString();
    } else if(array_dims[0] > 1) {
        if(xy[1] != 0) { throw Error('array '+array_name+' element out of bounds'); }
        return array_name+xy[0].toString();
    } else if(array_dims[1] > 1) {
        if(xy[0] != 0) { throw Error('array '+array_name+' element out of bounds'); }
        return array_name+xy[1].toString();
    } else {
        return array_name;
    }
};

// Create a dialog
// 'data': pass the member of gamedata['dialogs'] for the dialog you want to create
// e.g. gamedata['dialogs']['upgrade_dialog']

/** @constructor
  * @extends SPUI.Container
  * @param {Object} data reference to gamedata['dialogs']
  * @param {Object=} instance_props override data with per-instance key/vals
  */
SPUI.Dialog = function(data, instance_props) {
    if(!instance_props) { instance_props = {}; }

    goog.base(this);

    if('xy' in instance_props) {
        this.xy = [instance_props['xy'][0], instance_props['xy'][1]];
    }
    this.clip_to = data['clip_to'] || instance_props['clip_to'] || null;

    if('transparent_to_mouse' in instance_props) {
        this.transparent_to_mouse = instance_props['transparent_to_mouse'];
    } else if('transparent_to_mouse' in data) {
        this.transparent_to_mouse = data['transparent_to_mouse'];
    } else {
        this.transparent_to_mouse = false; // XXX may want to change the default later
    }

    // stash a reference to data in case we need it later
    this.data = data;

    // pixel width/height are hard-coded in gamedata.json
    this.wh = [data['dimensions'][0], data['dimensions'][1]];

    this.layout = ('layout' in instance_props ? instance_props['layout'] : null);

    // note: only works when children do not set their own alphas
    this.alpha = 1;

    if('clip_children' in data) { this.clip_children = data['clip_children']; }

    // obtain reference to the GameArt.Image for this dialog's background image (loaded by the GameArt system)
    if(('bg_image' in data) && data['bg_image'] != '') {
        this.bg_image = GameArt.assets[data['bg_image']].states['normal'];
    } else {
        this.bg_image = null;
    }

    this.bg_image_offset = ('bg_image_offset' in data ? data['bg_image_offset'] : [0,0]);

    // instantiate widgets

    // keep references to the widgets in a dictionary indexed by widget name
    // this is in addition to the 'children' array from SPUI.Container, and
    // is necessary to allow JavaScript code to fiddle with specific widgets

    this.widgets = {};
    for(var wname in data['widgets']) {
        var wdata = data['widgets'][wname];
        if('array' in wdata) {
            for(var y = 0; y < wdata['array'][1]; y++) {
                for(var x = 0; x < wdata['array'][0]; x++) {
                    var nam = wname;
                    if(wdata['array'][0] > 1) {
                        nam += x.toString();
                    }
                    if(wdata['array'][1] > 1) {
                        if(wdata['array'][0] > 1) {
                            nam += ',';
                        }
                        nam += y.toString();
                    }
                    var widget = SPUI.instantiate_widget(wdata);
                    this.add(widget);
                    this.widgets[nam] = widget;
                }
            }

            // set initial position for array widgets
            this.update_array_widget_positions(wname);

        } else {
            var widget = SPUI.instantiate_widget(wdata);
            this.add(widget);
            this.widgets[wname] = widget;
        }
    }

    if('default_button' in data) {
        this.default_button = this.widgets[data['default_button']];
    } else {
        this.default_button = null;
    }

    this.show = (('show' in instance_props) ? instance_props['show'] : true);

    this.modal = false;
    this.centered = null;

    this.transform = null;

    // optional function that is called right before dialog draws itself
    // e.g. to update values in real time
    this.ondraw = null;
    this.afterdraw = null;
    this.on_destroy = null;

    // this is a place for the caller to stash anything it wants
    this.user_data = {};
};

goog.inherits(SPUI.Dialog, SPUI.Container);

/** Update local xy positions, and optionally visibility, of child array widgets.
 * Any widget that has an x or y "array_offset" equal to -1 will get an auto-computed
 * offset based on "array_max_dimensions", and its visibility will be set to show or hide
 * automatically, all based on element_count.
 *
 * If element_count is less than the entire x*y array size, then hide
 * widgets beyond this element (where element 0 is at the top-right
 * and we count left-to-right then top-to-bottom).
 *
 * @param {string} array_name name prefix for the widget array
 * @param {number=} element_count (optional) number of widgets to display.
 */
SPUI.Dialog.prototype.update_array_widget_positions = function(array_name, element_count) {
    var wdata = this.data['widgets'][array_name];

    // calculate how many elements that we'll be able to fit in each dimension
    var array_dims = wdata['array'].slice(0);
    if(element_count && element_count > 0) {
        element_count = Math.min(element_count, array_dims[0] * array_dims[1]);

        // fill elements starting from the top left corner and going row by row
        array_dims = [Math.min(element_count, array_dims[0]), Math.ceil(element_count / array_dims[0])];
    } else {
        element_count = array_dims[0] * array_dims[1];
    }

    // calculate offsets
    var array_offset = wdata['array_offset'].slice(0);
    var first_element_offset = [0, 0];
    for(var i = 0; i < 2; i++) {
        if(array_offset[i] == -1) { // -1 offset means "automatically compute offset to space widgets nicely"
            array_offset[i] = (wdata['array_max_dimensions'][i] - array_dims[i] * wdata['dimensions'][i]) / array_dims[i] + wdata['dimensions'][i];
            first_element_offset[i] = Math.floor((array_offset[i] - wdata['dimensions'][i]) / 2);
        }
    }

    // update positions and (optionally) visibility
    for(var y = 0; y < wdata['array'][1]; y++) {
        for(var x = 0; x < wdata['array'][0]; x++) {
            var name = SPUI.get_array_widget_name(array_name, wdata['array'], [x,y]);
            var widget = this.widgets[name];

            widget.xy = [wdata['xy'][0] + x * array_offset[0] + first_element_offset[0],
                         wdata['xy'][1] + y * array_offset[1] + first_element_offset[1]];
            widget.array_pos = [x,y];
            if(widget.fixed_tooltip_offset && 'fixed_tooltip_offset' in wdata) {
                widget.fixed_tooltip_offset = [widget.fixed_tooltip_offset[0] + x * array_offset[0] + first_element_offset[0],
                                               widget.fixed_tooltip_offset[1] + y * array_offset[1] + first_element_offset[1]];
            }
            if(widget.clip_to && ('clip_to' in wdata)) {
                widget.clip_to = [widget.clip_to[0] + x * array_offset[0] + first_element_offset[0],
                                  widget.clip_to[1] + y * array_offset[1] + first_element_offset[1],
                                  widget.clip_to[2], widget.clip_to[3]];
            }
        }
    }
}

SPUI.Dialog.prototype.is_visible = function() { return this.parent && this.show; };

SPUI.Dialog.prototype.destroy = function() {
    if(this.on_destroy) { this.on_destroy(this); }
    goog.base(this, 'destroy');
};

SPUI.Dialog.prototype.get_address = function() {
    var ret = 'Dialog';
    if(false && this.user_data['dialog']) {
        ret += '('+this.user_data['dialog']+')';
    } else {
        for(var name in gamedata['dialogs']) {
            if(gamedata['dialogs'][name] === this.data) {
                ret += '('+name+')';
            }
        }
    }
    ret = goog.base(this, 'get_address') + '-'+ret;
    return ret;
};

/** return true if this dialog is the "front-most" dialog, i.e. the deepest-nested
    dialog that has a "modal" flag
    @override
    @return {boolean} */
SPUI.Dialog.prototype.is_frontmost = function() {
    if(!this.modal) { return false; }

    // if any child is a frontmost dialog, then we aren't.
    if(goog.array.some(this.children, function(child) { return child.is_frontmost(); })) { return false; }

    // if any child of the toplevel parent after us is a frontmost dialog, then we aren't either
    // XXXXXX awkward - this has to do with the bad design of install_child_dialog() putting new children into selection.ui.children regardless of depth!
    var p = this.parent;
    var mypath = [this]; // keep track of the entire chain of parents
    while(p.parent && p.parent instanceof SPUI.Dialog) { mypath.push(p); p = p.parent; }
    var found = false;
    for(var i = 0; i < p.children.length; i++) {
        var sib = p.children[i];
        if(goog.array.contains(mypath, sib)) { found = true; continue; }
        // any subsequent children will override our "frontmost" property
        if(found && sib.is_frontmost()) { return false; }
    }
    return true;
};

SPUI.Dialog.prototype.draw = function(offset) {
    if(this.ondraw) {
        try {
            this.ondraw(this);
        } catch(e) {
            log_exception(e, 'bad ondraw: '+this.get_address());
            return;
        }
    }

    if(!this.show) { return; }

    var draw_offset = offset;

    if(this.transform || this.clip_to || this.alpha < 1) {
        SPUI.ctx.save();
    }

    if(this.alpha < 1) {
        SPUI.ctx.globalAlpha = this.alpha;
    }

    if(this.clip_to) {
        SPUI.ctx.beginPath();
        SPUI.ctx.rect(offset[0]+this.clip_to[0], offset[1]+this.clip_to[1], this.clip_to[2], this.clip_to[3]);
        SPUI.ctx.clip();
    }

    if(this.transform) {
        var t = this.transform;
        SPUI.ctx.transform(t[0], t[1], t[2], t[3], t[4], t[5]);
    }

    goog.base(this, 'draw', draw_offset);

    if(this.afterdraw) { this.afterdraw(this, draw_offset); }

    if(this.transform || this.clip_to || this.alpha < 1) {
        SPUI.ctx.restore();
    }
}

SPUI.Dialog.prototype.do_draw = function(offset) {

    if(this.modal) {
        SPUI.ctx.save();
        set_default_canvas_transform(SPUI.ctx); // zero out the global transform
        SPUI.ctx.fillStyle = SPUI.modal_bg_color.str();
        // hack :)
        if(typeof(this.modal) === 'number') {
            SPUI.ctx.globalAlpha = this.modal;
        }
        SPUI.ctx.fillRect(0,0,SPUI.canvas_width,SPUI.canvas_height);
        SPUI.ctx.restore();
    }
    if(this.bg_image) {
        this.bg_image.draw_topleft([offset[0]+this.xy[0]+this.bg_image_offset[0],
                                    offset[1]+this.xy[1]+this.bg_image_offset[1]],
                                   Math.PI/2, 0);
    }
};

SPUI.Dialog.prototype.reflow = function() { /* not used */ return [0,0]; };

SPUI.Dialog.prototype.in_bounds = function(uv, offset) {
    if(!this.show) { return false; }

    /* do NOT check wh bounding box, this is only for clipping calcs!
    if(!this.modal && this.clip_children) {
        if(uv[0]-offset[0] < this.xy[0] || uv[0]-offset[0] >= this.xy[0]+this.wh[0] ||
           uv[1]-offset[1] < this.xy[1] || uv[1]-offset[1] >= this.xy[1]+this.wh[1]) { return false; }
    }
    */

    if(this.clip_to) {
        //console.log('UV '+uv[0]+','+uv[1]+' OFFSET '+offset[0]+','+offset[1]+' XY '+this.xy[0]+','+this.xy[1]);
        if(uv[0]-offset[0] < this.clip_to[0] ||
           uv[0]-offset[0] >= (this.clip_to[0]+this.clip_to[2]) ||
           uv[1]-offset[1] < this.clip_to[1] ||
           uv[1]-offset[1] >= (this.clip_to[1]+this.clip_to[3])) {
            return false;
        }
        return true;
    }
    return true;
};

SPUI.Dialog.prototype.on_mousedown = function(uv, offset, button) {
    if(!this.in_bounds(uv, offset)) { return false; }
    var ret = goog.base(this, 'on_mousedown', uv, offset, button);
    if(this.modal) {
        ret = true;
    }
    return ret;
};
SPUI.Dialog.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.in_bounds(uv, offset)) { return false; }
    var ret = goog.base(this, 'on_mouseup', uv, offset, button);
    if(this.modal) {
        ret = true;
    }
    return ret;
};

// XXX I'm kind of at a loss as to why tooltips keep showing underneath modal dialogs.
// I think we need to rewrite the entire tooltip path to use hit detection instead of mouse_enter_time
SPUI.Dialog.prototype.on_mousemove = function(uv, offset) {
    if(!this.in_bounds(uv, offset)) { this.onleave(); return false; }
    var ret = goog.base(this, 'on_mousemove', uv, offset);
    if(this.modal) { ret = true; }
    return ret;
};

/** @param {string=} centering_mode */
SPUI.Dialog.prototype.auto_center = function(centering_mode) {
    centering_mode = 'root'; // XXXXXX hack - might need to force this always (region_map_dialog being off-center etc.)
    this.centered = centering_mode;

    var pxy, pwh;
    if(centering_mode != 'root' && this.parent) {
        pxy = this.parent.xy;
        pwh = this.parent.wh;
    } else {
        pxy = [0,0];
        pwh = [SPUI.canvas_width, SPUI.canvas_height];
    }

    var offset;
    if(centering_mode == 'root' && this.parent) {
        offset = this.parent.get_absolute_xy();
    } else {
        offset = [0,0];
    }
    this.xy = [Math.floor((pwh[0] - this.wh[0])/2)-offset[0],
               Math.floor((pwh[1] - this.wh[1])/2)-offset[1]];
};

SPUI.Dialog.prototype.on_resize = function() {
    goog.base(this, 'on_resize');
    if(this.centered) {
        this.auto_center(this.centered);
    }
};

// experimental anchored layout
SPUI.Dialog.prototype.apply_layout = function() {
    goog.object.forEach(this.widgets, function(widget, wname) {
        if(widget.layout) {
            var layout = widget.layout;

            // grow/shrink with parent dialog
            if(layout['hresizable'] || layout['resizable']) {
                widget.wh = [this.wh[0] - this.data['dimensions'][0] + widget.data['dimensions'][0],
                             widget.wh[1]];

            }
            if(layout['vresizable'] || layout['resizable']) {
                widget.wh = [widget.wh[0],
                             this.wh[1] - this.data['dimensions'][1] + widget.data['dimensions'][1]];
            }

            var orig_xy = this.data['widgets'][wname]['xy'];
            if(layout['hjustify'] == 'center') {
                widget.xy = [Math.floor((this.wh[0] - this.data['dimensions'][0])/2) + orig_xy[0],
                             widget.xy[1]];
            } else if(layout['hjustify'] == 'right') {
                widget.xy = [this.wh[0] - this.data['dimensions'][0] + orig_xy[0],
                             widget.xy[1]];
            }

            if(layout['vjustify'] == 'center') {
                widget.xy = [widget.xy[0],
                             Math.floor((this.wh[1] - this.data['dimensions'][1])/2) + orig_xy[1]];
            } else if(layout['vjustify'] == 'bottom') {
                widget.xy = [widget.xy[0],
                             this.wh[1] - this.data['dimensions'][1] + orig_xy[1]];
            }

            if(widget.fixed_tooltip_offset) {
                widget.fixed_tooltip_offset = [widget.data['fixed_tooltip_offset'][0] + (widget.xy[0]-widget.data['xy'][0]),
                                               widget.data['fixed_tooltip_offset'][1] + (widget.xy[1]-widget.data['xy'][1])];
            }
        }
    }, this);
};

// parent class for all Dialog widgets
/** @constructor
  * @extends SPUI.Element
  */
SPUI.DialogWidget = function(data) {
    goog.base(this);

    // stash a reference to data in case we need it later
    this.data = data;

    // get hard-coded coordinates
    this.xy = [data['xy'][0], data['xy'][1]];
    this.wh = [data['dimensions'][0], data['dimensions'][1]];
    this.layout = data['layout'] || null;
    this.array_pos = null; // [x,y] if an array member

    if('show' in data) {
        this.show = (data['show'] ? true : false);
    } else {
        this.show = true;
    }

    // XXX move animation stuff somewhere more sensible
    this.delay = data['delay'] || 0;
    this.start_time = SPUI.time + this.delay;
    this.duration = data['duration'] || -1;
    this.off_after = data['off_after'] || -1;
    this.on_after = data['on_after'] || -1;
    this.sound = data['sound'] || null;
    this.sound_played = false;
    this.transform = data['transform'] || null;

    /** @type {function(SPUI.DialogWidget)|null} optional function that is called right before dialog draws itself
        e.g. to update values in real time */
    this.ondraw = null;
};
goog.inherits(SPUI.DialogWidget, SPUI.Element);

// dialog widgets have hard-coded coordinates, so reflow() is not used
SPUI.DialogWidget.prototype.reflow = function() { /* not used */ return [0,0] };

SPUI.DialogWidget.prototype.draw = function(offset) {
    if(!this.show) { return false; }
    if(this.off_after > 0 && SPUI.time > this.start_time + this.off_after) { return false; }
    if(this.on_after > 0 && SPUI.time < this.start_time + this.on_after) { return false; }
    if(this.ondraw) { this.ondraw(this); }
    if(SPUI.time >= this.start_time && this.sound && !this.sound_played) {
        GameArt.assets[this.sound].states['normal'].audio.play(SPUI.time);
        this.sound_played = true;
    }

    var draw_offset = offset;
    if(this.transform) {
        SPUI.ctx.save();
        var t = this.transform;
        // note: munge the transform and offset so that the transform applies to a coordinate system where this.xy is at [0,0]
        SPUI.ctx.transform(t[0], t[1], t[2], t[3], t[4]+offset[0]+this.xy[0], t[5]+offset[1]+this.xy[1]);
        draw_offset = [-this.xy[0],-this.xy[1]];
    }

    var ret = this.do_draw(draw_offset);
    if(this.transform) {
        SPUI.ctx.restore();
    }
    return ret;
};

SPUI.DialogWidget.prototype.reset_fx = function() {
    this.start_time = SPUI.time + this.delay;
    this.sound_played = false;
};
SPUI.DialogWidget.prototype.fx_time_remaining = function() {
    if(this.duration > 0 && (SPUI.time - this.start_time) < this.duration) {
        return this.duration - (SPUI.time-this.start_time);
    }
    return -1;
};

// TextWidget
// common parent class for text-based widgets

/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.TextWidget = function(data) {
    goog.base(this, data);

    this.num_val = null; // numeric value, optionally used by the animation system for rolling counters

    if('text_color' in data) {
        var col = data['text_color'];
        this.text_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    } else {
        this.text_color = SPUI.default_text_color;
    }

    var text_style = data['text_style'] || "normal";
    var text_size = data['text_size'] || 18;
    var text_leading = data['text_leading'] || (text_size+4);
    this.font = SPUI.make_font(text_size, text_leading, text_style);

    this.text_hjustify = data['text_hjustify'] || "center";
    this.text_vjustify = data['text_vjustify'] || "center";
    this.text_offset = data['text_offset'] || [0,0];
    this.text_scale = 1;
    this.text_angle = data['text_angle'] || 0;
    this.clip_to = data['clip_to'] || null;
    this.drop_shadow = data['drop_shadow'] || false;
    this.resize_to_fit_text = data['resize_to_fit_text'] || false;

    // these fields are updated in measure_text() and only used for drawing
    this.text_xy = null;
    this.text_dimensions = null;

    // note: the caller may over-ride this.str later
    if(data['auto_linebreaking']) {
        this.set_text_with_linebreaking(data['ui_name']);
    } else {
        this.str = data['ui_name'] || '';
    }
};
goog.inherits(SPUI.TextWidget, SPUI.DialogWidget);

// figure out the x,y coordinates to draw the text according to desired justification
// set this.text_xy and this.text_dimensions
// NOTE: this.font MUST BE SELECTED INTO SPUI.ctx FIRST!!
SPUI.TextWidget.prototype.measure_text = function() {

    this.text_xy = [];
    this.text_dimensions = [];

    // XXX hack - somewhere some code is setting this to an integer :(
    if(typeof(this.str) !== 'string') {
        this.str = this.str.toString();
    }

    var lines = this.str.split('\n');

    for(var i = 0; i < lines.length; i++) {
        this.text_xy.push([0,0]);
        var dims = this.font.measure_string(lines[i]);
        dims[0] *= this.text_scale;
        dims[1] *= this.text_scale;
        this.text_dimensions.push(dims);

        if(this.text_hjustify === 'center') {
            this.text_xy[i][0] = Math.floor((this.wh[0] - this.text_dimensions[i][0])/2);
        } else if(this.text_hjustify === 'left') {
            this.text_xy[i][0] = 0;
        } else if(this.text_hjustify === 'right') {
            this.text_xy[i][0] = Math.floor(this.wh[0] - this.text_dimensions[i][0]);
        }

        // XXX this is really broken. draw_text_core below adds leading ON TOP OF this.text_xy
        if(this.text_vjustify === 'center') {
            // special case for 1-line strings - use the exact dimensions instead of line leading
            // this is necessary for all the many buttons that use the default "center" vjustify setting
            this.text_xy[i][1] = Math.floor((this.wh[1] - (lines.length > 1 ? (lines.length-1)*this.text_scale*this.font.leading : this.text_dimensions[i][1]))/2 + this.text_scale * this.font.size);
        } else if(this.text_vjustify === 'top') {
            this.text_xy[i][1] = this.text_scale * this.font.size;
        } else if(this.text_vjustify === 'bottom') {
            this.text_xy[i][1] = Math.floor(this.wh[1] - (lines.length-1)*this.text_scale*this.font.leading);
        }

        this.text_xy[i][0] += this.text_offset[0];
        this.text_xy[i][1] += this.text_offset[1];
    }
};

// temporary - try to catch widgets that have invalid strings set by other code
SPUI.TextWidget.prototype.draw_text_core = function(offset) {
    try {
        this._draw_text_core(offset);
    } catch(e) {
        var xys = (this.text_xy ? this.text_xy.toString() : 'BAD');
        var txys = (this.xy ? this.xy.toString() : 'BAD');
        var whs = (this.wh ? this.wh.toString() : 'BAD');
        var ofs = (offset ? offset.toString() : 'null_or_bad');
        var ctxs = (SPUI.ctx ? SPUI.ctx.toString() : 'null_or_bad');
        log_exception(e, 'draw_text_core: widget = '+this.get_address()+' str = ' + this.str.toString() + ' offset = '+ ofs + ' text_scale = '+this.text_scale.toString() + ' this.xy = ' + txys + ' this.wh = ' + whs + ' text_xy = '+ xys + ' leading = '+this.font.leading.toString() + ' SPUI.ctx = ' + ctxs);
    }
};

SPUI.TextWidget.prototype._draw_text_core = function(offset) {
    if(!this.str) { return; }

    var lines = this.str.split('\n');
    if(!lines || lines.length < 1) { return; }

    if(this.clip_to) {
        SPUI.ctx.save();
        SPUI.ctx.beginPath();
        SPUI.ctx.rect(offset[0]+this.clip_to[0], offset[1]+this.clip_to[1], this.clip_to[2], this.clip_to[3]);
        SPUI.ctx.clip();
    }

    var line_y = 0;

    for(var i = 0; i < lines.length; i++) {
        if(this.text_scale != 1 || this.text_angle != 0) {
            SPUI.ctx.save();
            var xlate = [this.xy[0]+offset[0]+this.text_xy[i][0],
                         this.xy[1]+offset[1]+this.text_xy[i][1]+line_y];
            SPUI.ctx.transform(1, 0, 0, 1, xlate[0], xlate[1]);

            if(this.text_scale != 1) {
                SPUI.ctx.transform(this.text_scale, 0, 0, this.text_scale, 0, 0);
            }
            if(this.text_angle != 0) {
                var angle = (Math.PI/180)*this.text_angle;
                var c = Math.cos(angle), s = Math.sin(angle);
                SPUI.ctx.transform(c, s, -s, c, 0, 0);
            }

            SPUI.ctx.fillText(lines[i], 0, 0);
            SPUI.ctx.restore();
        } else {
            SPUI.ctx.fillText(lines[i], this.xy[0]+offset[0]+this.text_xy[i][0], this.xy[1]+offset[1]+this.text_xy[i][1]+line_y);
        }
        line_y += this.font.leading;
    }

    if(this.clip_to) {
        SPUI.ctx.restore();
    }
};

SPUI.TextWidget.prototype.draw_text = function(offset) {
    if(!this.str) { return; }
    SPUI.ctx.save();

    // XXX probably want to track context to minimize unnecessary Canvas state changes

    SPUI.ctx.font = this.font.str();

    this.measure_text();
    if(this.drop_shadow) {
        SPUI.ctx.fillStyle = 'rgba(0,0,0,1)';
        this.draw_text_core([offset[0]+this.drop_shadow,offset[1]+this.drop_shadow]);
    }
    SPUI.ctx.fillStyle = this.text_color.str();
    this.draw_text_core(offset);

    SPUI.ctx.restore();
};

/** @param {string} str
    @param {SPUI.Font} font
    @param {Array.<number>} wh
    @param {Object=} options */
SPUI.break_lines = function(str, font, wh, options) {
    var bbcode = (options && options.bbcode);

    if(!str) { return ['', 1]; }

    var ret = '';
    var x = 0, nlines = 1;

    SPUI.ctx.save();
    SPUI.ctx.font = font.str();
    var space_width = font.measure_string(' ')[0];
    var em_width = font.measure_string('M')[0];

    // approximate max number of characters that can fit on one line
    var max_chars = Math.max(Math.floor(wh[0] / em_width), 1);

    var blocks = str.split('\n');
    for(var b = 0; b < blocks.length; b++) {
        if(b != 0) {
            ret += '\n'; x = 0; nlines += 1;
        }
        var block = blocks[b];

        // split line into words
        var words;
        if(bbcode) {
            words = SPText.bbcode_split_words(block);
        } else {
            words = block.split(' ');
        }

        for(var i = 0; i < words.length; i++) {

            // sanity check to prevent infinite loop
            if(i > 999 || words.length > 999) { break; }

            var measure_word = words[i];
            if(bbcode) { measure_word = SPText.bbcode_strip(measure_word); }

            //console.log('B '+b+' I '+i+' LEN '+words.length);
            var word_width = font.measure_string(measure_word)[0];

            //console.log('HERE x '+x+' w '+word_width+' wh '+wh[0]+' '+words[i]);

            // BBCode text tends to run slightly long because we can't apply kerning between blocks,
            // so pretend we need to accommodate one extra space worth of padding per line
            if(x + word_width + (bbcode ? space_width : 0) >= wh[0] || words[i] === '\n') {
                ret += '\n'; x = 0; nlines += 1;
            } else if(x != 0 && i != 0) {
                ret += ' ';
                x += space_width;
            }

            if(x == 0 && word_width >= wh[0] && measure_word.length > max_chars && !bbcode) {
                // one word so long it doesn't fit on the line even by itself!
                // break it at a non-whitespace location
                var first = words[i].slice(0,max_chars);
                var rest = words[i].slice(max_chars);
                //console.log('LONG ' + words[i] + ' -> ' + first + ' , '+ rest);
                ret += first + '\n'; x = 0; nlines += 1;

                // insert the rest of the word into the word list at the next index
                words.splice(i+1, 0, rest);
            } else {
                ret += words[i];
                x += word_width;
            }
        }
    }

    SPUI.ctx.restore();
    return [ret, nlines];
};

SPUI.TextWidget.prototype.break_lines = function(str) {
    return SPUI.break_lines(str, this.font, this.wh);
};

// set this.str with lines broken to fit space
SPUI.TextWidget.prototype.set_text_with_linebreaking = function(str) {
    var s_n = this.break_lines(str);
    this.str = s_n[0];
    if(this.resize_to_fit_text) {
        this.wh[1] = s_n[1] * this.font.leading;
    }
};

// TextField

/** @constructor
  * @extends SPUI.TextWidget
  */
SPUI.TextField = function(data) {
    goog.base(this, data);

    this.alpha = data['alpha'] || 1;

    if('ui_tooltip' in data) {
        var params = {'ui_name': data['ui_tooltip'] };
        if('tooltip_delay' in data) { params['delay'] = data['tooltip_delay']; }
        this.tooltip = new SPUI.Tooltip(params, this);
    } else {
        this.tooltip = null;
    }
    this.fixed_tooltip_offset = data['fixed_tooltip_offset'] || null;
};
goog.inherits(SPUI.TextField, SPUI.TextWidget);

SPUI.TextField.prototype.onleave = function() { if(this.tooltip) { this.tooltip.onleave(); } };

SPUI.TextField.prototype.do_draw = function(offset) {
    if(this.tooltip) { this.tooltip.activation_check(); }
    if(this.alpha <= 0) { return false; }
    var has_state = false;
    if(this.alpha < 1) {
        has_state = true;
        SPUI.ctx.save();
        SPUI.ctx.globalAlpha = this.alpha;
    }
    this.draw_text(offset);
    if(has_state) {
        SPUI.ctx.restore();
    }
    return true;
};

SPUI.TextField.prototype.on_mousemove = function(uv, offset) {
    if(!this.show) { return false; }
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        if(this.tooltip) {
            this.tooltip.onenter();
            //this.tooltip.xy = [this.xy[0]+offset[0], this.xy[1]+offset[1]];
            if(this.tooltip.xy === null) {
                if(this.fixed_tooltip_offset) {
                    this.tooltip.xy = [this.fixed_tooltip_offset[0] + offset[0],
                                       this.fixed_tooltip_offset[1] + offset[1]];
                } else {
                    this.tooltip.xy = [uv[0], uv[1]];
                }
            }
        }
    } else {
        if(this.tooltip) { this.tooltip.onleave(); }
    }
    return false;
};

// EXPERIMENTAL new BBCode rich-text field
/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.RichTextField = function(data) {
    goog.base(this, data);
    var text_style = data['text_style'] || "normal";
    var text_size = data['text_size'] || 18;
    var text_leading = data['text_leading'] || (text_size+4);
    this.font = SPUI.make_font(text_size, text_leading, text_style);
    this.text_hjustify = data['text_hjustify'] || 'center';
    this.text_vjustify = data['text_vjustify'] || 'center';
    this.text_offset = data['text_offset'] || [0,0];
    this.drop_shadow = data['drop_shadow'] || false;
    this.resize_to_fit_text = data['resize_to_fit_text'] || false;
    this.text = null;
    this.sblines = null;
    this.rtxt = null;
    this.dims_dirty = false;
    if('ui_name' in data && data['ui_name'].length>0) {
        this.set_text_bbcode(data['ui_name']);
    }

    this.onclick = null;
    this.pushed = false;

    // mouse-enter handler
    this.onenter = null;
    this.mouse_enter_time = -1;
    this.onleave_cb = null; // .onleave() is already used internally by SPUI :(

    if('ui_tooltip' in data) {
        var params = {'ui_name': data['ui_tooltip'] };
        if('tooltip_delay' in data) { params['delay'] = data['tooltip_delay']; }
        this.tooltip = new SPUI.Tooltip(params, this);
    } else {
        this.tooltip = null;
    }
    this.fixed_tooltip_offset = data['fixed_tooltip_offset'] || null;
};
goog.inherits(SPUI.RichTextField, SPUI.DialogWidget);
SPUI.RichTextField.prototype.set_text_ablocks = function(ablocks) {
    this.text = ablocks;
    this.sblines = this.rtxt = null;
    this.dims_dirty = true;
};
SPUI.RichTextField.prototype.set_text_bbcode = function(str) {
    this.set_text_ablocks(str ? SPText.cstring_to_ablocks_bbcode(str) : null);
};
// clip text if it takes more than "max_lines" lines. If we truncate text, add "appendage" (bbcode) to the end, e.g. "... See More"
SPUI.RichTextField.prototype.clip_to_max_lines = function(max_lines, appendage) {
    var lines = SPText.break_lines(this.text, this.wh[0], this.font);
    if(lines.length >= max_lines) {
        lines = lines.slice(0, max_lines);
        // rebuild the ABlocks from the post-line-break SBlocks
        var new_lines = [];
        for(var i = 0; i < lines.length; i++) {
            new_lines.push([]);
            for(var j = 0; j < lines[i].length; j++) {
                var s = lines[i][j].str;
                // truncate very last block
                if(i == lines.length-1 && j == lines[i].length-1) {
                    s = s.slice(0, s.length-(appendage ? 10 : 0)); // XXX need a rough approximation of appendage length
                }
                new_lines[i].push(new SPText.ABlock(s, lines[i][j].props));
            }
        }
        if(appendage) {
            new_lines[new_lines.length-1] = new_lines[new_lines.length-1].concat(SPText.cstring_to_ablocks_bbcode(appendage)[0]);
        }
        this.set_text_ablocks(new_lines);
        return true;
    }
    return false;
};
SPUI.RichTextField.prototype.update_dims = function() {
    if(!this.dims_dirty) { return; }
    this.dims_dirty = false;
    if(!this.text) { return; }
    SPUI.ctx.save();
    SPUI.ctx.font = this.font.str();
    this.sblines = SPText.break_lines(this.text, this.wh[0], this.font);
    if(this.sblines.length > 0) {
        if(this.resize_to_fit_text) { this.wh = [this.wh[0], this.sblines.length * this.font.leading + this.font.size]; }
        this.rtxt = SPText.layout_text(this.sblines, this.wh, this.text_hjustify, this.text_vjustify, this.font, [0,0]);
    } else {
        if(this.resize_to_fit_text) { this.wh = [this.data['dimensions'][0], 0]; }
    }
    SPUI.ctx.restore();
}
SPUI.RichTextField.prototype.do_draw = function(offset) {
    if(this.tooltip) { this.tooltip.activation_check(); }
    this.update_dims();
    if(!this.rtxt) {
        return false;
    }
    SPUI.ctx.save();
    SPUI.ctx.font = this.font.str();
    var text_offset = vec_add(this.text_offset, [offset[0], offset[1] + (this.pushed ? 1 : 0)]);
    if(this.drop_shadow) {
        SPUI.ctx.fillStyle = '#000000';
        SPText.render_text(this.rtxt, [text_offset[0]+this.xy[0]+this.drop_shadow,text_offset[1]+this.xy[1]+this.drop_shadow], this.font, true);
    }
    SPUI.ctx.fillStyle = SPUI.default_text_color.str();
    SPText.render_text(this.rtxt, [text_offset[0]+this.xy[0],text_offset[1]+this.xy[1]], this.font);
    SPUI.ctx.restore();
    return true;
};
SPUI.RichTextField.prototype.onleave = function() {
    if(this.tooltip) { this.tooltip.onleave(); }
    this.mouse_enter_time = -1;
    if(this.onleave_cb) { this.onleave_cb(this); }
};
SPUI.RichTextField.prototype.on_mousemove = function(uv, offset) {
    if(!this.show) { return false; }
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        if(this.mouse_enter_time == -1) {
            this.mouse_enter_time = SPUI.time;
            if(this.onenter) { this.onenter(this); }
        }
        if(this.tooltip) {
            this.tooltip.onenter();
            if(this.fixed_tooltip_offset) {
                this.tooltip.xy = [this.fixed_tooltip_offset[0] + offset[0],
                                   this.fixed_tooltip_offset[1] + offset[1]];
            } else {
                this.tooltip.xy = [uv[0]+10, uv[1]+10];
            }
        }
        // do not stop event handling here; allow other widgets to detect mouse-out
        //return true;
    } else {
        this.onleave();
    }
    return false;
};

SPUI.RichTextField.prototype.on_mousedown = function(uv, offset, button) {
    if(!this.show) { return false; }

    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) { // click is inside the area
        if(this.state === 'disabled') { return true; }
        this.pushed = true;
        return true;
    }
    return false;
};

SPUI.RichTextField.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.show) { return false; }

    this.pushed = false;

    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) { // click is inside the area
        if(this.state === 'disabled') { return true; }
        if(this.onclick) {
            // force the tooltip to disappear
            if(this.tooltip) { this.tooltip.onleave(); }
            this.onclick(this, button);
        }
        return true;
    }
    return false;
};

//
// TOOLTIPS
//

// global reference to the single active tooltip
// necessary in order to paint the tooltip on top of all other UI
SPUI.active_tooltip = null;

SPUI.tooltip_bg_color = new SPUI.Color(0,0,0,0.66);
SPUI.tooltip_outline_color = new SPUI.Color(1,1,1,1); // new SPUI.Color(0.5,0.15,0,1);

/** @constructor
  * @extends SPUI.TextWidget
  */
SPUI.Tooltip = function(data, owner) {
    // make a copy of 'data' so we can non-destructively override some values
    var data2 = {};
    for(var key in data) { if(data.hasOwnProperty(key)) { data2[key] = data[key]; } }
    data2['xy'] = data2['dimensions'] = [0,0]; // these are computed on the fly
    data2['text_size'] = 14;
    data2['text_hjustify'] = 'left'; data2['text_vjustify'] = 'top';

    goog.base(this, data2);
    this.xy = null; // assumes the associated widget will set this

    // number of seconds the mouse must hover before tooltip will appear
    if('delay' in data) {
        this.delay = data['delay'];
    } else {
        this.delay = 0.75;
    }

    this.owner = owner; // widget that this tooltip belongs to

    // # of pixels of padding between text string and tooltip border
    this.pad = 10;

    // SPUI.time when the mouse entered the associated widget, -1 if never
    this.mouse_enter_time = -1;
};
goog.inherits(SPUI.Tooltip, SPUI.TextWidget);

SPUI.Tooltip.prototype.get_address = function() {
    if(!this.owner) {
        return 'orphan tooltip';
    } else {
        return this.owner.get_address() + '.tooltip';
    }
};

SPUI.Tooltip.prototype.onenter = function() {
    if(this.mouse_enter_time < 0) {
        this.mouse_enter_time = SPUI.time;
    }
};
SPUI.Tooltip.prototype.onleave = function() {
    this.mouse_enter_time = -1;
    // deactivate tooltip when mouse leaves associated widget
    if(SPUI.active_tooltip === this) {
        SPUI.active_tooltip = null;
        this.xy = null;
    }
};
SPUI.Tooltip.prototype.activation_check = function() {
    if(!this.str) { return; }
    if((this.mouse_enter_time > 0) &&
       (SPUI.time - this.mouse_enter_time >= this.delay) &&
       (SPUI.active_tooltip != this)) {
        // activate the tooltip
        SPUI.active_tooltip = this;
    }
}
SPUI.Tooltip.prototype.activate = function() { SPUI.active_tooltip = this; };
SPUI.Tooltip.prototype.deactivate = function() { if(SPUI.active_tooltip === this) { SPUI.active_tooltip = null; } };
SPUI.Tooltip.prototype.is_active = function() { return (SPUI.active_tooltip === this); };

// note: does NOT go through base class draw()!
SPUI.Tooltip.prototype.draw = function(offset) {
    if(this.ondraw) { this.ondraw(this); }
    if(!this.is_active()) { return false; }

    // if owner was destroyed, then get rid of the tooltip
    if(this.owner && this.owner.parent === null) {
        this.deactivate();
        return false;
    }

    if(!this.str) { return false; }

    SPUI.ctx.save();
    SPUI.ctx.font = this.font.str();

    // resize border to surround text tightly
    this.wh = this.font.measure_string(this.str);
    this.measure_text();

    // four corners of the tooltip box
    var corners = [[this.xy[0]+offset[0]-this.pad, this.xy[1]+offset[1]-this.pad],
                   [this.xy[0]+offset[0]+this.wh[0]+this.pad, this.xy[1]+offset[1]-this.pad],
                   [this.xy[0]+offset[0]+this.wh[0]+this.pad, this.xy[1]+offset[1]+this.wh[1]+this.pad],
                   [this.xy[0]+offset[0]-this.pad, this.xy[1]+offset[1]+this.wh[1]+this.pad]];

    // draw dark background
    if(1) {
        var sprite = GameArt.assets['tooltip_bg'].states['normal'];
        sprite.draw_topleft_at_size([corners[0][0], corners[0][1]], 0, SPUI.time, [corners[2][0] - corners[0][0], corners[2][1] - corners[0][1]]);
    } else {
        SPUI.ctx.fillStyle = SPUI.tooltip_bg_color.str();
        SPUI.ctx.fillRect(corners[0][0], corners[0][1], corners[2][0] - corners[0][0], corners[2][1] - corners[0][1]);

        SPUI.ctx.strokeStyle = this.text_color.str(); /* SPUI.tooltip_outline_color.str(); */
        SPUI.ctx.lineWidth = 1;
        SPUI.ctx.beginPath();
        SPUI.ctx.rect(corners[0][0], corners[0][1], corners[2][0] - corners[0][0], corners[2][1] - corners[0][1]);
        SPUI.ctx.stroke();
    }

    SPUI.ctx.fillStyle = this.text_color.str();

    // draw text string
    this.draw_text_core(offset);
    SPUI.ctx.restore();
    return true;
}


// ActionButton: a button that does something when clicked
// (only draws a text string, the button itself is part of the dialog's background image)

/** @constructor
  * @extends SPUI.TextWidget
  */
SPUI.ActionButton = function(data) {
    goog.base(this, data);

    this.state = data['state'] || 'normal';
    this.rotating = data['rotating'] || false;
    this.shape_hack = data['shape_hack'] || null;
    this.clip_to = data['clip_to'] || null;

    this.pushed = false; // whether to draw button "pushed inwards"
    this.push_text = ('push_text' in data ? data['push_text'] : true); // whether text gets "pushed"
    this.push_bg_image = data['push_bg_image'] || false; // whether backgound image also gets "pushed"

    if('bg_image_offset' in data) {
        this.bg_image_offset = [data['bg_image_offset'][0], data['bg_image_offset'][1]];
    } else {
        this.bg_image_offset = [0,0];
    }
    this.bg_image_justify = data['bg_image_justify'] || null;
    this.bg_image_resizable = data['bg_image_resizable'] || null;

    this.bg_image = data['bg_image'] || null;

    // raw HTML Image element, can override bg_image
    this.raw_image = null;

    this.fade_unless_hover = data['fade_unless_hover'] || false;
    this.alpha = data['alpha'] || 1;
    this.mouseover_sound = data['mouseover_sound'] || false;

    if('highlight_text_color' in data) {
        var col = data['highlight_text_color'];
        this.highlight_text_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    } else {
        this.highlight_text_color = null;
    }

    if('dripper' in data) {
        var make_dripper_cb = function(widget) {
            return function() {
                widget.onclick(widget);
            };
        };
        this.dripper_cb = make_dripper_cb(this);
        this.dripper_rate = data['dripper']['rate'] || 1.5;
        this.dripper_delay = data['dripper']['delay'] || 0;
    } else {
        this.dripper_cb = this.dripper_rate = this.dripper_delay = null;
    }

    // note: it is expected that the caller will over-ride the onclick() handler
    this.onclick = function(widget, buttons) { console.log('BUTTON PRESS ' + widget.str); };

    // mouse-enter handler
    this.onenter = null;
    this.mouse_enter_time = -1;
    this.onleave_cb = null; // .onleave() is already used internally by SPUI :(

    if('ui_tooltip' in data) {
        var params = {'ui_name': data['ui_tooltip'] };
        if('tooltip_delay' in data) { params['delay'] = data['tooltip_delay']; }
        this.tooltip = new SPUI.Tooltip(params, this);
    } else {
        this.tooltip = null;
    }
    this.fixed_tooltip_offset = data['fixed_tooltip_offset'] || null;
};
goog.inherits(SPUI.ActionButton, SPUI.TextWidget);

SPUI.ActionButton.prototype.is_clickable = function() { return this.show && this.state != 'disabled'; };

SPUI.ActionButton.prototype.do_draw = function(offset) {
    if(this.tooltip) { this.tooltip.activation_check(); }
    var ctx_saved = false;

    var do_fade = (this.alpha != 1) || (this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0);
    if(do_fade) {
        var alpha = this.alpha;
        if(this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0) {
            alpha *= this.fade_unless_hover;
        }
        if(alpha < 0.005) { return false; }
        if(!ctx_saved) { SPUI.ctx.save(); ctx_saved = true; }
        SPUI.ctx.globalAlpha = alpha;
    }

    if(this.clip_to) {
        if(!ctx_saved) { SPUI.ctx.save(); ctx_saved = true; }
        SPUI.ctx.beginPath();
        SPUI.ctx.rect(offset[0]+this.clip_to[0], offset[1]+this.clip_to[1], this.clip_to[2], this.clip_to[3]);
        SPUI.ctx.clip();
    }

    var text_offset = [offset[0], offset[1]];
    var img_offset = [offset[0], offset[1]];
    if(this.pushed) {
        if(this.push_text) {
            text_offset[1] += 1;
        }
        if(this.push_bg_image) {
            img_offset[1] += 1;
        }
    }

    if(this.bg_image) {
        var art_asset = GameArt.assets[this.bg_image];
        var draw_state = this.state;
        if(!art_asset || !(draw_state in art_asset.states)) {
            throw Error('undefined art asset "'+this.bg_image+'" state "'+draw_state+'" in '+this.get_address());
        }

        if(this.pushed && ('pushed' in art_asset.states || art_asset.states[draw_state].on_push)) {
            // switch to 'pushed' state during mouse push, unless disabled
            if(this.state === 'normal' || this.state === 'active' || (this.state !== 'disabled' && art_asset.states[draw_state].on_push)) {
                draw_state = art_asset.states[draw_state].on_push || 'pushed';
            }
        } else if(this.mouse_enter_time != -1 && ('highlight' in art_asset.states || art_asset.states[draw_state].on_mouseover)) {
            // switch to 'highlight' state during mouse-over, unless the button is disabled
            if((this.state === 'normal') || (this.state !== 'disabled' && art_asset.states[draw_state].on_mouseover)) {
                draw_state = art_asset.states[draw_state].on_mouseover || 'highlight';
            }
        }

        var art_state = art_asset.states[draw_state];
        if(!art_state) {
            throw Error('undefined state "'+draw_state+'" for art asset "'+this.bg_image+'"');

        }

        var temp = this.text_color; // save text color so we can replace it later
        if(this.text_color === SPUI.default_text_color && art_state.text_color != null) {
            var col = art_state.text_color;
            this.text_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
        }

        var facing;
        if(this.rotating) {
            facing = ((2*SPUI.time) % (2*Math.PI));
        } else {
            facing = Math.PI/2;
        }

        if(this.bg_image_justify === 'center') {
            // this case handles icons for units and buildings when they are drawn in UI dialog boxes
            // since their sizes vary, we have to compute our own "center point" and then use the GameArt
            // drawing function that draws the unit/building with its center pixel on that point
            var ctr = [this.xy[0]+Math.floor(this.wh[0]/2), this.xy[1]+Math.floor(this.wh[1]/2)];
            art_state.draw([ctr[0]+img_offset[0]+this.bg_image_offset[0], ctr[1]+img_offset[1]+this.bg_image_offset[1]], facing, SPUI.time, (this.bg_image_resizable ? this.wh : null));
        } else {
            // normal case. Note, if we are resizing the background
            // image, we pass OUR this.wh down into the GameArt
            // drawing function, to tell it what size to draw.
            art_state.draw_topleft_at_size([this.xy[0]+img_offset[0]+this.bg_image_offset[0],
                                            this.xy[1]+img_offset[1]+this.bg_image_offset[1]],
                                           facing, SPUI.time, (this.bg_image_resizable ? this.wh : null));
        }
        if(this.str) {
            this.draw_text(text_offset);
        }
        this.text_color = temp;

    } else if(this.raw_image) {
        if(this.raw_image.complete && this.raw_image.width > 0) {
            try {
                // avoid browser barfs...
                SPUI.ctx.drawImage(this.raw_image, 0, 0, this.wh[0], this.wh[1], this.xy[0]+img_offset[0], this.xy[1]+img_offset[1], this.wh[0], this.wh[1]); // OK
            } catch(e) {}
        }
        if(this.str) {
            this.draw_text(text_offset);
        }
    } else {
        // button with no background image - just plain text
        var temp = this.text_color;
        if(this.mouse_enter_time != -1 && this.highlight_text_color && this.state === 'normal') {
            this.text_color = this.highlight_text_color;
        }
        if(this.str) { this.draw_text(text_offset); }
        this.text_color = temp;
    }

    if(ctx_saved) {
        SPUI.ctx.restore();
    }

    return true;
};

SPUI.ActionButton.prototype.detect_hit = function(uv, offset) {
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        if(this.shape_hack) {
            // horrible hack to handle triangular shape of unit recycle button
            var sum = (uv[0]-(this.xy[0]+offset[0])) + (uv[1]-(this.xy[1]+offset[1]));
            if(sum >= 58) {
                return false;
            }
        }
        return true;
    }
    return false;
};

SPUI.ActionButton.prototype.on_mousedown = function(uv, offset, button) {
    if(!this.show) { return false; }

    if(this.detect_hit(uv, offset)) {
        // click is inside the area
        if(this.state === 'disabled') { return true; }

        if(this.dripper_cb) {
            SPUI.dripper.reset(this.dripper_cb, this.dripper_rate, client_time + this.dripper_delay);
        }

        this.pushed = true;
        return true;
    }
    return false;
};

SPUI.ActionButton.prototype.onleave = function() {
    if(this.tooltip) { this.tooltip.onleave(); }
    this.mouse_enter_time = -1;
    this.pushed = false;
    if(this.onleave_cb) { this.onleave_cb(this); }

    // stop dripper if we own it
    if(this.dripper_cb && SPUI.dripper.cb === this.dripper_cb) {
        SPUI.dripper.stop();
    }
};

SPUI.ActionButton.prototype.destroy = function() {
    // stop dripper if we own it
    if(this.dripper_cb && SPUI.dripper.cb === this.dripper_cb) {
        SPUI.dripper.stop();
    }
    goog.base(this, 'destroy');
};

SPUI.ActionButton.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.show) { return false; }

    this.pushed = false;

    if(this.detect_hit(uv, offset)) {
        // click is inside the area
        if(this.state === 'disabled') { return true; }
        if(this.onclick) {
            if(this.bg_image) {
                var art_state = GameArt.assets[this.bg_image].states[this.state];
                if(art_state.audio) {
                    art_state.audio.play(SPUI.time);
                }
            }

            // force the tooltip to disappear
            if(this.tooltip) { this.tooltip.onleave(); }

            if(!this.dripper_cb) {
                this.onclick(this, button);
            } else if(SPUI.dripper.cb === this.dripper_cb) {
                SPUI.dripper.stop(true);
            }
        }
        return true;
    }
    return false;
};

SPUI.ActionButton.prototype.on_mousemove = function(uv, offset) {
    if(!this.show) { return false; }
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        if(this.mouse_enter_time == -1) {
            this.mouse_enter_time = SPUI.time;

            if(this.mouseover_sound && this.state != 'disabled' && 'mouseover_button_sound' in GameArt.assets) {
                GameArt.assets['mouseover_button_sound'].states['normal'].audio.play(SPUI.time);
            }

            if(this.onenter) { this.onenter(this); }
        }

        if(this.tooltip) {
            this.tooltip.onenter();
            if(this.fixed_tooltip_offset) {
                this.tooltip.xy = [this.fixed_tooltip_offset[0] + offset[0],
                                   this.fixed_tooltip_offset[1] + offset[1]];
            } else {
                this.tooltip.xy = [uv[0]+10, uv[1]+10];
            }
        }
        // do not stop event handling here; allow other widgets to detect mouse-out
        //return true;
    } else {
        this.onleave();
    }
    return false;
};

/** Returns SPUI.dripper if it is currently controlled by this button.
 *  @returns {(Dripper.Dripper | null)}
 */
SPUI.ActionButton.prototype.get_dripper = function() {
    return ((this.dripper_cb && SPUI.dripper.cb === this.dripper_cb) ? SPUI.dripper : null);
};

// StaticImage

/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.StaticImage = function(data) {
    goog.base(this, data);

    this.state = data['state'] || 'normal';
    this.asset = data['asset'] || null;
    this.rotating = data['rotating'] || false;
    this.rocking = data['rocking'] || false;
    this.bg_image_offset = data['bg_image_offset'] || [0,0];
    this.bg_image_justify = data['bg_image_justify'] || null;
    this.bg_image_resizable = data['bg_image_resizable'] || null;
    this.clip_to = data['clip_to'] || null;
    this.fade_unless_hover = data['fade_unless_hover'] || false;
    this.composite_mode = data['composite_mode'] || null;
    this.alpha = data['alpha'] || 1;
    this.opacity = data['opacity'] || 1;
    this.fade = data['fade'] || 0;
    this.fade_peak = data['fade_peak'] || 0.5;
    this.fade_times = data['fade_times'] || 1;

    if('transparent_to_mouse' in data) {
        this.transparent_to_mouse = data['transparent_to_mouse'];
    } else {
        this.transparent_to_mouse = true;
    }

    // caller can override this to use a raw HTML5 Image element rather than going through GameArt
    this.raw_image = null;

    if('fill_color' in data) {
        var col = data['fill_color'];
        this.fill_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    } else {
        this.fill_color = null;
    }

    // XXX really want a "mixin" class to provide tooltip
    // functionality - this is mostly copied from ActionButton
    this.onenter = null;
    this.mouse_enter_time = -1;
    this.onleave_cb = null; // .onleave() is already used internally by SPUI :(

    if('ui_tooltip' in data) {
        var params = {'ui_name': data['ui_tooltip'] };
        if('tooltip_delay' in data) { params['delay'] = data['tooltip_delay']; }
        this.tooltip = new SPUI.Tooltip(params, this);
    } else {
        this.tooltip = null;
    }
    this.fixed_tooltip_offset = data['fixed_tooltip_offset'] || null;

};
goog.inherits(SPUI.StaticImage, SPUI.DialogWidget);

SPUI.StaticImage.prototype.do_draw = function(offset) {
    if(this.tooltip) { this.tooltip.activation_check(); }

    var state_saved = false;

    var do_fade = (this.alpha != 1) || (this.opacity != 1) || this.fade || (this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0) || this.composite_mode;
    if(do_fade) {
        var alpha = this.alpha * this.opacity;
        if(this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0) {
            alpha *= this.fade_unless_hover;
        }

        if(this.fade) {
            var t = (SPUI.time - this.start_time) / this.duration;
            if(t < 0 || t > this.fade_times) {
                alpha *= 0;
            } else {
                t %= this.fade_times;
                var u;
                if(t < this.fade_peak) {
                    u = 1 - (this.fade_peak - t)/this.fade_peak;
                } else {
                    u = 1 - (t - this.fade_peak)/(1-this.fade_peak);
                }
                alpha *= Math.pow(u,2.0);
            }
        }

        if(alpha < 0.005) { return false; }

        if(!state_saved) { SPUI.ctx.save(); state_saved = true; }
        SPUI.ctx.globalAlpha = alpha;
        if(this.composite_mode) { SPUI.ctx.globalCompositeOperation = this.composite_mode; }
    }

    if(this.clip_to) {
        if(!state_saved) { SPUI.ctx.save(); state_saved = true; }
        SPUI.ctx.beginPath();
        SPUI.ctx.rect(offset[0]+this.clip_to[0], offset[1]+this.clip_to[1], this.clip_to[2], this.clip_to[3]);
        SPUI.ctx.clip();
    }

    if(this.raw_image && this.raw_image.complete && this.raw_image.width > 0) {
        try {
            // avoid browser barfs...
            SPUI.ctx.drawImage(this.raw_image, 0, 0, this.wh[0], this.wh[1], this.xy[0]+offset[0], this.xy[1]+offset[1], this.wh[0], this.wh[1]); // OK
        } catch(e) {}
    } else if(this.asset) {
        // XXX duplicated code from ActionButton. Make this a mixin
        var art_asset = GameArt.assets[this.asset];
        if(!art_asset) {
            console.log('Missing art asset '+this.asset+'!');
        } else {
            var facing;
            if(this.rotating) {
                facing = ((2*SPUI.time) % (2*Math.PI));
            } else {
                facing = Math.PI/2;
            }
            var draw_state = this.state;
            if(this.mouse_enter_time != -1 && this.state === 'normal' && 'highlight' in art_asset.states) {
                // switch to 'highlight' state during mouse-over, unless the button is disabled
                draw_state = 'highlight';
            }
            var art_state = art_asset.states[draw_state];
            if(!art_state) {
                console.log('Missing art asset state '+this.asset+'/'+draw_state+'!');
            } else {
                if(this.bg_image_justify === 'center') {
                    // this case handles icons for units and buildings when they are drawn in UI dialog boxes
                    // since their sizes vary, we have to compute our own "center point" and then use the GameArt
                    // drawing function that draws the unit/building with its center pixel on that point
                    var ctr = [this.xy[0]+Math.floor(this.wh[0]/2), this.xy[1]+Math.floor(this.wh[1]/2)];
                    art_state.draw([ctr[0]+offset[0]+this.bg_image_offset[0], ctr[1]+offset[1]+this.bg_image_offset[1]], facing, SPUI.time, (this.bg_image_resizable ? this.wh : null));
                } else {
                    // normal case. Note, we pass OUR this.wh down into the GameArt drawing function, to handle resizable widgets
                    var draw_xy = [this.xy[0]+offset[0]+this.bg_image_offset[0],
                                   this.xy[1]+offset[1]+this.bg_image_offset[1]];
                    if(this.rocking) {
                        if(!state_saved) { SPUI.ctx.save(); state_saved = true; }
                        var angle = (Math.PI/180)*15*Math.sin(5*SPUI.time);
                        var c = Math.cos(angle), s = Math.sin(angle);
                        SPUI.ctx.transform(c, s, -s, c, draw_xy[0]+this.wh[0]/2, draw_xy[1]+this.wh[1]/2);
                        draw_xy = [-this.wh[0]/2,-this.wh[1]/2];
                    }
                    art_state.draw_topleft_at_size(draw_xy, facing, SPUI.time, (this.bg_image_resizable ? this.wh : null));
                }
            }
        }
    } else if(this.fill_color) {
        if(!state_saved) { SPUI.ctx.save(); state_saved = true; }
        SPUI.ctx.fillStyle = this.fill_color.str();
        if(this.wh[0] < 0 && this.wh[1] < 0) { // fill screen
            SPUI.ctx.fillRect(0, 0, SPUI.canvas_width, SPUI.canvas_height);
        } else {
            SPUI.ctx.fillRect(this.xy[0]+offset[0], this.xy[1]+offset[1], this.wh[0], this.wh[1]);
        }
    }

    if(state_saved) { SPUI.ctx.restore(); }

    return true;
};

SPUI.StaticImage.prototype.on_mousemove = function(uv, offset) {
    if(!this.show) { return false; }
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        if(this.mouse_enter_time == -1) {
            this.mouse_enter_time = SPUI.time;
            if(this.onenter) { this.onenter(this); }
        }
        if(this.tooltip) {
            this.tooltip.onenter();
            if(this.fixed_tooltip_offset) {
                this.tooltip.xy = [this.fixed_tooltip_offset[0] + offset[0],
                                   this.fixed_tooltip_offset[1] + offset[1]];
            } else {
                this.tooltip.xy = [uv[0], uv[1]];
            }
        }
        // do not stop event handling here; allow other widgets to detect mouse-out
        //return true;
//      if(!this.transparent_to_mouse) { return true; }
    } else {
        this.onleave();
    }
    return false;
};

SPUI.StaticImage.prototype.onleave = function() {
    if(this.tooltip) { this.tooltip.onleave(); }
    this.mouse_enter_time = -1;
    if(this.onleave_cb) { this.onleave_cb(this); }
};

SPUI.StaticImage.prototype.on_mouseup = function(uv, offset, button) {
    if(this.show && !this.transparent_to_mouse &&
       uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        return true;
    }
    return false; // goog.base(this, 'on_mouseup', uv, offset, button);
};
SPUI.StaticImage.prototype.on_mousedown = SPUI.StaticImage.prototype.on_mouseup;

// FriendPortrait
// this is JUST the 50x50 pixel avatar picture for an AI or human player

/** @constructor
  * @extends SPUI.ActionButton
  */
SPUI.FriendPortrait = function(data) {
    goog.base(this, data);
    this.user_id = null;

    // filled in asynchronously
    // if displayed_user_id == this.user_id, then we are ready to draw
    this.displayed_user_id = null;
};
goog.inherits(SPUI.FriendPortrait, SPUI.ActionButton);

/** @param {number} user_id
  * @param {boolean=} use_map_portrait - if true, use the AI base "map_portrait" icon instead of "portrait"
  */
SPUI.FriendPortrait.prototype.set_user = function(user_id, use_map_portrait) {
    this.user_id = user_id;
    this.use_map_portrait = !!use_map_portrait;
};

SPUI.FriendPortrait.prototype.invalidate = function() { this.displayed_user_id = null; };

SPUI.force_anon_portraits = false; // set by the main client if we want to disable off-origin portrait image loading

// return a generic anonymous portrait image from inside the art pack
SPUI.get_anonymous_portrait_url = function(is_myself) {
    var filename = (is_myself ? 'art/anon_portrait.jpg' : 'art/anon_portrait2.jpg');
    return GameArt.art_url(filename, false);
};

SPUI.get_facebook_portrait_url = function(facebook_id) {
    facebook_id = facebook_id.toString(); // just make sure we don't get any numeric IDs
    if(SPUI.force_anon_portraits || anon_mode || facebook_id.indexOf('example') == 0) { // anonymous mode or testing sandbox
        return SPUI.get_anonymous_portrait_url(facebook_id === spin_facebook_user);
    } else {
        if(gamedata['client']['proxy_portraits']) {
            return GameArt.art_url('fb_portrait/'+facebook_id+'/picture?v='+gamedata['client']['portrait_proxy_cache_rev'], false); // "v" version is to rev the cache
        } else {
            return SPFB.versioned_graph_endpoint('user/picture', facebook_id+'/picture');
        }
    }
};
SPUI.get_armorgames_portrait_url = function(ag_id, avatar_url) {
    if(SPUI.force_anon_portraits || anon_mode || (ag_id && ag_id.indexOf('example') == 0)) { // anonymous mode or testing sandbox
        return SPUI.get_anonymous_portrait_url(ag_id === spin_armorgames_user);
    } else {
        if(gamedata['client']['proxy_portraits']) {
            return GameArt.art_url('ag_portrait/?avatar_url='+encodeURIComponent(avatar_url)+'&v='+gamedata['client']['portrait_proxy_cache_rev'], false);
        } else {
            return avatar_url;
        }
    }
};
SPUI.get_kongregate_portrait_url = function(kg_id, avatar_url) {
    if(SPUI.force_anon_portraits || anon_mode || (kg_id && kg_id.indexOf('example') == 0)) { // anonymous mode or testing sandbox
        return SPUI.get_anonymous_portrait_url(kg_id === spin_kongregate_user);
    } else {
        if(gamedata['client']['proxy_portraits']) {
            return GameArt.art_url('kg_portrait/?avatar_url='+encodeURIComponent(avatar_url)+'&v='+gamedata['client']['portrait_proxy_cache_rev'], false);
        } else {
            return avatar_url;
        }
    }
};

SPUI.FriendPortrait.prototype.update_display = function() {
    if(this.displayed_user_id == this.user_id) { return; } // already set
    this.bg_image = this.raw_image = null;

    if(this.user_id) {
        if(this.user_id < 0) { // set user_id negative to call up a "?" image
            this.bg_image = 'unknown_person_portrait';
            this.displayed_user_id = this.user_id; // mark as up-to-date
            return;
        }

        var info = PlayerCache.query_sync_fetch(this.user_id);
        if(info) {

            // for AIs, we pull the asset from gamedata
            if(PlayerCache.get_is_ai(info)) {
                var key = this.user_id.toString();
                if(!(key in gamedata['ai_bases_client']['bases'])) {
                    console.log('lookup of undefined ai portrait: '+key);
                    this.bg_image = 'unknown_person_portrait';
                } else {
                    var ai_base_data = gamedata['ai_bases_client']['bases'][key];
                    var portrait_key = (this.use_map_portrait && 'map_portrait' in ai_base_data) ? 'map_portrait' : 'portrait';
                    this.bg_image = ai_base_data[portrait_key];
                }
                this.displayed_user_id = this.user_id; // mark as up-to-date
                return;
            }

            // now try social network portrait URLs
            var url = null;
            var urls = {'fb': (info['facebook_id'] ? SPUI.get_facebook_portrait_url(info['facebook_id']) : null),
                        'ag': (info['ag_avatar_url'] ? SPUI.get_armorgames_portrait_url(info['ag_id'] || null, info['ag_avatar_url']) : null),
                        'kg': (info['kg_avatar_url'] ? SPUI.get_kongregate_portrait_url(info['kg_id'] || null, info['kg_avatar_url']) : null) };

            // first try current frame platform
            if(urls[spin_frame_platform]) {
                url = urls[spin_frame_platform];
            } else {
                // now try all others
                var frame_platforms = goog.object.getKeys(urls).sort(); // stabilize order to avoid flicker
                for(var i = 0; i < frame_platforms.length; i++) {
                    var u = urls[frame_platforms[i]];
                    if(u) { url = u; break; }
                }
            }
            if(url) {
                this.raw_image = PortraitCache.get_raw_image(url);
            } else {
                console.log('SPUI.FriendPortrait: cannot display '+JSON.stringify(info));
            }

            this.displayed_user_id = this.user_id; // mark as up-to-date
        } else {
            this.bg_image = 'unknown_person_portrait'; // temporarily show unknown while pending
        }
    }
};
SPUI.FriendPortrait.prototype.do_draw = function(offset) {
    this.update_display();

    // this sometimes fails due to broken HTML Image downloads
    try {
        return goog.base(this, 'do_draw', offset);
    } catch(e) {
        return false;
    }
};

// FriendIcon
// this is a FriendPortrait PLUS a (short) name and level display on top

/** @constructor
  * @extends SPUI.ActionButton
  */
SPUI.FriendIcon = function(data) {
    var friend_frame = GameArt.assets['friend_frame'].states['normal'];
    goog.base(this, {'xy':data['xy'], 'dimensions':data['dimensions'], 'state':data['state'], 'bg_image':'friend_frame'});
    this.mouseover_sound = true;

    this.portrait = new SPUI.FriendPortrait({'xy':data['xy'], 'dimensions':[50,50]});
    this.name = new SPUI.TextField({'xy':data['xy'], 'dimensions':[friend_frame.wh[0], 21],
                                    'text_size': 11});
    this.level = new SPUI.TextField({'xy':[data['xy'][0]+3, data['xy'][1]+55],
                                     'dimensions':[28,15], 'text_size':13, 'text_style': 'thick',
                                     'text_color':[1,1,1,1]});
    this.user_id = null;
    this.level_override = null;
};
goog.inherits(SPUI.FriendIcon, SPUI.ActionButton);

SPUI.FriendIcon.prototype.set_user = function(user_id) {
    this.user_id = user_id;
    this.level_override = null;
    this.portrait.set_user(this.user_id);
};
// manually override the displayed player level - useful for battle logs when looking at historical data
// (otherwise players send support tickets about being attacked by out-of-level-band attackers)
SPUI.FriendIcon.prototype.set_user_level = function(level) { this.level_override = level; };
SPUI.FriendIcon.prototype.update_display = function() {
    var name = null, level = null;
    if(this.user_id === session.user_id) {
        name = player.get_ui_name();
        level = player.resource_state['player_level'];
    } else {
        var info = PlayerCache.query_sync_fetch(this.user_id);
        name = (info ? PlayerCache._get_ui_name(info) : null);
        level = (info && info['player_level'] ? info['player_level'] : null);
    }

    level = (this.level_override || level);

    if(level === null) {
        this.level.str = 'L?';
    } else {
        this.level.str = 'L'+level.toFixed(0);
    }

    if(name === null) {
        this.name.str = '...';
    } else {
        if(name.length > 7) {
            // try to abbreviate the name
            name = name.split(' ')[0];
            if(name.length > 7) {
                name = name.slice(0,7);
            }
        }
        this.name.str = name;
    }
};

SPUI.FriendIcon.prototype.do_draw = function(offset) {
    // update child positions
    this.portrait.xy = this.xy;
    this.name.xy = this.xy;
    this.level.xy = [this.xy[0]+3, this.xy[1]+55];

    if(!this.user_id) {
        // empty - draw frame only
        var temp_state = this.state;
        this.state = 'empty';
        goog.base(this, 'do_draw', offset);
        this.state = temp_state;
    } else {
        this.update_display();

        // draw Facebook portrait underneath the frame
        var portrait_offset = [offset[0], offset[1] + 11 + (this.pushed ? 1 : 0)];
        var drawn = this.portrait.draw(portrait_offset);

        if(!drawn) {
            // fallback if it failed to draw anything - fill the portrait area with black
            SPUI.ctx.save();
            SPUI.ctx.fillStyle = '#000000';
            SPUI.ctx.fillRect(this.xy[0]+portrait_offset[0], this.xy[1]+portrait_offset[1], 50, 50);
            SPUI.ctx.restore();
        }

        // draw the frame
        goog.base(this, 'do_draw', offset);

        // draw text on top
        var text_state;
        if(this.mouse_enter_time != -1 && this.state === 'normal') {
            text_state = 'highlight';
        } else {
            text_state = 'normal';
        }
        var col = GameArt.assets['friend_frame'].states[text_state].text_color;
        this.name.text_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
        this.name.draw(offset);
        this.level.draw(offset);
    }
    return true;
};

SPUI.FriendIcon.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.portrait.user_id && !this.onclick) { return; }
    return goog.base(this, 'on_mouseup', uv, offset, button);
};

// SolidRect
/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.SolidRect = function(data) {
    goog.base(this, data);
    var col;

    col = ('color' in data ? data['color'] : [0,0,0,1]);
    this.color = (col ? new SPUI.Color(col[0], col[1], col[2], col[3]) : null);
    col = data['outline_color'] || null;
    this.outline_color = (col ? new SPUI.Color(col[0], col[1], col[2], col[3]) : null);
    col = data['gradient_color'] || null;
    this.gradient_color = (col ? new SPUI.Color(col[0], col[1], col[2], col[3]) : null);
    this.gradient_midpoint = ('gradient_midpoint' in data ? data['gradient_midpoint'] : 0.5);

    this.path = data['path'] || null;
    this.outline_width = data['outline_width'] || 0;
    this.opacity = data['opacity'] || 1;
    this.alpha = ('alpha' in data ? data['alpha'] : 1);
    this.bevel = data['bevel'] || 0;
    this.gradient = data['gradient'] || null;
    this.transparent_to_mouse = ('transparent_to_mouse' in data ? data['transparent_to_mouse'] : true);
    this.fade_unless_hover = data['fade_unless_hover'] || false;
};
goog.inherits(SPUI.SolidRect, SPUI.DialogWidget);

SPUI.add_quad_to_path = function(v) {
    SPUI.ctx.moveTo(v[0][0], v[0][1]);
    SPUI.ctx.lineTo(v[1][0], v[1][1]);
    SPUI.ctx.lineTo(v[2][0], v[2][1]);
    SPUI.ctx.lineTo(v[3][0], v[3][1]);
    SPUI.ctx.lineTo(v[0][0], v[0][1]);
};

SPUI.add_beveled_rectangle_to_path = function(xy, wh, b) {
    SPUI.ctx.moveTo(xy[0]+b, xy[1]);
    SPUI.ctx.lineTo(xy[0]+wh[0]-b, xy[1]);
    SPUI.ctx.lineTo(xy[0]+wh[0], xy[1]+b);
    SPUI.ctx.lineTo(xy[0]+wh[0], xy[1]+wh[1]-b);
    SPUI.ctx.lineTo(xy[0]+wh[0]-b, xy[1]+wh[1]);
    SPUI.ctx.lineTo(xy[0]+b, xy[1]+wh[1]);
    SPUI.ctx.lineTo(xy[0], xy[1]+wh[1]-b);
    SPUI.ctx.lineTo(xy[0], xy[1]+b);
    SPUI.ctx.lineTo(xy[0]+b, xy[1]);
};

SPUI.SolidRect.prototype.do_draw = function(offset) {
    SPUI.ctx.save();

    if(this.opacity < 1 || this.alpha < 1 || (this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0)) {
        var a = this.opacity * this.alpha;
        if(this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0) {
            a *= this.fade_unless_hover;
        }
        SPUI.ctx.globalAlpha = a;
    }

    var xy = [offset[0]+this.xy[0], offset[1]+this.xy[1]];

    if((this.color && this.color.a != 0) || (this.outline_width && this.outline_color)) {
        if(this.gradient) {
            var grd;

            if(this.gradient == 'vinout') {
                grd = SPUI.ctx.createLinearGradient(xy[0], xy[1], xy[0]+this.wh[0], xy[1]);
                grd.addColorStop(0, this.color.str());
                grd.addColorStop(this.gradient_midpoint, this.gradient_color.str());
                grd.addColorStop(1, this.color.str());
            } else if(this.gradient == 'hinout') {
                grd = SPUI.ctx.createLinearGradient(xy[0], xy[1], xy[0], xy[1]+this.wh[1]);
                grd.addColorStop(0, this.color.str());
                grd.addColorStop(this.gradient_midpoint, this.gradient_color.str());
                grd.addColorStop(1, this.color.str());
            } else {
                throw Error('unhandled gradient type '+this.gradient);
            }
            SPUI.ctx.fillStyle = grd;
        } else if(this.color) {
            SPUI.ctx.fillStyle = this.color.str();
        }
        if(this.path) {
            SPUI.ctx.beginPath();
            SPUI.ctx.moveTo(xy[0]+this.path[0][0], xy[1]+this.path[0][1]);
            for(var i = 1; i < this.path.length; i++) {
                if(this.path[i] === null) { // null means "raise pen while moving to next point"
                    i += 1;
                    if(i < this.path.length) {
                        SPUI.ctx.moveTo(xy[0]+this.path[i][0], xy[1]+this.path[i][1]);
                    }
                } else {
                    SPUI.ctx.lineTo(xy[0]+this.path[i][0], xy[1]+this.path[i][1]);
                }
            }
            if(this.color) { SPUI.ctx.fill(); }
        } else if(this.bevel > 0) {
            SPUI.ctx.beginPath();
            SPUI.add_beveled_rectangle_to_path(xy, this.wh, this.bevel);
            if(this.color) { SPUI.ctx.fill(); }
        } else {
            if(this.color) { SPUI.ctx.fillRect(xy[0], xy[1], this.wh[0], this.wh[1]); }
        }
    }
    if(this.outline_width && this.outline_color) {
        SPUI.ctx.lineWidth = this.outline_width;
        SPUI.ctx.strokeStyle = this.outline_color.str();
        if(this.path || this.bevel > 0) {
            SPUI.ctx.stroke();
        } else {
            SPUI.ctx.strokeRect(xy[0], xy[1], this.wh[0], this.wh[1]);
        }
    }
    SPUI.ctx.restore();
    return true;
};

SPUI.SolidRect.prototype.on_mousedown = function(uv, offset, button) {
    if(this.show && !this.transparent_to_mouse &&
       (uv[0] >= this.xy[0]+offset[0] &&
        uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
        uv[1] >= this.xy[1]+offset[1] &&
        uv[1]  < this.xy[1]+offset[1]+this.wh[1])) {
        return true;
    }
    return false;
};
SPUI.SolidRect.prototype.on_mouseup = SPUI.SolidRect.prototype.on_mousedown;
SPUI.SolidRect.prototype.on_mousemove = SPUI.SolidRect.prototype.on_mousedown;

// Line
/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.Line = function(data) {
    goog.base(this, data);
    var col = data['color'] || [0,0,0,1];
    this.color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    this.stroke_width = data['stroke_width'] || 2;
};
goog.inherits(SPUI.Line, SPUI.DialogWidget);
SPUI.Line.prototype.do_draw = function(offset) {
    SPUI.ctx.save();
    SPUI.ctx.strokeStyle = this.color.str();
    SPUI.ctx.strokeWidth = this.stroke_width;
    SPUI.ctx.beginPath();
    SPUI.ctx.moveTo(offset[0]+this.xy[0], offset[1]+this.xy[1]);
    SPUI.ctx.lineTo(offset[0]+this.xy[0]+this.wh[0], offset[1]+this.xy[1]+this.wh[1]);
    SPUI.ctx.stroke();
    SPUI.ctx.restore();
    return true;
};

// ProgressBar
/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.ProgressBar = function(data) {
    goog.base(this, data);
    this.outline_width = data['outline_width'] || 2;
    var col = data['outline_color'] || [0.02,0.02,0.02,0.5];
    // outline of the bar
    this.outline_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    col = data['empty_color'] || [0.01,0.01,0.01,1];
    // empty background behind the bar
    this.empty_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    col = data['full_color'] || [0.0,0.7,0.7,1];
    // the bar itself
    this.full_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    // optionally change the color of the bar when low
    if('low_color' in data) {
        col = data['low_color'];
        this.low_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    } else {
        this.low_color = null;
    }

    if('full_mouseover_color' in data) {
        col = data['full_mouseover_color'];
        this.full_mouseover_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    } else {
            this.full_mouseover_color = null;
    }
    this.tick_color = SPUI.make_colorv(('tick_color' in data ? data['tick_color'] : [1,1,1,1]));
    this.ticks = null;
    this.clip_to = data['clip_to'] || null;
    this.alpha = data['alpha'] || 1;
    this.progress = 0.5;
    this.mouse_enter_time = -1;
    this.onclick = null;
    this.state = 'normal';
};
goog.inherits(SPUI.ProgressBar, SPUI.DialogWidget);
SPUI.ProgressBar.prototype.do_draw = function(offset) {

    if(this.duration > 0) { // pure animation
        this.progress = (SPUI.time - this.start_time) / this.duration;
    }

    SPUI.ctx.save();
    if(this.clip_to) {
        SPUI.ctx.beginPath();
        SPUI.ctx.rect(offset[0]+this.clip_to[0], offset[1]+this.clip_to[1], this.clip_to[2], this.clip_to[3]);
        SPUI.ctx.clip();
    }
    if(this.alpha < 1) { SPUI.ctx.globalAlpha = this.alpha; }
    SPUI.ctx.fillStyle = this.empty_color.str();
    SPUI.ctx.fillRect(offset[0]+this.xy[0], offset[1]+this.xy[1], this.wh[0], this.wh[1]);
    this.progress = Math.min(Math.max(this.progress, 0), 1);

    var end = Math.floor(this.progress*this.wh[0]);
    if(this.progress > 0) {
        var col;
        if(this.low_color) {
            col = SPUI.Color.mix(this.low_color, this.full_color, this.progress);
        } else {
            col = this.full_color;
        }
        SPUI.ctx.fillStyle = (this.full_mouseover_color && this.mouse_enter_time > 0) ? this.full_mouseover_color.str() : col.str();
        SPUI.ctx.fillRect(offset[0]+this.xy[0], offset[1]+this.xy[1], end, this.wh[1]);
    }
    if(this.outline_width > 0) {
        SPUI.ctx.lineWidth = this.outline_width;
        SPUI.ctx.strokeStyle = this.outline_color.str();
        SPUI.ctx.strokeRect(offset[0]+this.xy[0], offset[1]+this.xy[1], this.wh[0], this.wh[1]);
    }
    if(this.ticks) {
        SPUI.ctx.strokeStyle = this.tick_color.str();
        SPUI.ctx.lineWidth = 2;
        SPUI.ctx.beginPath();
        goog.array.forEach(this.ticks, function(tick) {
            var x = Math.floor(tick['progress']*this.wh[0]);
            SPUI.ctx.moveTo(offset[0]+this.xy[0]+x, offset[1]+this.xy[1]);
            SPUI.ctx.lineTo(offset[0]+this.xy[0]+x, offset[1]+this.xy[1]+this.wh[1]);
        }, this);
        SPUI.ctx.stroke();
    }
    SPUI.ctx.restore();
    return true;
};
SPUI.ProgressBar.prototype.on_mousemove = function(uv, offset) {
    if(!this.show) { return false; }
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        if(this.mouse_enter_time == -1) {
            this.mouse_enter_time = SPUI.time;
        }
    } else {
        this.mouse_enter_time = -1;
    }
};
SPUI.ProgressBar.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.show) { return false; }
    if(!this.onclick) { return false; }

    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        // click is inside the area
        if(this.state === 'disabled') { return true; }
        this.onclick(this, button);
        return true;
    }
    return false;
};

// TextInput
/** @constructor
  * @extends SPUI.ActionButton
  */
SPUI.TextInput = function(data) {
    goog.base(this, data);
    this.blank_on_enter = ('blank_on_enter' in data ? data['blank_on_enter'] : true);
    this.max_chars = data['max_chars'] || 1000;
    this.multiline = ('multiline' in data ? data['multiline'] : false);
    this.clip_to = data['clip_to'] || null;
    this.allowed_chars = null;
    this.disallowed_chars = null;
    this.force_uppercase = data['force_uppercase'] || false;
    this.state = 'normal';

    this.fade_unless_hover = data['fade_unless_hover'] || false;
    if(this.fade_unless_hover) {
        this.faded_text_color = new SPUI.Color(1,1,1,this.fade_unless_hover);
    }

    this.has_typed = false;

    this.left_char = 0; // index of leftmost character to display

    this.onclick = function(widget) { widget.TextInput_onclick(); };
    this.ontype = null; // called for each character typed
    this.ontextready = null; // called on "ENTER" press
};
goog.inherits(SPUI.TextInput, SPUI.ActionButton);

SPUI.TextInput.prototype.reset_left_char = function() {
    if(this.multiline) { return; }

    // fix left_char to ensure cursor is on screen
    var jump = 15;

    SPUI.ctx.save();
    SPUI.ctx.font = this.font.str();
    var str_width = this.font.measure_string(this.str.slice(this.left_char))[0];
    SPUI.ctx.restore();
    if(str_width >= this.wh[0]) {
        this.left_char += jump;
        if(this.left_char > this.str.length-1) {
            this.left_char = this.str.length - jump;
        }
    } else if(this.left_char > 0 && this.left_char > this.str.length-1) {
        this.left_char = this.str.length - jump;
    }

    if(this.left_char < 0) { this.left_char = 0; }
};

SPUI.TextInput.prototype.onkeydown = function(code) {
    if(this.state == 'disabled') { return; }

    if(code === 8) { // backspace
        this.str = this.str.slice(0, this.str.length-1);
        this.reset_left_char();
        if(this.ontype) {
            this.ontype(this);
        }
        return true;
    } else if(code === 13) { // enter
        if(this.ontextready) {
            this.ontextready(this, this.str);
        }
        if(this.blank_on_enter) {
            this.str = '';
            this.left_char = 0;
        }
        return true;
    }

    return false;
};
SPUI.TextInput.prototype.onkeypress = function(code, c) {
    if(this.state == 'disabled') { return true; }

    if(this.str.length >= this.max_chars) { return true; }
    if(this.allowed_chars && this.allowed_chars.indexOf(c) == -1) { return true; }
    if(this.disallowed_chars && this.disallowed_chars.indexOf(c) != -1) { return true; }

    if(this.force_uppercase) { c = c.toUpperCase(); }
    this.str += c;
    this.reset_left_char();
    if(this.ontype) {
        this.ontype(this);
    }
    return true;
};

SPUI.TextInput.prototype.do_draw = function(offset) {
    var disabled = (this.state == 'disabled');
    var save_str = this.str;
    var save_color = this.text_color;

    if(!this.has_typed && this.fade_unless_hover && this.parent && this.parent.mouse_enter_time < 0) {
        if(this.fade_unless_hover < 0.005) { return false; }
        this.text_color = this.faded_text_color;
    }

    this.pushed = false; // disable "pushed" behavior

    // just for safety, check that left_char is within bounds
    if(this.left_char > this.str.length || this.left_char < 0) { this.left_char = 0; }
    if(this.left_char != 0) {
        this.str = this.str.slice(this.left_char);
    }

    // draw blinking bar cursor
    if(!disabled && SPUI.keyboard_focus === this && (Math.floor(2*SPUI.time) % 2 === 0)) {
        this.str += '|';
    }
    if(this.multiline) {
        this.set_text_with_linebreaking(this.str);
    }

    if(this.clip_to || disabled) {
        SPUI.ctx.save();
        if(this.clip_to) {
            SPUI.ctx.beginPath();
            SPUI.ctx.rect(offset[0]+this.clip_to[0], offset[1]+this.clip_to[1], this.clip_to[2], this.clip_to[3]);
            SPUI.ctx.clip();
        }
        if(disabled) {
            SPUI.ctx.globalAlpha = 0.5;
        }
    }

    goog.base(this, 'do_draw', offset);

    if(this.clip_to || disabled) {
        SPUI.ctx.restore();
    }

    this.text_color = save_color;
    this.str = save_str;
    return true;
}
SPUI.TextInput.prototype.TextInput_onclick = function() {
    if(!this.has_typed && this.blank_on_enter) {
        // clear out initial text message
        this.has_typed = true;
        this.str = '';
    }
    SPUI.set_keyboard_focus(this);
};
SPUI.TextInput.prototype.destroy = function() {
    goog.base(this, 'destroy');
    if(SPUI.keyboard_focus === this) {
        SPUI.set_keyboard_focus(null);
    }
};
SPUI.set_keyboard_focus = function(newfocus) {
    if(SPUI.keyboard_focus != newfocus) {
        if(SPUI.keyboard_focus && SPUI.keyboard_focus.onunfocus) {
            SPUI.keyboard_focus.onunfocus(SPUI.keyboard_focus);
        }
        SPUI.keyboard_focus = newfocus;
        if(SPUI.keyboard_focus && SPUI.keyboard_focus.onfocus) {
            SPUI.keyboard_focus.onfocus(SPUI.keyboard_focus);
        }
    }
};

// ScrollingTextField

// vertically scrollable text field
// uses a circular doubly-linked list to hold lines of text

/** @constructor */
SPUI.TextNode = function() {
    /** @type {Array.<SPText.ABlock>|null} */
    this.text = null;
    /** @type {SPUI.TextNode|null} */
    this.prev = null;
    /** @type {SPUI.TextNode|null} */
    this.next = null;
    /** @type {function(SPUI.TextNode)|null} */
    this.on_destroy = null;
    this.user_data = null;
};
SPUI.TextNode.prototype.destroy = function() {
    if(this.on_destroy) { this.on_destroy(this); }
    this.text = this.prev = this.next = this.on_destroy = this.user_data = null;
};

/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.ScrollingTextField = function(data) {
    goog.base(this, data);

    this.transparent_to_mouse = ('transparent_to_mouse' in data ? data['transparent_to_mouse'] : false);

    // XXX temporarily copied from TextWidget until we replace TextWidget's
    // linebreaking/drawing functions with the new SPText library and make
    // this inherit from TextField again

    if('text_color' in data) {
        var col = data['text_color'];
        this.text_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
    } else {
        this.text_color = SPUI.default_text_color;
    }

    var text_style = data['text_style'] || "normal";
    var text_size = data['text_size'] || 18;
    var text_leading = data['text_leading'] || (text_size+4);
    this.font = SPUI.make_font(text_size, text_leading, text_style);
    this.drop_shadow = data['drop_shadow'] || false;

    this.text_hjustify = data['text_hjustify'] || "center";
    this.text_vjustify = data['text_vjustify'] || "center";
    this.text_offset = data['text_offset'] || [0,0];
    this.alpha = ('alpha' in data ? data['alpha'] : 1);

    // XXXXXX the circular-buffer scrolling mechanics here are very confusing.
    // this was originally designed "IRC client" style, with the window by default
    // keeping up with the last-appended line ("head" pointer), and the beginning
    // of the displayed text pointed to by "bot". But now the in-game chat window
    // uses the "invert" option to invert the vertical display. Also, other parts
    // if the GUI are using this to make a scrolling rich text widget, where the
    // "IRC" scrolling style doesn't make sense. Need to clean this up sometime.

    /** @type {SPUI.TextNode}
        @private */
    // sentinel element that represents the bottom of the scroll area
    // new lines are added before this
    this.head = new SPUI.TextNode();
    this.head.next = this.head;
    this.head.prev = this.head;

    /** @type {SPUI.TextNode}
        @private */
    // bot points to the bottom-most line currently being displayed
    this.bot = this.head;

    /** @type {SPUI.TextNode}
        @private */
    // top is read-only, updated only in update_text()
    this.top = this.head;

    this.n_lines = 0;
    this.max_lines = data['scrollback_buffer'] || 50;
    this.invert = data['invert'] || false; // show upside-down (newest at top)

    /** @type {Array.<Array.<SPText.RBlock>>|null} */
    this.rtxt = null; // renderable text from SPText

    if('ui_tooltip' in data) {
        var params = {'ui_name': data['ui_tooltip'] };
        if('tooltip_delay' in data) { params['delay'] = data['tooltip_delay']; }
        this.tooltip = new SPUI.Tooltip(params, this);
    } else {
        this.tooltip = null;
    }

    // optional connections to scroll arrow widgets
    this.scroll_up_button = null;
    this.scroll_down_button = null;
};
goog.inherits(SPUI.ScrollingTextField, SPUI.DialogWidget);

SPUI.ScrollingTextField.prototype.set_text = function(text, user_data) {
    this.clear_text();
    this.append_text(text, user_data);
};

SPUI.ScrollingTextField.prototype.clear_text = function() {
    var next;
    for(var node = this.head.next; node != this.head; node = next) {
        next = node.next;
        node.destroy();
    }
    this.bot = this.head;
    this.top = this.head;
    this.head.next = this.head.prev = this.head;
    this.n_lines = 0;
    this.update_text();
};

SPUI.ScrollingTextField.prototype.destroy = function() {
    goog.base(this, 'destroy');
    this.clear_text();
};

/** @param {Array.<SPText.ABlock>} text
    @param {Object=} user_data */
SPUI.ScrollingTextField.prototype.append_text = function(text, user_data) {
    var node;
    if(this.n_lines >= this.max_lines) {
        // reuse topmost element
        node = this.head.next;
        node.prev.next = node.next;
        node.next.prev = node.prev;
        node.destroy();
    } else {
        // make new element
        node = new SPUI.TextNode();
        this.n_lines += 1;
    }
    // prepend element before BOT

    node.text = text;
    if(user_data) { node.user_data = user_data; }
    node.prev = this.head.prev;
    node.next = this.head;
    this.head.prev.next = node;
    this.head.prev = node;

    this.update_text();
    return node;
};

SPUI.ScrollingTextField.prototype.revise_text = function(node, text) {
    if(!node.prev || !node.next) { throw Error('revise_text on bad node '+node.toString()); }
    if(text === null) { throw Error('null text!'); }
    node.text = text;
    this.update_text();
    return node;
};
SPUI.ScrollingTextField.prototype.remove_text = function(node) {
    if(!node.prev || !node.next) { throw Error('remove_text on bad node '+node.toString()); }
    node.prev.next = node.next;
    node.next.prev = node.prev;
    node.destroy();
    this.update_text();
};
SPUI.ScrollingTextField.prototype.revise_all_text = function(mutator) {
    for(var node = this.head.next; node != this.head; node = node.next) {
        node.text = mutator(node.text, node.user_data);
        if(node.text === null) { throw Error('null text!'); }
    }
    this.update_text();
};

SPUI.ScrollingTextField.prototype.update_text = function() {
    // how many lines can fit on screen?
    var disp_lines = Math.floor(this.wh[1] / this.font.leading);
    if(disp_lines < 1) { this.rtxt = null; return; }

    // accumulate text lines upwards from 'bot'

    var node = this.bot;
    if(node === this.head) {
        node = this.bot.prev;
    }

    SPUI.ctx.save();
    SPUI.ctx.font = this.font.str();

    var sblines = [];
    while(sblines.length < disp_lines && node !== this.head) {
        if(node.text === null) { throw Error('encountered invalid text node'); }

        var s_n = SPText.break_lines(node.text, this.wh[0], this.font);
        if(sblines.length + s_n.length > disp_lines) {
            // can't fit
            break;
        }

        // If we have an empty text node, the intention is to insert a
        // carriage return. By default, break_lines() assumes empty
        // text takes no space at all, so for the purposes of this
        // widget, we have to change the interpretation of empty text
        // to be "a line with no text" instead of "nothing at all".
        if(s_n.length < 1) { s_n.push([]); }

        if(this.invert) { s_n.reverse(); }
        sblines = s_n.concat(sblines);
        node = node.prev;
        this.top = node;
    }
    if(sblines.length > 0) {
        if(this.invert) { sblines.reverse(); }
        this.rtxt = SPText.layout_text(sblines, this.wh, this.text_hjustify, this.text_vjustify, this.font, this.text_offset);
    } else {
        this.rtxt = null;
    }
    SPUI.ctx.restore();

    if(this.scroll_up_button) {
        this.scroll_up_button.state = (this.can_scroll_up() ? 'normal' : 'disabled');
    }
    if(this.scroll_down_button) {
        this.scroll_down_button.state = (this.can_scroll_down() ? 'normal' : 'disabled');
    }
};

SPUI.ScrollingTextField.prototype.do_draw = function(offset) {
    if(this.tooltip) { this.tooltip.activation_check(); }
    if(!this.rtxt) {
        return false;
    }
    SPUI.ctx.save();
    if(this.alpha != 1) {
        SPUI.ctx.globalAlpha = this.alpha;
    }
    SPUI.ctx.font = this.font.str();
    if(this.drop_shadow) {
        SPUI.ctx.fillStyle = '#000000';
        SPText.render_text(this.rtxt, [offset[0]+this.xy[0]+this.drop_shadow,offset[1]+this.xy[1]+this.drop_shadow], this.font, true);
    }
    SPUI.ctx.fillStyle = SPUI.ctx.strokeStyle = this.text_color.str();
    SPText.render_text(this.rtxt, [offset[0]+this.xy[0],offset[1]+this.xy[1]], this.font);
    SPUI.ctx.restore();
    return true;
};

SPUI.ScrollingTextField.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.show) { return false; }
    if(!this.rtxt) { return; }
    if(uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        // click is inside the area
        if(this.state === 'disabled') { return true; }
        var testxy = [uv[0]-this.xy[0]-offset[0]-this.text_offset[0],
                      uv[1]-this.xy[1]-offset[1]-this.text_offset[1]];
        testxy[1] += this.font.size; // XXX adjust for baseline in SPText
        var props = SPText.detect_hit(this.rtxt, testxy);
        if(props && props.onclick) {
            props.onclick(this, uv);
            // force the tooltip to disappear
            if(this.tooltip) { this.tooltip.onleave(); }
            return true;
        }
        return !this.transparent_to_mouse;
    }
    return false;
};
SPUI.ScrollingTextField.prototype.on_mousedown = function(uv, offset, button) {
    if(this.show && !this.transparent_to_mouse &&
       uv[0] >= this.xy[0]+offset[0] &&
       uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
       uv[1] >= this.xy[1]+offset[1] &&
       uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
        return true;
    }
    return false;
};

SPUI.ScrollingTextField.prototype.on_mousemove = function(uv, offset) {
    if(!this.show) { return false; }
    if(this.tooltip) {
        this.tooltip.str = null;
        if(this.rtxt &&
           uv[0] >= this.xy[0]+offset[0] &&
           uv[0]  < this.xy[0]+offset[0]+this.wh[0] &&
           uv[1] >= this.xy[1]+offset[1] &&
           uv[1]  < this.xy[1]+offset[1]+this.wh[1]) {
            var testxy = [uv[0]-this.xy[0]-offset[0]-this.text_offset[0],
                          uv[1]-this.xy[1]-offset[1]-this.text_offset[1]];
            testxy[1] += this.font.size; // XXX adjust for baseline in SPText
            var props = SPText.detect_hit(this.rtxt, testxy);
            if(props && props.tooltip_func) {
                var s = props.tooltip_func();
                if(s) {
                    this.tooltip.onenter();
                    this.tooltip.str = s;
                    this.tooltip.xy = [uv[0]+10, uv[1]+10];
                }
            }
        } else {
            this.onleave();
        }
    }
    return false;
};

SPUI.ScrollingTextField.prototype.onleave = function() {
    if(this.tooltip) { this.tooltip.onleave(); }
};


SPUI.ScrollingTextField.prototype.can_scroll_down = function() {
    return (this.bot !== this.head);
};
SPUI.ScrollingTextField.prototype.can_scroll_up = function() {
    return (this.bot.prev !== this.head && this.top != this.head);
};

/** return the number of times, after scroll_to_bottom(), you'd have to call scroll_up() to reach the current position
    @return {number} */
SPUI.ScrollingTextField.prototype.get_scroll_pos_from_head_to_bot = function() {
    if(this.bot === this.head) { return 0; }
    var pos = 0;
    var p = this.head.prev;
    while(p != this.bot) {
        pos += 1;
        p = p.prev;
    }
    return pos;
};

SPUI.ScrollingTextField.prototype.scroll_down = function() {
    if(this.can_scroll_down()) {
        this.bot = this.bot.next;
        if(this.bot.next === this.head) {
            // stick it to the bottom
            this.bot = this.head;
        }
        this.update_text();
    }
};

SPUI.ScrollingTextField.prototype.scroll_to_bottom = function() {
    this.bot = this.head;
    this.update_text();
};

SPUI.ScrollingTextField.prototype.scroll_up = function() {
    if(this.can_scroll_up()) {
        if(this.bot === this.head) {
            // lift if off the bottom
            this.bot = this.bot.prev.prev;
        } else {
            this.bot = this.bot.prev;
        }
        this.update_text();
    }
};

SPUI.ScrollingTextField.prototype.scroll_to_top = function() {
    // XXX horrible performance, work on it later
    while(this.can_scroll_up()) { this.scroll_up(); }
};


// SpellIcon (obsolete, this has been replaced by inventory slot/item/stack/frame plus CooldownClock)

/** @constructor
  * @extends SPUI.ActionButton
  */
SPUI.SpellIcon = function(data) {
    goog.base(this, {'xy':data['xy'], 'dimensions':data['dimensions'], 'state':data['state']});
    this.inset = [0,0];
    this.frame = GameArt.assets['spell_icon_frame'].states['normal'];
    this.glow_inner = GameArt.assets['spell_icon_glow_inner'].states['normal'];
    this.glow_outer = null; // GameArt.assets['spell_icon_glow_outer'].states['normal'];

    this.unit = 1234;
    this.spell = 1234; // not null so set_spell() initializes
    this.pushed_key = false;

    /*

    this.name = new SPUI.TextField({'xy':data['xy'], 'dimensions':[friend_frame.wh[0], 21],
                                    'text_size': 11});
    this.level = new SPUI.TextField({'xy':[data['xy'][0]+3, data['xy'][1]+55],
                                     'dimensions':[28,15], 'text_size':13, 'text_style': 'bold',
                                     'text_color':[1,1,1,1]});
    */
    this.set_spell(null, null, null);
};
goog.inherits(SPUI.SpellIcon, SPUI.ActionButton);
SPUI.SpellIcon.prototype.set_spell = function(unit, spell_name, spell) {
    if(unit === this.unit && spell === this.spell) { return; }
    this.activated = 0;
    this.cooldown = 0;
    this.unit = unit;
    this.spell_name = spell_name;
    this.spell = spell;
    if(!spell || !spell['icon']) {
        this.icon = null;
    } else {
        this.icon = GameArt.assets[spell['icon']].states['normal'];
    }
    //this.name.str = short_name;
};

SPUI.SpellIcon.prototype.do_draw = function(offset) {
    SPUI.ctx.save();
    var pos = [this.xy[0]+offset[0],this.xy[1]+offset[1]];

    SPUI.ctx.fillStyle = '#000000';

    if(!this.icon) {
        // empty - draw back rect instead of icon
        SPUI.ctx.fillRect(this.xy[0]+offset[0]+this.inset[0], this.xy[1]+offset[1]+this.inset[1], 50, 50);
    } else {
        var icon_offset = [offset[0]+this.inset[0], offset[1]+this.inset[1]];
        if(this.pushed || this.pushed_key) {
            //icon_offset[1] += 1;
        }
        this.icon.draw_topleft([this.xy[0]+icon_offset[0], this.xy[1]+icon_offset[1]], 0, client_time);
        // draw text on top
        /*
        var text_state;
        if(this.mouse_enter_time != -1 && this.state === 'normal') {
            text_state = 'highlight';
        } else {
            text_state = 'normal';
        }
        var col = GameArt.assets['friend_frame'].states[text_state].text_color;
        this.name.text_color = new SPUI.Color(col[0], col[1], col[2], col[3]);
        this.name.draw(offset);
        this.level.draw(offset);
        */
        var inner_glow = 0, outer_glow = 0;
        if(this.pushed_key) {
            inner_glow = 0.25;
        }
        if(this.pushed) {
            inner_glow = 0.25;
            //outer_glow += 0.85;
        }

        if(this.activated > 0) {
            var fade_time = 0.5;
            var fade = 1.0 - ((client_time+0.15) - this.activated) / fade_time;
            fade = Math.min(fade, 1);
            if(fade > 0) {
                inner_glow = Math.max(inner_glow, fade);
                outer_glow = Math.max(outer_glow, fade);
            }
        }


        // draw cooldown clock sweep
        if(this.cooldown > this.activated) {
            var progress = (SPUI.time - this.activated) / (this.cooldown - this.activated);
            if(progress >= 1) {
                this.activated = SPUI.time; // make it flash again
                this.cooldown = 0;
            } else {
                var size = 25;
                progress = Math.min(Math.max(progress,0.001),0.999);
                SPUI.ctx.globalAlpha = 0.66;
                SPUI.ctx.beginPath();
                SPUI.ctx.moveTo(pos[0]+size, pos[1]+size);
                SPUI.ctx.lineTo(pos[0]+size, pos[1]+this.inset[1]);
                //SPUI.ctx.arc(pos[0]+size, pos[1]+size, size-this.inset[0], -Math.PI/2, 2*Math.PI*progress - Math.PI/2, true);
                if(1-progress >= 0.125) {
                    SPUI.ctx.lineTo(pos[0]+this.inset[0], pos[1]+this.inset[1]);
                }
                if(1-progress >= 0.375) {
                    SPUI.ctx.lineTo(pos[0]+this.inset[0], pos[1]+2*size-this.inset[1]);
                }
                if(1-progress >= 0.625) {
                    SPUI.ctx.lineTo(pos[0]+2*size-this.inset[0], pos[1]+2*size-this.inset[1]);
                }
                if(1-progress >= 0.875) {
                    SPUI.ctx.lineTo(pos[0]+2*size-this.inset[0], pos[1]+this.inset[1]);
                }
                // final point is projection of smooth clock hand
                var angle = 2*Math.PI*progress - Math.PI/2;
                var s = Math.sin(angle), c = Math.cos(angle);
                var x = c;
                var y = s;
                if(Math.abs(x) >= Math.abs(y)) {
                    // clamp to left/right edge
                    if(x >= 0) {
                        x = 1; y = Math.tan(angle);
                    } else {
                        x = -1; y = -Math.tan(angle - Math.PI);
                    }

                } else {
                    // clamp to top/bottom
                    if(y >= 0) {
                        y = 1; x = -Math.tan(angle - Math.PI/2);
                    } else {
                        y = -1; x = Math.tan(angle + Math.PI/2);
                    }
                }
                SPUI.ctx.lineTo(Math.floor(pos[0]+size + (size-this.inset[0])*x),
                                Math.floor(pos[1]+size + (size-this.inset[1])*y));
                SPUI.ctx.lineTo(pos[0]+size, pos[1]+size);
                SPUI.ctx.fill();
            }
        }

        if(inner_glow > 0) {
            SPUI.ctx.globalAlpha = Math.min(1, inner_glow);
            this.glow_inner.draw_topleft(pos, 0, client_time);
            this.glow_inner.draw_topleft(pos, 0, client_time); // XXX fix opacity later
        }

        if(outer_glow > 0 && this.glow_outer) {
            SPUI.ctx.globalAlpha = Math.min(1, outer_glow);
            this.glow_outer.draw_topleft(pos, 0, client_time);
        }
    }
    SPUI.ctx.globalAlpha = 1;
    this.frame.draw_topleft(pos, 0, client_time);
    SPUI.ctx.restore();
    return true;
};

SPUI.SpellIcon.prototype.on_mouseup = function(uv, offset, button) {
    if(!this.spell) { return; }
    return goog.base(this, 'on_mouseup', uv, offset, button);
};


// CooldownClock

/** @constructor
  * @extends SPUI.DialogWidget
  */
SPUI.CooldownClock = function(data) {
    goog.base(this, data);
    this.inset = [0,0];
    this.glow_inner = GameArt.assets['spell_icon_glow_inner'].states['normal'];
    this.flash_time = 0;
    this.cooldown_start = 0;
    this.cooldown_end = 0;
    this.disabled = false;
};
goog.inherits(SPUI.CooldownClock, SPUI.DialogWidget);

SPUI.CooldownClock.prototype.do_draw = function(offset) {

    var pos = [this.xy[0]+offset[0],this.xy[1]+offset[1]];

    var inner_glow = 0, outer_glow = 0;

    if(this.flash_time > 0) {
        var fade_time = 0.5;
        var fade = 1.0 - ((SPUI.time+0.15) - this.flash_time) / fade_time;
        fade = Math.min(fade, 1);
        if(fade > 0) {
            inner_glow = Math.max(inner_glow, fade);
            outer_glow = Math.max(outer_glow, fade);
        }
    }

    var progress = ((this.cooldown_end > this.cooldown_start) ? ((SPUI.time - this.cooldown_start) / (this.cooldown_end - this.cooldown_start)) : -1);
    if(progress >= 1) {
        if(!this.disabled) {
            this.flash_time = SPUI.time; // make it flash again as cooldown finishes
            //console.log("GO! client_time"+client_time+" SPUI.time "+SPUI.time+" progress "+progress+" togo "+player.cooldown_togo('GCD')+ " this start "+this.cooldown_start+" end "+this.cooldown_end+" GCD start "+player.global_cooldown['start']+" end "+player.global_cooldown['end']);
        }
        this.cooldown_start = this.cooldown_end = 0;
    }

    // cull
    if(outer_glow <= 0 && inner_glow <= 0 && (progress < 0 || progress >= 1)) { return; }
    //console.log("inner_glow "+inner_glow+" progress "+progress);

    SPUI.ctx.save();
    SPUI.ctx.fillStyle = '#000000';

    // draw cooldown clock sweep
    if(progress > 0 && progress < 1) {
        var size = Math.floor(this.wh[0]/2);
        progress = Math.min(Math.max(progress,0.001),0.999);
        SPUI.ctx.globalAlpha = 0.66;
        SPUI.ctx.beginPath();
        SPUI.ctx.moveTo(pos[0]+size, pos[1]+size);
        SPUI.ctx.lineTo(pos[0]+size, pos[1]+this.inset[1]);
        //SPUI.ctx.arc(pos[0]+size, pos[1]+size, size-this.inset[0], -Math.PI/2, 2*Math.PI*progress - Math.PI/2, true);
        if(1-progress >= 0.125) {
            SPUI.ctx.lineTo(pos[0]+this.inset[0], pos[1]+this.inset[1]);
        }
        if(1-progress >= 0.375) {
            SPUI.ctx.lineTo(pos[0]+this.inset[0], pos[1]+2*size-this.inset[1]);
        }
        if(1-progress >= 0.625) {
            SPUI.ctx.lineTo(pos[0]+2*size-this.inset[0], pos[1]+2*size-this.inset[1]);
        }
        if(1-progress >= 0.875) {
            SPUI.ctx.lineTo(pos[0]+2*size-this.inset[0], pos[1]+this.inset[1]);
        }
        // final point is projection of smooth clock hand
        var angle = 2*Math.PI*progress - Math.PI/2;
        var s = Math.sin(angle), c = Math.cos(angle);
        var x = c;
        var y = s;
        if(Math.abs(x) >= Math.abs(y)) {
            // clamp to left/right edge
            if(x >= 0) {
                x = 1; y = Math.tan(angle);
            } else {
                x = -1; y = -Math.tan(angle - Math.PI);
            }
        } else {
            // clamp to top/bottom
            if(y >= 0) {
                y = 1; x = -Math.tan(angle - Math.PI/2);
            } else {
                y = -1; x = Math.tan(angle + Math.PI/2);
            }
        }
        SPUI.ctx.lineTo(Math.floor(pos[0]+size + (size-this.inset[0])*x),
                        Math.floor(pos[1]+size + (size-this.inset[1])*y));
        SPUI.ctx.lineTo(pos[0]+size, pos[1]+size);
        SPUI.ctx.fill();
    }

    if(inner_glow > 0) {
        SPUI.ctx.globalAlpha = Math.min(1, inner_glow);
        this.glow_inner.draw_topleft(pos, 0, client_time);
        this.glow_inner.draw_topleft(pos, 0, client_time); // XXX fix opacity later
    }
    SPUI.ctx.restore();

    return true;
};
