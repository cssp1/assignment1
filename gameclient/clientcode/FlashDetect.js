goog.provide('FlashDetect');

// Flash Detect library - http://featureblend.com/javascript-flash-detection-library.html

/**
 * Copyright (c) 2007, Carl S. Yestrau
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *     * Redistributions of source code must retain the above copyright
 *       notice, this list of conditions and the following disclaimer.
 *     * Redistributions in binary form must reproduce the above copyright
 *       notice, this list of conditions and the following disclaimer in the
 *       documentation and/or other materials provided with the distribution.
 *     * Neither the name of Feature Blend nor the
 *       names of its contributors may be used to endorse or promote products
 *       derived from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY Carl S. Yestrau ''AS IS'' AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
 * WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
 * DISCLAIMED. IN NO EVENT SHALL Carl S. Yestrau BE LIABLE FOR ANY
 * DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
 * (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 * LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
 * ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 */

// SP3RDPARTY : FlashDetect.js : BSD License

var FlashDetect = {
    cache: -1,
    detect: function() {
        if(FlashDetect.cache != -1) {
            return FlashDetect.cache;
        }

        var hasPlugin = false, n = navigator, nP = n['plugins'], obj, type, types, AX = window['ActiveXObject'];

        if (nP && nP.length) {
            type = 'application/x-shockwave-flash';
            types = n['mimeTypes'];
            if (types && types[type] && types[type]['enabledPlugin'] && types[type]['enabledPlugin']['description']) {
                hasPlugin = true;
            }
        } else if (typeof AX !== 'undefined') {
            try {
                obj = new AX('ShockwaveFlash.ShockwaveFlash');
            } catch(e) {
                // oh well
            }
            hasPlugin = (!!obj);
        }

        FlashDetect.cache = (hasPlugin ? 1 : 0);
        return FlashDetect.cache;
    }
};
