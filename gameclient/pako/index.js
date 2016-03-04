// SP3RDPARTY : pako JavaScript compression library : MIT License

// Top level file is just a mixin of submodules & constants
'use strict';

var assign    = require('./lib/utils/common').assign;

var deflate   = require('./lib/deflate');
var inflate   = require('./lib/inflate');
var constants = require('./lib/zlib/constants');

// DJM - Closure has a hard time understanding what assign() does.
//var pako = {};
//assign(pako, deflate, inflate, constants);

module.exports = {Deflate: deflate.Deflate,
                  deflate: deflate.deflate,
                  deflateRaw: deflate.deflateRaw,
                  gzip: deflate.gzip,
                  Inflate: inflate.Inflate,
                  inflate: inflate.inflate,
                  inflateRaw: inflate.inflateRaw,
                  ungzip: inflate.inflate};
