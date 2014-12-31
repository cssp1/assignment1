goog.provide('SPHTTP');

// Copyright (c) 2014 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// wrap/unwrap Unicode text strings for safe transmission across the AJAX connection
// mirrors gameserver/SpinHTTP.py

goog.require('goog.crypt.base64');

var SPHTTP = {
    wrap_string: function(str) {
        // note: to make it safe for the AJAX post, use UTF-8 wrapped inside base64!
        // JavaScript string -> UTF-8 conversion from http://ecmanaut.blogspot.com/2006/07/encoding-decoding-utf8-in-javascript.html
        var utf8_str = unescape(encodeURIComponent(str));
        var encoded_str = goog.crypt.base64.encodeString(utf8_str);
        return encoded_str;
    },
    unwrap_string: function(input) {
        var utf8_body = goog.crypt.base64.decodeString(input);
        // UTF-8 -> JavaScript string see http://ecmanaut.blogspot.com/2006/07/encoding-decoding-utf8-in-javascript.html
        var body = decodeURIComponent(escape(utf8_body));
        return body;
    }
};
