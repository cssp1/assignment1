// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

SPLWMetrics = {};

SPLWMetrics.prepare_props = function(event_name, props) {
    // sanitize prop values by removing semicolons so JSON encoder does not barf
    for(var key in props) {
        if(typeof(props[key]) === 'string') {
            if(props[key].indexOf(';') != -1) {
                var temp = props[key].split('');
                var newprop = '';
                for(var i = 0; i < temp.length; i++) {
                    var t = temp[i];
                    if(t == ';') {
                        newprop += '.';
                    } else {
                        newprop += t;
                    }
                }
                props[key] = newprop;
            }
            props[key] = unescape(encodeURIComponent(props[key])); // make Unicode JSON-safe
        }
    }
    var code = Number(event_name.slice(0,4));
    props['code'] = code;
};

SPLWMetrics.send_event = function(id, event_name, props) {
    if(typeof(JSON) == 'undefined') { return; } // don't barf on broken browsers
    SPLWMetrics.prepare_props(event_name, props);
    var msg = [id, event_name, props];
    console.log(['To Metrics'].concat(msg));

    // 1x1 inline GIF
    var img = new Image();
    var url_props = JSON.stringify(props);
    url_props = encodeURIComponent(url_props);
    var url = spin_metrics_url+'?event='+event_name+'&props='+url_props;
    if(id) { url += '&id='+id; }
    img.src = url;
};

SPLWMetrics.on_ajax = function (msg) {
    if(msg != 'ok') {
        console.log('metrics AJAX unexpected response: '+msg);
    }
};

// similar to the logger in main.js, but usable before it loads
SPLWMetrics.early_exception_sent = false;
SPLWMetrics.log_early_exception = function(e, where) {
    if(SPLWMetrics.early_exception_sent) { return; }
    SPLWMetrics.early_exception_sent = true;
    console.log('Exception thrown in '+where);
    var msg;
    if(e) {
        msg = e.toString();
        if(e.stack) {
            msg += '\nstack: '+e.stack.toString();
        }
        if(e.message) {
            msg += '\nmessage: '+e.message.toString();
        }
    } else {
        msg = 'none';
    }
    console.log(msg);
    var MAX_LEN = 1500;
    if(msg.length > MAX_LEN) { msg = msg.slice(0,MAX_LEN); }
    SPLWMetrics.send_event(spin_user_id, '0970_client_exception', add_demographics({'method':msg, 'location':where}));
};
