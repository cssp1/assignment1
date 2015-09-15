goog.provide('lz4');

// https://github.com/pierrec/node-lz4/blob/master/lib/decoder-js.js

// Copyright (c) 2012 Pierre Curto

// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:

// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.

// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

// SP3RDPARTY : lz4.js : MIT License

/** @param {!Array} input (ByteArray)
    @return {!Array} */
lz4.decompress = function(input) {
    var original_length = (input[0] | (input[1]<<8) | (input[2]<<16) | (input[3]<<24));
    var output = [];
    var i = 4;
    var n = input.length;
    var j = 0;
    while(i < n) {
        /** @type {number} */
        var token = input[i++];
        var literals_length = (token >> 4);
        for(var l = literals_length+240; l === 255; literals_length += (l = /** @type {number} */ (input[i++]))) {}
        if(literals_length > 0) {
            var end = i + literals_length;
            while (i < end) { output[j++] = input[i++]; }
        }
        if(i === n) { break; }

        var offset = input[i++] | (input[i++]<<8);
        if(offset === 0) { throw Error('uncompress error'); }
        var match_length = (token & 0xf);
        for(var l = match_length+240; l === 255; match_length += (l = /** @type {number} */ (input[i++]))) {}
        match_length += 4;
        var pos = j - offset;
        var end = j + match_length;
        while(j < end) { output[j++] = output[pos++]; }
    }
    return output;
};
