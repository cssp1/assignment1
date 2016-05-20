goog.provide('SPGzip');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes}
    It's not going to be possible to make this typesafe due to the CommonJS hack :(
*/

// Hack to import the pako CommonJS module into this goog.module code
// Affected by work-in-progress issue in the Closure compiler:
// https://github.com/google/closure-compiler/issues/1472
// The hack works as follows:
// - Plaintext code: we load the Browserified version of the library manually (see proxyserver)
// and then fake out base.js to pretend that it's been loaded under the mangled module name.
// - Compiled code: we require() the true module name
// so that Closure finds the source files and links up the type info.

// Note: for plaintext code, "pako" will already be defined by the pre-loaded Browserified code.
// For compiled code, we need to assign it ourselves.

SPGzip.pako = (typeof(pako) === 'undefined' ? require('../pako') : pako);

/** @param {!Array<number>|Uint8Array} input
    @return {!Array<number>|Uint8Array} */
SPGzip.gzip = function(input) {
    return /** @type {!Array<number>|Uint8Array} */ (SPGzip.pako.gzip(input));
};
/** @param {!Array<number>|Uint8Array} input
    @return {!Array<number>|Uint8Array} */
SPGzip.gunzip = function(input) {
    return /** @type {!Array<number>|Uint8Array} */ (SPGzip.pako.ungzip(input));
};
