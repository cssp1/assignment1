goog.provide('SPGzip');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes}
    It's not going to be possible to make this typesafe due to the CommonJS hack :(
*/

goog.require('goog.crypt.base64');

// Hack to import the pako CommonJS module into this goog.module code
// Affected by work-in-progress issue in the Closure compiler:
// https://github.com/google/closure-compiler/issues/1472
// The hack works as follows:
// - Plaintext code: we load the Browserified version of the library manually (see proxyserver)
// and then fake out base.js to pretend that it's been loaded. We rely on the Browserified
// code for the module to provide the global exported name.
// - Compiled code: we goog.require() the undocumented internal mangled module name
// so that Closure finds the source files and links up the type info.

goog.require('module$pako$index');

// For plaintext code, "pako" will already be defined by the pre-loaded Browserified code.
// For compiled code, we need to assign it ourselves using the mangled symbol name.

/** @suppress {duplicate} */
var pako;
if(pako === undefined) {
    pako = goog.module.get('module$pako$index');
}

/** @param {string} input
    @return {string} */
SPGzip.gzip_to_base64_string = function(input) {
    return goog.crypt.base64.encodeString(/** @type {string} */ (pako.gzip(input, {to: 'string'})));
};
/** @param {string} input
    @return {string} */
SPGzip.gunzip_from_base64_string = function(input) {
    return /** @type {string} */ (pako.ungzip(goog.crypt.base64.decodeString(input), {to: 'string'}));
};
