goog.provide('SPStringCoding');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// utilities for converting between native JavaScript strings, UTF-8 byte arrays,
// and "binstrings" (native JavaScript strings of raw byte values, not displayable).

// based on pako.js (MIT license)

/** Trim array memory usage down to a specific size
    @param {!Uint8Array|Uint16Array|Array<number>} buf
    @param {number} size
    @return {!Uint8Array|Uint16Array|Array<number>} */
SPStringCoding.shrinkBuf = function(buf, size) {
    if (buf.length === size) { return buf; }
    if (buf.subarray) { return buf.subarray(0, size); }
    buf.length = size;
    return buf;
};

/** Allocate a (hopefully typed) byte array
    @param {number} size
    @return {!Uint8Array|Array<number>} */
SPStringCoding.Buf8 = function(size) {
    if(typeof Uint8Array !== 'undefined') {
        return new Uint8Array(size);
    } else {
        return new Array(size);
    }
};

// function checks for fast apply() string ops
/** @private */
SPStringCoding.STR_APPLY_OK = true;
/** @private */
SPStringCoding.STR_APPLY_UIA_OK = true;

try { String.fromCharCode.apply(null, [ 0 ]); } catch (__) { SPStringCoding.STR_APPLY_OK = false; }
try { String.fromCharCode.apply(null, new Uint8Array(1)); } catch (__) { SPStringCoding.STR_APPLY_UIA_OK = false; }


/** Table with utf8 lengths (calculated by first byte of sequence)
    Note, that 5 & 6-byte values and some 4-byte values can not be represented in JS,
    because max possible codepoint is 0x10ffff.
    @private
    @type {!Uint8Array|Array<number>} */
SPStringCoding._utf8len = SPStringCoding.Buf8(256);
for (var q = 0; q < 256; q++) {
    SPStringCoding._utf8len[q] = (q >= 252 ? 6 : q >= 248 ? 5 : q >= 240 ? 4 : q >= 224 ? 3 : q >= 192 ? 2 : 1);
}
SPStringCoding._utf8len[254] = SPStringCoding._utf8len[254] = 1; // Invalid sequence start


/** Convert native JavaScript string to UTF-8 byte array (typed, when possible)
    @param {string} str
    @return {!Uint8Array|Array<number>} */
SPStringCoding.js_string_to_utf8_array = function (str) {
    var buf, c, c2, m_pos, i, str_len = str.length, buf_len = 0;

    // count binary size
    for (m_pos = 0; m_pos < str_len; m_pos++) {
        c = str.charCodeAt(m_pos);
        if ((c & 0xfc00) === 0xd800 && (m_pos + 1 < str_len)) {
            c2 = str.charCodeAt(m_pos + 1);
            if ((c2 & 0xfc00) === 0xdc00) {
                c = 0x10000 + ((c - 0xd800) << 10) + (c2 - 0xdc00);
                m_pos++;
            }
        }
        buf_len += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
    }

    // allocate buffer
    buf = SPStringCoding.Buf8(buf_len);

    // convert
    for (i = 0, m_pos = 0; i < buf_len; m_pos++) {
        c = str.charCodeAt(m_pos);
        if ((c & 0xfc00) === 0xd800 && (m_pos + 1 < str_len)) {
            c2 = str.charCodeAt(m_pos + 1);
            if ((c2 & 0xfc00) === 0xdc00) {
                c = 0x10000 + ((c - 0xd800) << 10) + (c2 - 0xdc00);
                m_pos++;
            }
        }
        if (c < 0x80) {
            /* one byte */
            buf[i++] = c;
        } else if (c < 0x800) {
            /* two bytes */
            buf[i++] = 0xC0 | (c >>> 6);
            buf[i++] = 0x80 | (c & 0x3f);
        } else if (c < 0x10000) {
            /* three bytes */
            buf[i++] = 0xE0 | (c >>> 12);
            buf[i++] = 0x80 | (c >>> 6 & 0x3f);
            buf[i++] = 0x80 | (c & 0x3f);
        } else {
            /* four bytes */
            buf[i++] = 0xf0 | (c >>> 18);
            buf[i++] = 0x80 | (c >>> 12 & 0x3f);
            buf[i++] = 0x80 | (c >>> 6 & 0x3f);
            buf[i++] = 0x80 | (c & 0x3f);
        }
    }

    return buf;
};

/** Convert array of codepoints to native JavaScript string.
    @private
    @param {!Uint8Array|Uint16Array|Array<number>} buf
    @param {number} len - length to use, may be less than the full array length
    @return {string} */
SPStringCoding.construct_string_from_array = function (buf, len) {
    // use fallback for big arrays to avoid stack overflow
    if (len < 65537) {
        if ((buf.subarray && SPStringCoding.STR_APPLY_UIA_OK) || (!buf.subarray && SPStringCoding.STR_APPLY_OK)) {
            return String.fromCharCode.apply(null, SPStringCoding.shrinkBuf(buf, len));
        }
    }
    var result = '';
    for (var i = 0; i < len; i++) {
        result += String.fromCharCode(buf[i]);
    }
    return result;
};


/** Convert native JavaScript string to byte array, ignoring Unicode.
    The string should NOT have any characters outside the range 0-255!
    @private
    @param {string} str
    @return {!Uint8Array|Array<number>} */
SPStringCoding.construct_array_from_string = function (str) {
    var buf = SPStringCoding.Buf8(str.length);
    for (var i = 0, len = buf.length; i < len; i++) {
        var x = str.charCodeAt(i);
        if(x > 255) {
            throw Error('out-of-range codepoint');
        }
        buf[i] = x;
  }
  return buf;
};


/** Convert UTF-8 byte array to native JavaScript string
    @param {!Uint8Array|Array<number>} buf
    @param {number=} max
    @return {string} */
SPStringCoding.utf8_array_to_js_string = function (buf, max) {
    var i, out;
    var len = max || buf.length;

    // Reserve max possible length (2 words per char)
    // NB: by unknown reasons, Array is significantly faster for
    //     String.fromCharCode.apply than Uint16Array.
    var utf16buf = new Array(len * 2);

    for (out = 0, i = 0; i < len;) {
        /** @type {number} */
        var c = buf[i++];

        // quick process ascii
        if (c < 0x80) { utf16buf[out++] = c; continue; }

        /** @type {number} */
        var c_len = SPStringCoding._utf8len[c];

        // skip 5 & 6 byte codes
        if (c_len > 4) { utf16buf[out++] = 0xfffd; i += c_len - 1; continue; }

        // apply mask on first byte
        c &= c_len === 2 ? 0x1f : c_len === 3 ? 0x0f : 0x07;
        // join the rest
        while (c_len > 1 && i < len) {
            c = (c << 6) | (buf[i++] & 0x3f);
            c_len--;
        }

        // terminated by end of string?
        if (c_len > 1) { utf16buf[out++] = 0xfffd; continue; }

        if (c < 0x10000) {
            utf16buf[out++] = c;
        } else {
            c -= 0x10000;
            utf16buf[out++] = 0xd800 | ((c >> 10) & 0x3ff);
            utf16buf[out++] = 0xdc00 | (c & 0x3ff);
        }
    }

    return SPStringCoding.construct_string_from_array(utf16buf, out);
};
