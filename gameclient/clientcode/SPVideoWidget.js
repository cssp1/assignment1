goog.provide('SPVideoWidget');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('GameArt');

SPVideoWidget = { div: null, onclose: null };

SPVideoWidget.make_youtube_url = function(key) {
    return 'http://www.youtube.com/embed/'+key+'?html5=1&autoplay=1&enablejsapi=1&hd=1&modestbranding=1&rel=0&theme=dark&origin='+spin_server_protocol+spin_server_host+':'+spin_server_port;
};

SPVideoWidget.init = function(video_url, onclose) {
    SPVideoWidget.onclose = onclose;

    SPVideoWidget.div = document.createElement('div');
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

    if(1) {
        SPVideoWidget.iframe = document.createElement('iframe');
        SPVideoWidget.iframe.allowfullscreen = true;
        SPVideoWidget.iframe.allowscriptaccess = true;
        SPVideoWidget.iframe.frameborder = '0';
        SPVideoWidget.iframe.style.position = 'relative';
        SPVideoWidget.iframe.style.top = '30px';
        SPVideoWidget.iframe.style.left = '48px';
        SPVideoWidget.iframe.style.width = '640px';
        SPVideoWidget.iframe.style.height = '360px';
        SPVideoWidget.iframe.src = video_url;
        SPVideoWidget.div.appendChild(SPVideoWidget.iframe);
    }

    SPVideoWidget.close_button = document.createElement('img');
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
