<div id="fb-root"></div>
<script type="text/javascript">
var spin_facebook_sdk_loaded = false;
var spin_facebook_sdk_on_init_callbacks = [];

window.fbAsyncInit = function() {
    FB.init({appId: spin_battlehouse_fb_app_id,
             version: 'v2.8',
             xfbml: true});
    spin_facebook_sdk_loaded = true;
    for(var i = 0; i < spin_facebook_sdk_on_init_callbacks; i++) {
        var cb = spin_facebook_sdk_on_init_callbacks[i];
        cb();
    }
};

(function(d, s, id){
    var js, fjs = d.getElementsByTagName(s)[0];
    if (d.getElementById(id)) {return;}
    js = d.createElement(s); js.id = id;
    js.src = "//connect.facebook.net/en_US/sdk.js";
    fjs.parentNode.insertBefore(js, fjs);
}(document, 'script', 'facebook-jssdk'));
</script>
