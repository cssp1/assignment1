// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// SPLWMetrics
var SPLWMetrics = {
    "prepare_props": function() {},
    "send_event": function () {}
};

// Global variables that are sent to the client by our proxyserver via proxy_index.html template replacements
var spin_pageload_begin;
var spin_demographics;
var spin_page_url;
var spin_game_container_url;
var spin_app_namespace;
var spin_app_id;
var spin_trialpay_vendor_id;
var spin_http_origin;
var spin_server_protocol;
var spin_server_host;
var spin_server_port;
var spin_server_http_port;
var spin_server_ssl_port;
var spin_game_server_host;
var spin_game_server_http_port;
var spin_game_server_ssl_port;
var spin_game_server_ws_port;
var spin_game_server_wss_port;
var spin_game_query_string;
var spin_game_direct_connect;
var spin_game_use_websocket;
var spin_ajax_config;
var spin_metrics_url;
var spin_metrics_anon_id;
var spin_is_returning_user;
var spin_user_id;
var spin_login_country;
var spin_session_id;
var spin_session_time;
var spin_session_signature;
var spin_session_data;
/** @type {boolean} */
var spin_secure_mode;
var spin_kissmetrics_enabled;
var spin_frame_platform;
var spin_social_id;
var spin_kongregate_enabled;
var spin_kongregate_user;
/** @type {boolean} */
var spin_facebook_enabled;
/** @type {string} */
var spin_facebook_user;
var spin_facebook_signed_request;
/** @type {string} */
var spin_facebook_oauth_token;
var spin_facebook_login_permissions;
var spin_facebook_api_versions;
var spin_art_protocol;
var spin_art_path;
var spin_unsupported_browser_landing;
var spin_loading_screen_name;
var spin_loading_screen_data;
var spin_loading_screen_mode;
var spin_init_messages;

/** @param {!Object.<string,?>} props
    @return {!Object.<string,?>} */
var add_demographics = function(props) {};

/** @type {Object.<string,?>} */
var gamedata; // from gamedata.js
var gameclient_build_date; // from compiled-client.js.date

var console;

/** @type {boolean} from XsollaSDK.js */
var spin_xsolla_sdk_loaded;

// Facebook API
var FB = {
    "ui": function() {},
    "init": function() {},
    "api": function() {},
    "getLoginStatus": function() {},
    "AppEvents": {
        "activateApp": function() {},
        "logEvent": function() {},
        "EventNames": function() {},
        "ParameterNames": function() {}
    },
    "Canvas": {
        "setSize": function() {},
        "setAutoGrow": function() {},
        "getPageInfo": function() {}
    }
};

// Kongregate API
var kongregate = {
    "mtx": {
        "purchaseItemsRemote": function() {}
    },
    "services": {
        "showInvitationBox": function() {}
    }
};

// TrialPay API
var TRIALPAY = {
    "fb": {
        "show_overlay": function() {}
    }
};

// Xsolla API
var XPayStationWidget = {
    "init": function() {},
    "open": function() {},
    "on": function() {},
    "off": function() {}
};

// HTML5 audio stuff
var Audio;
var webkitAudioContext = {
    "currentTime": {},
    "destination": {},
    "createBuffer": function () {},
    "decodeAudioData": function () {},
    "createBufferSource": function () {},
    "createGainNode": function () {},
    "createGain": function () {}
};
var AudioContext = {
    "currentTime": {},
    "destination": {},
    "createBuffer": function () {},
    "decodeAudioData": function () {},
    "createBufferSource": function () {},
    "createGainNode": function () {},
    "createGain": function () {}
};

// JQuery
var $ = {
    "fn": {
        "init": function () {},
        "selector": {},
        "jquery": {},
        "size": function () {},
        "get": function () {},
        "pushStack": function () {},
        "setArray": function () {},
        "each": function () {},
        "index": function () {},
        "attr": function () {},
        "css": function () {},
        "text": function () {},
        "wrapAll": function () {},
        "wrapInner": function () {},
        "wrap": function () {},
        "append": function () {},
        "prepend": function () {},
        "before": function () {},
        "after": function () {},
        "end": function () {},
        "push": function () {},
        "sort": function () {},
        "splice": function () {},
        "find": function () {},
        "clone": function () {},
        "filter": function () {},
        "closest": function () {},
        "not": function () {},
        "add": function () {},
        "is": function () {},
        "hasClass": function () {},
        "val": function () {},
        "html": function () {},
        "replaceWith": function () {},
        "eq": function () {},
        "slice": function () {},
        "map": function () {},
        "andSelf": function () {},
        "domManip": function () {},
        "extend": function () {},
        "parent": function () {},
        "parents": function () {},
        "next": function () {},
        "prev": function () {},
        "nextAll": function () {},
        "prevAll": function () {},
        "siblings": function () {},
        "children": function () {},
        "contents": function () {},
        "appendTo": function () {},
        "prependTo": function () {},
        "insertBefore": function () {},
        "insertAfter": function () {},
        "replaceAll": function () {},
        "removeAttr": function () {},
        "addClass": function () {},
        "removeClass": function () {},
        "toggleClass": function () {},
        "remove": function () {},
        "empty": function () {},
        "data": function () {},
        "removeData": function () {},
        "queue": function () {},
        "dequeue": function () {},
        "bind": function () {},
        "one": function () {},
        "unbind": function () {},
        "trigger": function () {},
        "triggerHandler": function () {},
        "toggle": function () {},
        "hover": function () {},
        "ready": function () {},
        "live": function () {},
        "die": function () {},
        "blur": function () {},
        "focus": function () {},
        "load": function () {},
        "resize": function () {},
        "scroll": function () {},
        "unload": function () {},
        "click": function () {},
        "dblclick": function () {},
        "mousedown": function () {},
        "mouseup": function () {},
        "mousemove": function () {},
        "mouseover": function () {},
        "mouseout": function () {},
        "mouseenter": function () {},
        "mouseleave": function () {},
        "change": function () {},
        "select": function () {},
        "submit": function () {},
        "keydown": function () {},
        "keypress": function () {},
        "keyup": function () {},
        "error": function () {},
        "_load": function () {},
        "serialize": function () {},
        "serializeArray": function () {},
        "ajaxStart": function () {},
        "ajaxStop": function () {},
        "ajaxComplete": function () {},
        "ajaxError": function () {},
        "ajaxSuccess": function () {},
        "ajaxSend": function () {},
        "show": function () {},
        "hide": function () {},
        "_toggle": function () {},
        "fadeTo": function () {},
        "animate": function () {},
        "stop": function () {},
        "slideDown": function () {},
        "slideUp": function () {},
        "slideToggle": function () {},
        "fadeIn": function () {},
        "fadeOut": function () {},
        "offset": function () {},
        "position": function () {},
        "offsetParent": function () {},
        "scrollLeft": function () {},
        "scrollTop": function () {},
        "innerHeight": function () {},
        "outerHeight": function () {},
        "height": function () {},
        "innerWidth": function () {},
        "outerWidth": function () {},
        "width": function () {}
    },
    "extend": function () {},
    "noConflict": function () {},
    "isFunction": function () {},
    "isArray": function () {},
    "isXMLDoc": function () {},
    "globalEval": function () {},
    "nodeName": function () {},
    "each": function () {},
    "prop": function () {},
    "className": {
        "add": function () {},
        "remove": function () {},
        "has": function () {}
    },
    "swap": function () {},
    "css": function () {},
    "curCSS": function () {},
    "clean": function () {},
    "attr": function () {},
    "trim": function () {},
    "makeArray": function () {},
    "inArray": function () {},
    "merge": function () {},
    "unique": function () {},
    "grep": function () {},
    "map": function () {},
    "browser": {
        "version": {},
        "safari": {},
        "opera": {},
        "msie": {},
        "mozilla": {}
    },
    "cache": {
        "1": {
            "events": {
                "unload": {
                    "1": function () {}
                },
                "load": {
                    "2": function () {}
                }
            },
            "handle": function () {}
        },
        "2": function () {}
    },
    "data": function () {},
    "removeData": function () {},
    "queue": function () {},
    "dequeue": function () {},
    "find": function () {},
    "filter": function () {},
    "expr": {
        "order": {
            "0": {},
            "1": {},
            "2": {},
            "3": {}
        },
        "match": {
            "ID": function () {},
            "CLASS": function () {},
            "NAME": function () {},
            "ATTR": function () {},
            "TAG": function () {},
            "CHILD": function () {},
            "POS": function () {},
            "PSEUDO": function () {}
        },
        "attrMap": {
            "class": {},
            "for": {}
        },
        "attrHandle": {
            "href": function () {}
        },
        "relative": {
            "+": function () {},
            ">": function () {},
            "": function () {},
            "~": function () {}
        },
        "find": {
            "ID": function () {},
            "NAME": function () {},
            "TAG": function () {},
            "CLASS": function () {}
        },
        "preFilter": {
            "CLASS": function () {},
            "ID": function () {},
            "TAG": function () {},
            "CHILD": function () {},
            "ATTR": function () {},
            "PSEUDO": function () {},
            "POS": function () {}
        },
        "filters": {
            "enabled": function () {},
            "disabled": function () {},
            "checked": function () {},
            "selected": function () {},
            "parent": function () {},
            "empty": function () {},
            "has": function () {},
            "header": function () {},
            "text": function () {},
            "radio": function () {},
            "checkbox": function () {},
            "file": function () {},
            "password": function () {},
            "submit": function () {},
            "image": function () {},
            "reset": function () {},
            "button": function () {},
            "input": function () {},
            "hidden": function () {},
            "visible": function () {},
            "animated": function () {}
        },
        "setFilters": {
            "first": function () {},
            "last": function () {},
            "even": function () {},
            "odd": function () {},
            "lt": function () {},
            "gt": function () {},
            "nth": function () {},
            "eq": function () {}
        },
        "filter": {
            "PSEUDO": function () {},
            "CHILD": function () {},
            "ID": function () {},
            "TAG": function () {},
            "CLASS": function () {},
            "ATTR": function () {},
            "POS": function () {}
        },
        ":": {
            "enabled": function () {},
            "disabled": function () {},
            "checked": function () {},
            "selected": function () {},
            "parent": function () {},
            "empty": function () {},
            "has": function () {},
            "header": function () {},
            "text": function () {},
            "radio": function () {},
            "checkbox": function () {},
            "file": function () {},
            "password": function () {},
            "submit": function () {},
            "image": function () {},
            "reset": function () {},
            "button": function () {},
            "input": function () {},
            "hidden": function () {},
            "visible": function () {},
            "animated": function () {}
        }
    },
    "multiFilter": function () {},
    "dir": function () {},
    "nth": function () {},
    "sibling": function () {},
    "event": {
        "add": function () {},
        "guid": {},
        "global": {
            "unload": {},
            "load": {}
        },
        "remove": function () {},
        "trigger": function () {},
        "handle": function () {},
        "props": {
            "0": {},
            "1": {},
            "2": {},
            "3": {},
            "4": {},
            "5": {},
            "6": {},
            "7": {},
            "8": {},
            "9": {},
            "10": {},
            "11": {},
            "12": {},
            "13": {},
            "14": {},
            "15": {},
            "16": {},
            "17": {},
            "18": {},
            "19": {},
            "20": {},
            "21": {},
            "22": {},
            "23": {},
            "24": {},
            "25": {},
            "26": {},
            "27": {},
            "28": {},
            "29": {},
            "30": {},
            "31": {},
            "32": {},
            "33": {}
        },
        "fix": function () {},
        "proxy": function () {},
        "special": {
            "ready": {
                "setup": function () {},
                "teardown": function () {}
            },
            "mouseenter": {
                "setup": function () {},
                "teardown": function () {}
            },
            "mouseleave": {
                "setup": function () {},
                "teardown": function () {}
            }
        },
        "specialAll": {
            "live": {
                "setup": function () {},
                "teardown": function () {}
            }
        },
        "triggered": {}
    },
    "Event": function () {},
    "isReady": {},
    "readyList": function () {},
    "ready": function () {},
    "support": {
        "leadingWhitespace": {},
        "tbody": {},
        "objectAll": {},
        "htmlSerialize": {},
        "style": {},
        "hrefNormalized": {},
        "opacity": {},
        "cssFloat": {},
        "scriptEval": {},
        "noCloneEvent": {},
        "boxModel": {}
    },
    "props": {
        "for": {},
        "class": {},
        "float": {},
        "cssFloat": {},
        "styleFloat": {},
        "readonly": {},
        "maxlength": {},
        "cellspacing": {},
        "rowspan": {},
        "tabindex": {}
    },
    "get": function () {},
    "getScript": function () {},
    "getJSON": function () {},
    "post": function () {},
    "ajaxSetup": function () {},
    "ajaxSettings": {
        "url": {},
        "global": {},
        "type": {},
        "contentType": {},
        "processData": {},
        "async": {},
        "xhr": function () {},
        "accepts": {
            "xml": {},
            "html": {},
            "script": {},
            "json": {},
            "text": {},
            "_default": {}
        }
    },
    "lastModified": function () {},
    "ajax": function () {},
    "handleError": function () {},
    "active": {},
    "httpSuccess": function () {},
    "httpNotModified": function () {},
    "httpData": function () {},
    "param": function () {},
    "speed": function () {},
    "easing": {
        "linear": function () {},
        "swing": function () {}
    },
    "timers": function () {},
    "fx": function () {},
    "offset": {
        "initialize": function () {},
        "bodyOffset": function () {}
    },
    "xLazyLoader": function () {},
    "boxModel": {}
};

// SoundManager2

/** @constructor */
var SMSound = function(){};

var soundManager, SM2_DEFER, sm2Debugger;

/**
 * @constructor
 * @param {string=} smURL Optional: Path to SWF files
 * @param {string=} smID Optional: The ID to use for the SWF container element
 * @this {SoundManager}
 * @return {SoundManager} The new SoundManager instance
 */
var SoundManager = function(smURL, smID){};
SoundManager.prototype.audioFormats = {"mp3":{},"mp4":{},"ogg":{},"wav":{}};

// SoundManager2 names that need to be visible to Flash
SoundManager.prototype.sounds = {};
SoundManager.prototype._writeDebug = function() {};
SoundManager.prototype._externalInterfaceOK = function() {};
SoundManager.prototype._setSandboxType = function() {};
SMSound.prototype._whileloading = function() {};
SMSound.prototype._whileplaying = function() {};
SMSound.prototype.pause = function() {};
SMSound.prototype._onload = function() {};
SMSound.prototype._onconnect = function() {};
SMSound.prototype._onfailure = function() {};
SMSound.prototype._onmetadata = function() {};
SMSound.prototype._ondataerror = function() {};
SMSound.prototype._onbufferchange = function() {};
SMSound.prototype._onid3 = function() {};
SMSound.prototype._onfinish = function() {};

// Flash names that need to be visible to SoundManager2
HTMLObjectElement.prototype._load = function() {};
HTMLObjectElement.prototype._unload = function() {};
HTMLObjectElement.prototype._start = function() {};
HTMLObjectElement.prototype._stop = function() {};
HTMLObjectElement.prototype._pause = function() {};
HTMLObjectElement.prototype._setPosition = function() {};
HTMLObjectElement.prototype._setPan = function() {};
HTMLObjectElement.prototype._setVolume = function() {};
HTMLObjectElement.prototype._setPolling = function() {};
HTMLObjectElement.prototype._setAutoPlay = function() {};
HTMLObjectElement.prototype._createSound = function() {};
HTMLObjectElement.prototype._destroySound = function() {};
HTMLObjectElement.prototype._getMemoryUse = function() {};
HTMLObjectElement.prototype._disableDebug = function() {};
HTMLObjectElement.prototype._externalInterfaceTest = function() {};
HTMLObjectElement.prototype.PercentLoaded = function() {};

// Microsoft IE10 "Pointer" API
Event.prototype.pointerId = function() {};
Event.prototype.pointerType = function() {};
Event.prototype.MSPOINTER_TYPE_TOUCH = function() {};
Event.prototype.MSPOINTER_TYPE_MOUSE = function() {};
Event.prototype.MSPOINTER_TYPE_PEN = function() {};

// Fix old Google Closure Library incompatibility with more recent Closure Compilers

/** @typedef {XMLHttpRequest} */
var GearsHttpRequest;

/** @typedef {Blob} */
var GearsBlob;
