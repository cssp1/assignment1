goog.provide('FBShare');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Facebook "Share" Dialog
    This references a ton of stuff from main.js. It's not a self-contained module.
*/

goog.require('SPFB');

/** @return {boolean}
    Check if FB Sharing is available. Works when the game is hosted on FB Canvas,
    AND when on Battlehouse. */
FBShare.supported = function() {
    return (spin_frame_platform == 'fb' || (spin_frame_platform == 'bh' && spin_battlehouse_fb_app_id));
};

/** @typedef {{ref: string,
               name: string,
               link_qs: (Object.<string,string>|undefined),
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

/** Facebook's new "Share" dialog
    @suppress {reportUnknownTypes} - Closure doesn't deal with the nested callbacks well
    @param {!FBShare.Options} options */
FBShare.invoke_share = function(options) {
    // these are the properties of the OGPAPI object we'll create (server-side)
    var props = {'type':'literal', // note: no game_id prefix on this OG object
                 'ui_name': options.name,
                 'spin_ref': options.ref,
                 'spin_ref_user_id': spin_user_id.toString(),
                 'image_url': options.picture || FBShare.default_picture()};
    if(options.description) {
        props['ui_description'] = options.description;
    }
    if(options.link_qs) {
        props['spin_link_qs'] = JSON.stringify(options.link_qs);
    }

    var url = ogpapi_url(props);
    if(player.is_developer()) {
        console.log(props);
        console.log(url);
    }
    metric_event('7270_feed_post_attempted', {'method':options.ref, 'api':'share',
                                              'sum': player.get_denormalized_summary_props('brief')});

    if(!spin_facebook_enabled) { console.log('FBShare.invoke_share: '+url); return; }

    SPFB.ui({'method': 'share',
             'href': url,
             'show_error': !spin_secure_mode || player.is_developer()},

            /** @param {!FBShare.Options} _options */
            (function (_options) {
                return /** @type {function(?Object.<string,string>)} */ (function(result) {
                    if(result && ('post_id' in result)) {
                        metric_event('7271_feed_post_completed',
                                     {'method':_options.ref, 'api':'share',
                                      'facebook_post_id':result['post_id'],
                                      'sum': player.get_denormalized_summary_props('brief')});
                    }
                }); })(options)
           );
};

/** Main entry point
    @param {!FBShare.Options} options */
FBShare.invoke = function(options) {
    if(!FBShare.supported()) { throw Error('FBShare not supported on this platform'); }
    if(options.ref.length > 15) { throw Error('ref too long: "'+options.ref+'"'); }
    return FBShare.invoke_share(options);
};
