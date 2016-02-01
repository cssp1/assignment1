<script type="text/javascript">
var spin_xsolla_sdk_loaded = false;
(function(d){
    var js, id = "xsolla-jssdk"; if (d.getElementById(id)) {return;}
    js = d.createElement("script"); js.id = id; js.async = true;
    js.src = "//static.xsolla.com/embed/paystation/1.0.1/widget.min.js";
    js.addEventListener('load', function(e) {
        spin_xsolla_sdk_loaded = true;
    }, false);
    d.getElementsByTagName("body")[0].appendChild(js);
}(document));
</script>
