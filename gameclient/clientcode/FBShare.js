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
    Check if FB Sharing is available.
    Works when the game is hosted on FB Canvas AND when on Battlehouse (using the Battlehouse SSO app). */
FBShare.supported = function() {
    return (spin_frame_platform == 'fb' || (spin_frame_platform == 'bh' && !!spin_battlehouse_fb_app_id));
};

/* Note: by default, we share an Open Graph object that consists of a
   synthetic URL served by the game server, and that allows us to attach
   arbitrary text/image.

   But, if the "url" parameter is passed in Options, then we share
   that URL instead (e.g. for BH friend invites). In this case, only the
   fields "url", "ref", and "message" are used. Everything else will come
   from Facebook crawling the Open Graph tags on the destination URL. */

/** @typedef {{ref: string,
               name: (string|undefined),
               url: (string|undefined),
               link_qs: (Object.<string,string>|undefined),
               message: (string|undefined),
               description: (string|undefined),
               picture: (string|undefined)}} */
FBShare.Options;

/** @private
    @return {string} */
FBShare.default_picture = function() {
    var common = /** @type {string} */ (gamedata['virals']['common_image_path']);
    common += /** @type {string} */ (gamedata['virals']['default_image']);
    return common;
};

/** Use Facebook "Share" dialog.
    @suppress {reportUnknownTypes} - Closure doesn't deal with the nested callbacks well
    @private
    @param {!FBShare.Options} options */
FBShare.invoke_share = function(options) {
    var url;
    if(options.url) {
        if(options.name) { throw Error('parameter "name" will be ignore'); }
        if(options.link_qs) { throw Error('parameter "link_qs" will be ignore'); }
        if(options.description) { throw Error('parameter "description" will be ignore'); }
        if(options.picture) { throw Error('parameter "picture" will be ignore'); }
        url = options.url;
    } else {
        // these are the properties of the OGPAPI object we'll create (server-side)
        if(!options.name) { throw Error('mandatory parameter "name" missing'); }
        if(!options.ref) { throw Error('mandatory parameter "ref" missing'); }
        var props = {'type':'literal', // note: no game_id prefix on this OG object
                     'frame_platform': spin_frame_platform,
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
        url = ogpapi_url(props);
    }

    if(player.is_developer()) {
        console.log('(DEV) Share URL: '+url);
    }

    metric_event('7270_feed_post_attempted', {'method':options.ref, 'api':'share',
                                              'sum': player.get_denormalized_summary_props('brief')});

    if(spin_frame_platform == 'fb') {
        if(!spin_facebook_enabled) { console.log('FBShare.invoke_share: '+url); return; }

        var fb_ui_param = {'method': 'share',
                           'href': url,
                           'show_error': !spin_secure_mode || player.is_developer()};
        var fb_ui_cb = /** @param {!FBShare.Options} _options */
            (function (_options) {
                return /** @type {function(?Object.<string,string>)} */ (function(result) {
                    if(result && ('post_id' in result)) {
                        metric_event('7271_feed_post_completed',
                                     {'method':_options.ref, 'api':'share',
                                      'facebook_post_id':result['post_id'],
                                      'sum': player.get_denormalized_summary_props('brief')});
                        send_to_server.func(["FB_FEED_POST_COMPLETED", {'method': _options.ref}]);
                    }
                }); })(options);

        // we need to have the publish_actions permission for this to work
        call_with_facebook_permissions('publish_actions', (function (_fb_ui_param, _fb_ui_cb) { return function() {
            SPFB.ui(_fb_ui_param, _fb_ui_cb);
        }; })(fb_ui_param, fb_ui_cb));

    } else if(spin_frame_platform == 'bh' && spin_battlehouse_fb_app_id) {
            // if Facebook SDK is loaded, use that
            if(window['FB']) {
                var fb_ui_params = {
                    'method': 'share',
                    'href': url,
                    'mobile_iframe': (screen.width < 768) // detect mobile?
                }
                if(options.message) {
                    fb_ui_params['quote'] = options.message;
                }
                FB.ui(fb_ui_params, function(response) {
                    // since we aren't actually logged in to Facebook, we won't get a response.
                    if(player.is_developer()) {
                        console.log('(DEV) response:');
                        console.log(response);
                    }
                });
            } else {
                // iframe doesn't require Facebook SDK
                var fb_share_url = 'https://www.facebook.com/dialog/share' +
                    '?app_id='+spin_battlehouse_fb_app_id+
                    '&display=iframe'+
                    '&href='+encodeURIComponent(url);
//            '&redirect_uri='+encodeURIComponent('https://www.battlehouse.com/');
                if(options.message) {
                    fb_share_url += '&quote='+encodeURIComponent(options.message);
                }
                var handle = window.open(fb_share_url, 'Share', 'width=600,height=425');
                if(handle && handle.focus) { handle.focus(); }
            }

    } else {
        throw Error('not supported');
    }
};

/** Main entry point
    @param {!FBShare.Options} options */
FBShare.invoke = function(options) {
    if(!FBShare.supported()) { throw Error('FBShare not supported on this platform'); }
    if(options.ref.length > 15) { throw Error('ref too long: "'+options.ref+'"'); }
    return FBShare.invoke_share(options);
};
