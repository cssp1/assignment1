goog.provide('FBShare');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Facebook "Share" Dialog
    This references a ton of stuff from main.js. It's not a self-contained module.
*/

goog.require('SPFB');

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

/** Facebook's old legacy "feed" API
    @suppress {reportUnknownTypes} - Closure doesn't deal with the nested callbacks well
    @param {!FBShare.Options} p_options */
FBShare.invoke_feed = function(p_options) {
    if(!spin_facebook_enabled) { console.log('FBShare.invoke_feed: '+p_options.ref); return; }

    call_with_facebook_permissions('publish_actions',
        (function(options) { return function() {
            metric_event('7270_feed_post_attempted', {'method':options.ref, 'api':'feed'});
            var url = 'https://apps.facebook.com/'+spin_app_namespace+'/?spin_ref='+options.ref+'&spin_ref_user_id='+spin_user_id.toString();
            if(options.link_qs) {
                for(var k in options.link_qs) {
                    url += '&'+k+'='+encodeURIComponent(options.link_qs[k]);
                }
            }
            if(player.is_developer()) {
                console.log(url);
            }

            SPFB.ui({'method': 'feed',
                     'name': options.name || null,
                     'message': options.message || null,
                     'description': options.description || null,
                     'link': url,
                     'picture': options.picture || FBShare.default_picture(),
                     'ref': options.ref,
                     'show_error': !spin_secure_mode || player.is_developer()},

                    /** @param {!FBShare.Options} _options */
                    (function (_options) {
                        return /** @type {function(?Object.<string,string>)} */ (function(result) {
                            if(result && ('post_id' in result)) {
                                metric_event('7271_feed_post_completed',
                                             {'method':_options.ref, 'api':'feed',
                                              'facebook_post_id':result['post_id']});
                            }
                        }); })(options)
                   );
        }; })(p_options));
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
    metric_event('7270_feed_post_attempted', {'method':options.ref, 'api':'share'});

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
                                      'facebook_post_id':result['post_id']});
                    }
                }); })(options)
           );
};

/** Old legacy method
    @param {!FBShare.Options} options */
FBShare.invoke = function(options) {
    if(options.ref.length > 15) { throw Error('ref too long: "'+options.ref+'"'); }

    var api = /** @type {?string} */ (gamedata['virals']['facebook_api']) || 'feed';
    if(api == 'feed') {
        FBShare.invoke_feed(options);
    } else if(api == 'share') {
        FBShare.invoke_share(options);
    } else {
        throw Error('unknown api '+api);
    }
};
