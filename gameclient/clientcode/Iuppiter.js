goog.provide('Iuppiter');

/**
$Id: Iuppiter.js 3026 2010-06-23 10:03:13Z Bear $

Copyright (c) 2010 Nuwa Information Co., Ltd, and individual contributors.
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

  1. Redistributions of source code must retain the above copyright notice,
     this list of conditions and the following disclaimer.

  2. Redistributions in binary form must reproduce the above copyright
     notice, this list of conditions and the following disclaimer in the
     documentation and/or other materials provided with the distribution.

  3. Neither the name of Nuwa Information nor the names of its contributors
     may be used to endorse or promote products derived from this software
     without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

$Author: Bear $
$Date: 2010-06-23 18:03:13 +0800 (星期三, 23 六月 2010) $
$Revision: 3026 $
*/

// SP3RDPARTY : Iuppiter.js : BSD License

var Iuppiter = {};

/**
 * Convert string value to a byte array.
 *
 * @param {string} input The input string value.
 * @return {Array} A byte array from string value.
 */
Iuppiter.string_to_bytes = function(input) {
    /* FIXED version from http://code.google.com/p/jslzjb/issues/detail?id=2 */
    var b = [];
    for(var i = 0; i < input.length; i++) {
        b.push(input.charCodeAt(i));
    }
    return b;
};

/**
 * Convert byte array to string
 *
 * @param {Array} input
 * @return {string}
 */
Iuppiter.bytes_to_string = function(input) {
    var ret = [];
    for(var i = 0; i < input.length; i++) {
        ret.push(String.fromCharCode(input[i]));
    }
    return ret.join('');
};

// Constants was used for compress/decompress function.

/** @const */ Iuppiter.NBBY = 8;
/** @const */ Iuppiter.MATCH_BITS = 6;
/** @const */ Iuppiter.MATCH_MIN = 3;
/** @const */ Iuppiter.MATCH_MAX = ((1 << Iuppiter.MATCH_BITS) + (Iuppiter.MATCH_MIN - 1));
/** @const */ Iuppiter.OFFSET_MAK = ((1 << (16 - Iuppiter.MATCH_BITS)) - 1);
/** @const */ Iuppiter.LEMPEL_SIZE = 256;

/**
 * Compress string or byte array using fast and efficient algorithm.
 *
 * Because of weak of javascript's natural, many compression algorithm
 * become useless in javascript implementation. The main problem is
 * performance, even the simple Huffman, LZ77/78 algorithm will take many
 * many time to operate. We use LZJB algorithm to do that, it suprisingly
 * fulfills our requirement to compress string fastly and efficiently.
 *
 * Our implementation is based on
 * http://src.opensolaris.org/source/raw/onnv/onnv-gate/
 * usr/src/uts/common/os/compress.c
 * It is licensed under CDDL.
 *
 * Please note it depends on toByteArray utility function.
 *
 * @param {Array} sstart The byte array that you want to compress.
 * @return {Array} Compressed byte array.
 */

// *note*! original length is prepended to byte array as a 4-byte quantity! this makes it incompatible with the "official" function!

Iuppiter.compress = function(sstart) {
    var dstart = [], slen,
        src = 0, dst = 0,
        cpy, copymap,
        copymask = 1 << (Iuppiter.NBBY - 1),
        mlen, offset, hp;
    var lempel = new Array(Iuppiter.LEMPEL_SIZE);

    // Initialize Lempel array
    for(var i = 0; i < Iuppiter.LEMPEL_SIZE; i++)
        lempel[i] = 3435973836;

    slen = sstart.length;
    if(slen > 0xffffffff) { throw Error('input too long'); }

    // prepend uncompressed length
    dstart[dst++] = slen & 0xff;
    dstart[dst++] = (slen>>8) & 0xff;
    dstart[dst++] = (slen>>16) & 0xff;
    dstart[dst++] = (slen>>24) & 0xff;

    while (src < slen) {
        if ((copymask <<= 1) == (1 << Iuppiter.NBBY)) {
            if (dst >= slen - 1 - 2 * Iuppiter.NBBY) {
                // short output, just copy from beginning
                mlen = slen;
                src = 0; dst = 4; // <- prepended length
                for (; mlen; mlen--) {
                    dstart[dst++] = sstart[src++];
                }
                return dstart;
            }
            copymask = 1;
            copymap = dst;
            dstart[dst++] = 0;
        }
        if (src > slen - Iuppiter.MATCH_MAX) {
            dstart[dst++] = sstart[src++];
            continue;
        }
        hp = ((sstart[src] + 13) ^
              (sstart[src + 1] - 13) ^
              sstart[src + 2]) &
            (Iuppiter.LEMPEL_SIZE - 1);
        offset = (src - lempel[hp]) & Iuppiter.OFFSET_MAK;
        lempel[hp] = src;
        cpy = src - offset;
        if (cpy >= 0 && cpy != src &&
            sstart[src] == sstart[cpy] &&
            sstart[src + 1] == sstart[cpy + 1] &&
            sstart[src + 2] == sstart[cpy + 2]) {
            dstart[copymap] |= copymask;
            for (mlen = Iuppiter.MATCH_MIN; mlen < Iuppiter.MATCH_MAX; mlen++) {
                if (sstart[src + mlen] != sstart[cpy + mlen]) {
                    break;
                }
            }
            dstart[dst++] = ((mlen - Iuppiter.MATCH_MIN) << (Iuppiter.NBBY - Iuppiter.MATCH_BITS)) | (offset >> Iuppiter.NBBY);
            dstart[dst++] = offset;
            src += mlen;
        } else {
            dstart[dst++] = sstart[src++];
        }
    }
    return dstart;
};

/**
 * Decompress byte array using fast and efficient algorithm.
 *
 * Our implementation is based on
 * http://src.opensolaris.org/source/raw/onnv/onnv-gate/
 * usr/src/uts/common/os/compress.c
 * It is licensed under CDDL.
 *
 * @param {Array} sstart The byte array that you want to compress.
 * @return {Array} Decompressed byte array.
 */
Iuppiter.decompress = function(sstart) {
    var dstart = [], slen;
    var src = 0, dst = 0;
    var cpy, copymap;
    var copymask = 1 << (Iuppiter.NBBY - 1);
    var mlen, offset, i;

    slen = sstart.length;

    // parse length
    var original_length = (sstart[0] | (sstart[1]<<8) | (sstart[2]<<16) | (sstart[3]<<24));
    src += 4;

    if(sstart.length >= original_length) {
        // stored uncompressed
        return sstart.slice(src);
    }

    while (src < slen) {
        //console.log('HERE '+src+' '+slen+' '+Iuppiter.bytes_to_string(dstart));
        if ((copymask <<= 1) == (1 << Iuppiter.NBBY)) {
            copymask = 1;
            copymap = sstart[src++];
        }

        if (copymap & copymask) {
            mlen = (sstart[src] >> (Iuppiter.NBBY - Iuppiter.MATCH_BITS)) + Iuppiter.MATCH_MIN;
            offset = ((sstart[src] << Iuppiter.NBBY) | sstart[src + 1]) & Iuppiter.OFFSET_MAK;
            src += 2;
            cpy = dst - offset;
            if (cpy >= 0) {
                while (--mlen >= 0) {
                    dstart[dst++] = dstart[cpy++];
                }
            } else {
                throw Error('Decompression error');
            }
        } else {
            dstart[dst++] = sstart[src++];
        }
    }
    return dstart;
};

// convenience functions that work with JavaScript strings.

Iuppiter.compress_string = function(s) { return Iuppiter.compress(Iuppiter.string_to_bytes(s)); };
Iuppiter.decompress_string = function(s) { return Iuppiter.bytes_to_string(Iuppiter.decompress(s)); };

/*
Iuppiter.test = function() {
    for(var i = 0; i < 1000; i++) {
        var s = '';
        var len = Math.floor(500*Math.random());

        for(var c = 0; c < len; c++) {
            var mychar = String.fromCharCode(Math.floor(30 + (128-30)*Math.random()));
            var run = (Math.random() > 0.75 ? Math.floor(1+64*Math.random()) : 1);
            for(var r = 0; r < run; r++) {
                s += mychar;
            }
        }
        //s = 'HELLO WORLD-------------------------------------------------------------HIHIHIASDFASDF--';
        if(Iuppiter.bytes_to_string(Iuppiter.string_to_bytes(s)) != s) {
            console.log('STRING FAIL '+s);
        }
        var bytes = Iuppiter.string_to_bytes(s);
        var comp = Iuppiter.compress(bytes);
        var decomp = Iuppiter.decompress(comp);
        if(bytes.length != decomp.length) {
            console.log('LEN MISMATCH '+bytes.length+' '+decomp.length+' "'+s+'"');
        } else {
            for(var c = 0; c < decomp.length; c++) {
                if(bytes[c] != decomp[c]) {
                    console.log('FAIL AT '+c);
                }
            }
        }
        if(Iuppiter.bytes_to_string(decomp) != s) {
            console.log('FAIL '+s);
        }
    }
    console.log('done');
};
goog.exportSymbol('Iuppiter.test',Iuppiter.test);
*/
