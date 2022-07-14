goog.provide('BHUserFingerprint');

// Copyright (c) 2022 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

/** @return {boolean} */
BHUserFingerprint.local_storage_enabled = function() {
    return (typeof(Storage) !== "undefined");
}

/** @return {string} */
BHUserFingerprint.master_key = function() {
    if(window.localStorage && window.localStorage.master_key) {
        return window.localStorage.master_key;
    }
    return 'undefined';
}

/** Set a fingerprinting master key sent by the server
 * @param {string} master_key
 */
BHUserFingerprint.set_master_key = function(master_key) {
    if(!(BHUserFingerprint.local_storage_enabled())) { return }
    window.localStorage.setItem('master_key', master_key);
}

/** collects configured timezone
 * @return {string}
 */
BHUserFingerprint.timezone = function() {
    var timezone = new Date().getTimezoneOffset().toString();
    if(timezone) { return timezone; }
    return 'undefined';
}

/** collects local time format
 * @return {string}
 */
BHUserFingerprint.date_format = function() {
    var time_zero = new Date(0);
    if(time_zero) { return time_zero.toLocaleDateString() + ', ' + time_zero.toLocaleTimeString(); }
    return 'undefined';
}

/** collects screen dimensions
 * @return {Array<number>|null}
 */
BHUserFingerprint.screen_size = function() {
    if(screen) {
        return [screen.width, screen.height];
    }
    return [-1,-1];
}

/** collects available screen dimensions
 * @return {Array<number>|null}
 */
BHUserFingerprint.screen_avail_size = function() {
    if(screen) {
        return [screen.availWidth, screen.availHeight];
    }
    return [-1,-1];
}

/** collects color depth
 * @return {number}
 */
BHUserFingerprint.color_depth = function() {
    if(screen) {
        return screen.colorDepth;
    }
    return -1;
}

/** collects pixel ratio
 * @return {number}
 */
BHUserFingerprint.pixel_ratio = function() {
    if(window.devicePixelRatio) {
        return window.devicePixelRatio;
    }
    return -1;
}

/** checks if cookies are enabled to the server
 * @return {boolean}
 */
BHUserFingerprint.cookies_enabled = function() {
    return (navigator && navigator.cookieEnabled);
}

/** collects user agent
 * @return {string}
 */
BHUserFingerprint.user_agent = function() {
    if(navigator && navigator.userAgent) {
        return navigator.userAgent.toString();
    }
    return 'undefined';
}

/** checks if device is a touch screen
 * @return {boolean}
 */
BHUserFingerprint.touch_compatibility = function() {
    return (navigator && navigator.maxTouchPoints && navigator.maxTouchPoints > 0) || (navigator && navigator.msMaxTouchPoints && navigator.msMaxTouchPoints > 0) || (window && 'ontouchstart' in window);
}

/** collects browser languages
 * @return {Array<string>}
 */
BHUserFingerprint.languages = function() {
    if(navigator && navigator.languages) {
        return navigator.languages;
    }
    return ['undefined'];
}

/** checks if browser is requesting do not track status
 * @return {boolean}
 */
BHUserFingerprint.do_not_track = function() {
    return (navigator && navigator.doNotTrack);
}

/** collects number of processors
 * @return {number}
 */
BHUserFingerprint.hardware_concurrency = function() {
    if(navigator && navigator.hardwareConcurrency) {
        return navigator.hardwareConcurrency;
    }
    return -1;
}

/** collects platform
 * @return {string}
 */
BHUserFingerprint.platform = function() {
    if(navigator && navigator.platform) {
        return navigator.platform;
    }
    return 'undefined';
}

/** collects browser plugins
 * @return {string}
 */
BHUserFingerprint.plugins = function() {
    if(navigator && navigator.plugins) {
        return navigator.plugins.toString();
    }
    return 'undefined';
}

/** collects webgl vendor information
 * @return {string}
 */
BHUserFingerprint.webgl_vendor = function() {
    var gl = document.createElement("canvas").getContext("webgl");
    if(gl) {
        var ext = gl.getExtension("WEBGL_debug_renderer_info");
        if(ext) { return gl.getParameter(ext.UNMASKED_VENDOR_WEBGL).toString(); }
    }
    return 'undefined';
}

/** collects webgl renderer information
 * @return {string}
 */
BHUserFingerprint.webgl_renderer = function() {
    var gl = document.createElement("canvas").getContext("webgl");
    if(gl) {
        var ext = gl.getExtension("WEBGL_debug_renderer_info");
        if(ext) { return gl.getParameter(ext.UNMASKED_RENDERER_WEBGL).toString(); }
    }
    return 'undefined';
}
