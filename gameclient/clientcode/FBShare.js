goog.provide('FBShare');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Facebook "Share" Dialog
    This references a ton of stuff from main.js. It's not a self-contained module.
*/

goog.require('SPFB');

/** @typedef {{link: string,
               ref: string,
               name: (string|undefined),
               message: (string|undefined),
               description: (string|undefined),
               picture: (string|undefined)}} */
FBShare.Options;

/** @return {string} */
FBShare.default_picture = function() {
    var common = /** @type {string} */ (gamedata['virals']['common_image_path']);
    common += /** @type {string} */ (gamedata['virals']['default_image']);
    return common;
};

/** Old legacy method
    @suppress {reportUnknownTypes} - Closure doesn't deal with the nested callbacks well
    @param {!FBShare.Options} p_options */
FBShare.invoke_feed = function(p_options) {
    call_with_facebook_permissions('publish_actions',
        (function(options) { return function() {
            metric_event('7270_feed_post_attempted', {'method':options.ref});
            SPFB.ui({'method': 'feed',
                     'name': options.name || null,
                     'message': options.message || null,
                     'description': options.message || null,
                     'link': options.link,
                     'picture': options.picture || FBShare.default_picture(),
                     'ref': options.ref,
                     'show_error': !spin_secure_mode || player.is_developer()},

                    /** @param {!FBShare.Options} _options */
                    (function (_options) {
                        return /** @type {function(?Object.<string,string>)} */ (function(result) {
                            if(result && ('post_id' in result)) {
                                metric_event('7271_feed_post_completed',
                                             {'method':_options.ref, 'facebook_post_id':result['post_id']});
                            }
                        }); })(options)
                   );
        }; })(p_options));
};

/** New "Share" dialog
    @param {!FBShare.Options} options */
FBShare.invoke_share = function(options) {
    throw Error('not implemented');
};

/** Old legacy method
    @param {!FBShare.Options} options */
FBShare.invoke = function(options) {
    if(!spin_facebook_enabled) { console.log('FBShare.invoke: '+options.link); return; }

    if(true) {
        FBShare.invoke_feed(options);
    } else {
        FBShare.invoke_share(options);
    }
};
