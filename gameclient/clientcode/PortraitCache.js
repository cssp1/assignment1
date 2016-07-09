goog.provide('PortraitCache');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// cache of HTML Image objects representing Facebook portraits, to
// minimize number of instantiated objects.

/** @type {!Object<string, !HTMLImageElement>} */
PortraitCache.images_by_url = {};

/** @type {number} */
PortraitCache.invalidation_gen = 0;

/** @param {string} url
    @return {HTMLImageElement} */
PortraitCache.get_raw_image = function(url) {
    if(!(url in PortraitCache.images_by_url)) {
        var image = new Image();
        image.crossOrigin = 'Anonymous';
        // append a "generation" number to force the browser to re-retrieve the image after an invalidation
        // (just swapping .src to the same URL won't work, regardless of HTTP cache header settings)
        image.src = url + (url.indexOf('?') > 0 ? '&' : '?') + 'gen='+(PortraitCache.invalidation_gen.toString());
        PortraitCache.images_by_url[url] = image;
    }
    return PortraitCache.images_by_url[url];
};

/** @param {string} url */
PortraitCache.invalidate_url = function(url) {
    if(url in PortraitCache.images_by_url) {
        delete PortraitCache.images_by_url[url];
        PortraitCache.invalidation_gen += 1;
    }
};
