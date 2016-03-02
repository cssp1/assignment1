'use strict';

/** @fileoverview
    @suppress {reportUnknownTypes}
*/

var TYPED_OK =  (typeof Uint8Array !== 'undefined') &&
                (typeof Uint16Array !== 'undefined') &&
                (typeof Int32Array !== 'undefined');

/** @param {...?} obj */
exports.assign = function (obj /*from1, from2, from3, ...*/) {
  var sources = Array.prototype.slice.call(arguments, 1);
  while (sources.length) {
    var source = sources.shift();
    if (!source) { continue; }

    if (typeof source !== 'object') {
      throw new TypeError(source + 'must be non-object');
    }

    for (var p in source) {
      if (source.hasOwnProperty(p)) {
        obj[p] = source[p];
      }
    }
  }

  return obj;
};


// reduce buffer size, avoiding mem copy
exports.shrinkBuf = function (buf, size) {
  if (buf.length === size) { return buf; }
  if (buf.subarray) { return buf.subarray(0, size); }
  buf.length = size;
  return buf;
};


var fnTyped = {
  arraySet: function (dest, src, src_offs, len, dest_offs) {
    if (src.subarray && dest.subarray) {
      dest.set(src.subarray(src_offs, src_offs + len), dest_offs);
      return;
    }
    // Fallback to ordinary array
    for (var i = 0; i < len; i++) {
      dest[dest_offs + i] = src[src_offs + i];
    }
  },
  // Join array of chunks to single array.
  flattenChunks: function (chunks) {
    var i, l, len, pos, chunk, result;

    // calculate data length
    len = 0;
    for (i = 0, l = chunks.length; i < l; i++) {
      len += chunks[i].length;
    }

    // join chunks
    result = new Uint8Array(len);
    pos = 0;
    for (i = 0, l = chunks.length; i < l; i++) {
      chunk = chunks[i];
      result.set(chunk, pos);
      pos += chunk.length;
    }

    return result;
  }
};

var fnUntyped = {
  arraySet: function (dest, src, src_offs, len, dest_offs) {
    for (var i = 0; i < len; i++) {
      dest[dest_offs + i] = src[src_offs + i];
    }
  },
  // Join array of chunks to single array.
  flattenChunks: function (chunks) {
    return [].concat.apply([], chunks);
  }
};


// Enable/Disable typed arrays use, for testing
//

/* DJM - This confuses Closure. Use runtime dispatch instead.
exports.setTyped = function (on) {
  if (on) {
    exports.Buf8  = Uint8Array;
    exports.Buf16 = Uint16Array;
    exports.Buf32 = Int32Array;
    exports.assign(exports, fnTyped);
  } else {
    exports.Buf8  = Array;
    exports.Buf16 = Array;
    exports.Buf32 = Array;
    exports.assign(exports, fnUntyped);
  }
};

exports.setTyped(TYPED_OK);
*/

/** @constructor @param {number} arg0 */
exports.Buf8 = function(arg0) { return (TYPED_OK ? new Uint8Array(arg0) : new Array(arg0)); };
/** @constructor @param {number} arg0 */
exports.Buf16 = function(arg0) { return (TYPED_OK ? new Uint16Array(arg0) : new Array(arg0)); };
/** @constructor @param {number} arg0 */
exports.Buf32 = function(arg0) { return (TYPED_OK ? new Int32Array(arg0) : new Array(arg0)); };
/** @param {?} arg0
    @param {?} arg1
    @param {?} arg2
    @param {?} arg3
    @param {?} arg4 */
exports.arraySet = function(arg0,arg1,arg2,arg3,arg4) { return (TYPED_OK ? fnTyped.arraySet(arg0,arg1,arg2,arg3,arg4) : fnUntyped.arraySet(arg0,arg1,arg2,arg3,arg4)); };
/** @param {?} arg0 */
exports.flattenChunks = function(arg0) { return (TYPED_OK ? fnTyped.flattenChunks(arg0) : fnUntyped.flattenChunks(arg0)); };
