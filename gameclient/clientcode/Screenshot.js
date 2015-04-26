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

/** Capture entire canvas
    @param {!HTMLCanvasElement} canvas
    @param {Screenshot.Codec} codec
    @return {string} */
Screenshot.capture_full = function(canvas, codec) {
    return canvas.toDataURL(codec);
};

/** Capture subimage
    @param {!HTMLCanvasElement} canvas
    @param {!Array.<number>} topleft
    @param {!Array.<number>} dimensions
    @param {Screenshot.Codec} codec
    @return {string} */
Screenshot.capture_subimage = function(canvas, topleft, dimensions, codec) {
    var con = /** @type {!CanvasRenderingContext2D} */ (canvas.getContext('2d'));
    var osc = /** @type {!HTMLCanvasElement} */ (document.createElement('canvas'));
    osc.width = dimensions[0]; osc.height = dimensions[1];
    var osc_con = /** @type {!CanvasRenderingContext2D} */ (osc.getContext('2d'));
    var data = con.getImageData(topleft[0], topleft[1], dimensions[0], dimensions[1]);
    /** @type {*} */ (osc_con.putImageData(data, 0, 0));
    return osc.toDataURL(codec);
};
