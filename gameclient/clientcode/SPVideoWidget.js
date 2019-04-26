goog.provide('SPVideoWidget');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    div-based widget that plays a YouTube video
*/

goog.require('GameArt');

/** @type {HTMLDivElement|null} */
SPVideoWidget.div = null;
/** @type {HTMLImageElement|null} */
SPVideoWidget.close_button = null;
/** @type {function()|null} */
SPVideoWidget.onclose = null;

/** @param {string} key
    @return {string}
    Given a YouTube video key name like "34gGxdfsdf", construct the URL string to bring up that video in an embedded player.
*/
SPVideoWidget.make_youtube_url = function(key) {
    var ret = 'http://www.youtube.com/embed/'+key+'?html5=1&autoplay=1&enablejsapi=1&hd=1&modestbranding=1&rel=0&theme=dark';
    if(spin_server_host != 'localhost') {
        ret += '&origin='+spin_server_protocol+spin_server_host+':'+spin_server_port;
    }
    return ret;
};

/** @param {function()} onclose
    Internal function - this sets up an HTML div to hold a video player on top of the game window.
 */
SPVideoWidget._init_div = function(onclose) {
    SPVideoWidget.onclose = onclose;

    SPVideoWidget.div = /** @type {HTMLDivElement} */ (document.createElement('div'));
    SPVideoWidget.div.style.backgroundColor = '#2c2c2c';
    SPVideoWidget.div.style.backgroundImage = 'url('+GameArt.art_url(gamedata['art']['dialog_video_widget']['states']['normal']['images'][0], false)+')';
    SPVideoWidget.div.style.position = 'absolute';
    /*
    SPVideoWidget.div.style.left = '25%';
    */
    SPVideoWidget.div.style.left = '0px';
    SPVideoWidget.div.style.right = '0px';
    SPVideoWidget.div.style.top = '70px';
    SPVideoWidget.div.style.margin = '0px auto 0px auto';
    /*
    SPVideoWidget.div.style.width = '50%';
    SPVideoWidget.div.style.height = '50%';
    SPVideoWidget.div.style.minWidth = '670px';
    SPVideoWidget.div.style.minHeight = '510px';
    */
    SPVideoWidget.div.style.width = '736px';
    SPVideoWidget.div.style.height = '423px';

    //SPVideoWidget.div.style.align = 'center';
    //SPVideoWidget.div.style.textAlign = 'center';
};

/** Internal function - add close button and finalize the video player div for display. */
SPVideoWidget._init_finish = function() {
    SPVideoWidget.close_button = /** @type {HTMLImageElement} */ (document.createElement('img'));
    SPVideoWidget.close_button.crossOrigin = 'Anonymous';
    SPVideoWidget.close_button.src = GameArt.art_url(gamedata['art']['close_button']['states']['normal']['images'][0], false);
    SPVideoWidget.close_button.style.position = 'absolute';
    SPVideoWidget.close_button.style.right = '1px';
    SPVideoWidget.close_button.style.top = '0%';
    SPVideoWidget.close_button.onclick = function(event) {
        if(SPVideoWidget.div) {
            document.body.removeChild(SPVideoWidget.div);
            SPVideoWidget.div = null;
        }
        if(SPVideoWidget.onclose) {
            SPVideoWidget.onclose();
            SPVideoWidget.onclose = null;
        }
    };
    SPVideoWidget.div.appendChild(SPVideoWidget.close_button);

    document.body.appendChild(SPVideoWidget.div);
};

/** @param {string} video_url
    @param {function()} onclose

    Start up a video player div featuring an embedded YouTube player.
*/
SPVideoWidget.init_youtube = function(video_url, onclose) {

    SPVideoWidget._init_div(onclose);

    var iframe = /** @type {HTMLIFrameElement} */ (document.createElement('iframe'));
    iframe.allowfullscreen = true;
    iframe.allowscriptaccess = true;
    iframe.frameborder = '0';
    iframe.style.position = 'relative';
    iframe.style.top = '30px';
    iframe.style.left = '48px';
    iframe.style.width = '640px';
    iframe.style.height = '360px';
    iframe.src = video_url;
    SPVideoWidget.div.appendChild(iframe);

    SPVideoWidget._init_finish();
};

/** @param {string} gif_url
    @param {number} gif_width
    @param {number} gif_height
    @param {function()} onclose

    Start up a video player div featuring an animated GIF.
*/
SPVideoWidget.init_gif = function(gif_url, gif_width, gif_height, onclose) {

    SPVideoWidget._init_div(onclose);

    var image = /** @type {HTMLImageElement} */ (document.createElement('img'));
    // XXXXXX add CSS style as necessary to center the GIF image
    //image.style.width = '640px';
    //image.style.height = '360px';
    image.src = gif_url;
    SPVideoWidget.div.appendChild(image);

    SPVideoWidget._init_finish();
};
