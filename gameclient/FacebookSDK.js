<div id="fb-root"></div>
<script>
var spin_facebook_sdk_loaded = false;
var spin_facebook_sdk_on_init_callbacks = [];
var spin_facebook_channel = spin_server_protocol+spin_server_host+":"+spin_server_port+"/channel.php";
window.fbAsyncInit = function() {
    var init_params = {
        appId      : spin_app_id, // App ID
        channelURL : spin_facebook_channel, // XD script channel file
        status     : true, // check login status
        cookie     : true, // enable cookies to allow the server to access the session
        oauth      : true, // enable OAuth 2.0
        xfbml      : true,  // parse XFBML
        frictionlessRequests : true
    };
    if(spin_facebook_api_versions && ('jssdk' in spin_facebook_api_versions)) {
        init_params.version = spin_facebook_api_versions['jssdk'];
    } else if(spin_facebook_api_versions && ('default' in spin_facebook_api_versions)) {
        init_params.version = spin_facebook_api_versions['default'];
    } else {
        init_params.version = 'v6.0'; // fallback default (sync with: FacebookSDK.js, fb_guest.html, gameserver/SpinFacebook.py, gameclient/clientcode/SPFB.js)
    }
    FB.init(init_params);
    spin_facebook_sdk_loaded = true;
    for(var i = 0; i < spin_facebook_sdk_on_init_callbacks; i++) {
        var cb = spin_facebook_sdk_on_init_callbacks[i];
        cb();
    }
    //window.setTimeout(function() { FB.Canvas.setAutoGrow(); }, 250);
};
(function(d){
    var js, id = "facebook-jssdk"; if (d.getElementById(id)) {return;}
    js = d.createElement("script"); js.id = id; js.async = true;
    js.src = "//connect.facebook.net/en_US/" + ((spin_facebook_api_versions && !spin_facebook_api_versions['jssdk']) ? "all.js" : "sdk.js");
    d.getElementsByTagName("head")[0].appendChild(js);
}(document));

// TrialPay SDK
// (function(d){
//     var js, id = "trialpay-jssdk"; if (d.getElementById(id)) {return;}
//     js = d.createElement("script"); js.id = id; js.async = true;
//     js.src = "//s-assets.tp-cdn.com/static3/js/api/payment_overlay.js";
//     d.getElementsByTagName("body")[0].appendChild(js);
// }(document));

</script>
