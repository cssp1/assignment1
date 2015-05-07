goog.provide('Screenshot');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    "Screenshot" a Canvas (or portion thereof) to a dataURI
*/

/** @enum {string} */
Screenshot.Codec = {
    JPEG: 'image/jpeg',
    PNG: 'image/png'
};

/** Once we get an exception, blacklist further screenshot attempts */
Screenshot.blacklisted = false;
/** @return {boolean} */
Screenshot.supported = function() { return !Screenshot.blacklisted; };

/** @constructor
    @struct
    @param {string} text */
Screenshot.Watermark = function(text) {
    this.text = text;
};

/** Wrap the toDataURL call to trap browser security (canvas tainted) error
    @param {!HTMLCanvasElement} canvas
    @param {string} codec
    @return {string|null} */
Screenshot.toDataURL = function(canvas, codec) {
    try {
        return canvas.toDataURL(codec);
    } catch(e) {
        //log_exception(e, 'Screenshot.toDataURL');
        metric_event('7275_screenshot_failed', add_demographics({}));
        Screenshot.blacklisted = true;
        return null;
    }
};

/** Capture entire canvas
    @param {!HTMLCanvasElement} canvas
    @param {Screenshot.Codec} codec
    @param {Screenshot.Watermark|null} watermark
    @return {string|null} */
Screenshot.capture_full = function(canvas, codec, watermark) {
    if(watermark) {
        return Screenshot.capture_subimage(canvas, [0,0], [canvas.width, canvas.height], codec, watermark);
    } else {
        return Screenshot.toDataURL(canvas, codec);
    }
};

/** Capture subimage
    @param {!HTMLCanvasElement} canvas
    @param {!Array.<number>} topleft
    @param {!Array.<number>} dimensions
    @param {Screenshot.Codec} codec
    @param {Screenshot.Watermark|null} watermark
    @return {string|null} */
Screenshot.capture_subimage = function(canvas, topleft, dimensions, codec, watermark) {
    var con = /** @type {!CanvasRenderingContext2D} */ (canvas.getContext('2d'));
    var osc = /** @type {!HTMLCanvasElement} */ (document.createElement('canvas'));
    osc.width = dimensions[0]; osc.height = dimensions[1];
    var osc_con = /** @type {!CanvasRenderingContext2D} */ (osc.getContext('2d'));
    var data = con.getImageData(topleft[0], topleft[1], dimensions[0], dimensions[1]);
    /** @type {*} */ (osc_con.putImageData(data, 0, 0));

    if(watermark) {
        Screenshot.apply_watermark(osc, osc_con, watermark);
    }

    return Screenshot.toDataURL(osc, codec);
};

/** @param {!HTMLCanvasElement} canvas
    @param {!CanvasRenderingContext2D} context
    @param {!Screenshot.Watermark} watermark */
Screenshot.apply_watermark = function(canvas, context, watermark) {
    var lines = watermark.text.split('\n');
    if(lines.length < 1) { return; }

    context.save();
    var size = Math.floor(canvas.height * 0.05);
    var leading = size + 3;
    /** @type {!Array.<number>} */
    var SHADOW_OFFSET = [2,2];
    var shadow_color = 'rgba(0,0,0,1)';
    var fill_color = 'rgba(255,255,255,1)';

    context.font = size.toString()+'px sans-serif bold';
    context.strokeStyle = 'rgba(0,0,0,1)';

    var max_width = 0;
    for(var n = 0; n < lines.length; n++) {
        var line = lines[n];
        max_width = Math.max(max_width, context.measureText(line).width);
    }

    var PAD = 30;
    var bounds = [[0,0],[0,0]];
    var hjustify = 'right';
    var x_start;
    if(hjustify == 'right') {
        x_start = canvas.width - PAD - max_width;
        bounds[0] = [x_start, x_start + max_width];
    } else if(hjustify == 'left') {
        x_start = PAD;
        bounds[0] = [x_start, x_start + max_width];
    } else if(hjustify == 'center') {
        x_start = Math.floor(canvas.width / 2); // center
        bounds[0] = [Math.floor(x_start - max_width/2), Math.ceil(x_start + max_width/2)];
    }

    var vjustify = 'bottom';
    var y_start;
    if(vjustify == 'top') {
        y_start = PAD;
    } else if(vjustify == 'bottom') {
        y_start = canvas.height - PAD - (lines.length-1) * leading; // bottom
    }
    bounds[1] = [y_start - Math.floor(leading/2), y_start + (lines.length-1) * leading];

    if(0) {
        // fill background
        var BGPAD = 12;
        context.fillStyle = 'rgba(0,0,0,0.5)';
        context.fillRect(bounds[0][0]-BGPAD, bounds[1][0]-BGPAD, bounds[0][1]-bounds[0][0]+2*BGPAD, bounds[1][1]-bounds[1][0]+2*BGPAD);
    }

    for(var n = 0; n < lines.length; n++) {
        var line = lines[n];
        /** @type {!Array.<number>} */
        var xy = [0,0];
        if(hjustify == 'right') {
            xy[0] = x_start + max_width - context.measureText(line).width;
            xy[1] = y_start + n * leading;
        } else if(hjustify == 'center') {
            xy[0] = x_start - Math.floor(context.measureText(line).width/2)
            xy[1] = y_start + n * leading;
        }
        context.fillStyle = shadow_color;
        context.fillText(line, xy[0] + SHADOW_OFFSET[0], xy[1] + SHADOW_OFFSET[1]);
        context.fillStyle = fill_color;
        context.fillText(line, xy[0], xy[1]);
        context.strokeText(line, xy[0], xy[1]);
    }

    context.restore();
};
