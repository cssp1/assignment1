goog.provide('GameArt');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.array');
goog.require('goog.string');
goog.require('SPAudio');
goog.require('BinaryHeap');
goog.require('FlashDetect');

// references metric_event from main.js

// global namespace
GameArt = { initialized: false };

GameArt.file_kinds = {
    IMAGE : 0,
    AUDIO : 1
};

// dictionary mapping filenames to {html_element, kind, filename, priority, [GameArt.Images/GameArt.Sounds...]}
// this is to allow different GameArt.Images to share the same HTML Image elements
// and different GameArt.Sounds to share the same sound samples
GameArt.file_list = {};

GameArt.stats = function() {
    var total = 0, total_img = 0, total_audio = 0;
    var non_delay = 0;
    for(var name in GameArt.file_list) {
        var entry = GameArt.file_list[name];
        total += 1;
        total_img += (entry.kind == GameArt.file_kinds.IMAGE ? 1 : 0);
        total_audio += (entry.kind == GameArt.file_kinds.AUDIO ? 1 : 0);
        non_delay += entry.delay_load ? 0 : 1;
    }
    var msg = 'ART FILES:\n';
    msg += total.toString()+' total\n';
    msg += non_delay.toString()+' not delay loaded\n';
    msg += total_img.toString()+' image files\n';
    msg += total_audio.toString()+' audio files\n';
    return msg;
};

// given an art asset filename from art.json, return the full URL to the source file
GameArt.art_url = function(filename, needs_cors) {
    var use_cdn = true;

    // some browsers do not yet have a way to retrieve images whose
    // pixel data we'll be looking at from the CDN without triggering
    // a security warning, so force them to be fetched locally.
    if(needs_cors && !GameArt.force_cors_art &&
       (spin_demographics['browser_name'] == "Safari" ||
        spin_demographics['browser_name'] == "Mozilla" ||
        spin_demographics['browser_name'] == "Explorer" ||
        (spin_demographics['browser_OS'] === "Linux" && spin_demographics['browser_name'] === "Mozilla") ||
        (spin_demographics['browser_name'] == "Firefox" && spin_demographics['browser_version'] < 9) ||
        (spin_demographics['browser_name'] == "Chrome" && spin_demographics['browser_version'] < 17) ||
        (spin_demographics['browser_name'] == "Opera" && spin_demographics['browser_version'] <= 11.64))) {
        use_cdn = false;
    }

    var url;
    if(spin_art_path && use_cdn) {
        // use CDN path
        var protocol;
        if(spin_art_protocol) {
            protocol = spin_art_protocol;
        } else {
            var is_audio = goog.string.endsWith(filename, '.ogg') || goog.string.endsWith(filename, '.mp3');
            if(GameArt.force_ssl_art ||
               (spin_demographics['browser_name'] === "Explorer" ||
                (spin_demographics['browser_name'] === 'Firefox' && spin_demographics['browser_version']>= 25) ||
                (spin_demographics['browser_name'] === 'Chrome' && spin_demographics['browser_version']>= 38 && is_audio))) {
                protocol = spin_server_protocol;
            } else {
                protocol = 'http://';
            }
        }
        url = protocol+spin_art_path+filename;
    } else {
        // use ordinary path
        url = spin_server_protocol+spin_server_host+':'+spin_server_port+'/'+filename;
    }

    if(spin_http_origin) {
        var delimiter = (url.indexOf('?') > 0 ? '&' : '?'); // really hacky query string detection
        url += delimiter+'spin_origin='+encodeURIComponent(spin_http_origin);
    }

    return url;
};

// ChannelGovernor manages an abstract set of audio channels
// it tries to ensure that we don't overload the underlying audio driver by
// trying to play too many sound effects at the same time
/** @constructor */
GameArt.ChannelGovernor = function(max_chan) {
    this.max_chan = max_chan;
    this.cur = 0;
    // keep track of completion times of currently-playing sounds
    this.completion = new BinaryHeap.BinaryHeap();
};

// try to get permission to play an audio clip, passing in starting and ending client_times
// if successful, claim a channel and return true
// if the audio system is overloaded, return false
GameArt.ChannelGovernor.prototype.get_chan = function(start, end) {
    if(this.cur >= this.max_chan) { return false; }
    if(end <= start) { console.log('invalid start/end times '+start+'/'+end); return false; }
    this.cur += 1;
    // XXX take starting delay into account?
    var entry = {end: end};
    this.completion.push(entry, entry.end);
    return true;
};
GameArt.ChannelGovernor.prototype.update = function(t) {
    while(this.completion.size() > 0 && this.completion.peek().end <= t) {
        this.completion.pop();
        this.cur -= 1;
    }
    if(this.cur < 0) { this.cur = 0; }
};

// call this every frame to establish when "now" is for the audio drivers and update faders
GameArt.sync_time = function(time) {
    if(!GameArt.initialized) { return; }
    if(GameArt.audio_driver) { GameArt.audio_driver.sync_time(time); }
    if(GameArt.channel_governor) { GameArt.channel_governor.update(time); }
    GameArt.time = time;
};

GameArt.set_audio_channel_max = function(num) {
    if(GameArt.channel_governor) { GameArt.channel_governor.max_chan = num; }
};

GameArt.init = function(time, canvas, ctx, art_json, dl_callback, audio_driver_name, use_low_gfx, lazy_art, enable_pixel_manipulation_in_low_gfx) {
    GameArt.initialized = true;
    GameArt.time = time;
    GameArt.canvas = canvas;
    GameArt.ctx = ctx;
    GameArt.enable_audio = !!audio_driver_name;
    GameArt.enable_images = (document.URL.indexOf('null_all_images=1') == -1);
    GameArt.low_gfx = use_low_gfx;
    GameArt.lazy_art = lazy_art;
    GameArt.enable_pixel_manipulation_in_low_gfx = enable_pixel_manipulation_in_low_gfx;

    GameArt.force_ssl_art = (document.URL.indexOf('sslart=1') != -1);
    GameArt.force_cors_art = (document.URL.indexOf('force_cors_art=1') != -1);

    // set audio driver
    GameArt.audio_driver = null;
    if(GameArt.enable_audio) {
        if(audio_driver_name == 'AudioContext') {
            if(typeof(AudioContext) != 'undefined' || typeof(webkitAudioContext) != 'undefined') {
                try {
                    GameArt.audio_driver = new SPAudio.ACDriver(time);
                } catch(e) {
                    //  usually NotSupportedError: Failed to construct 'AudioContext': The number of hardware contexts provided (6) is greater than or equal to the maximum bound (6).
                    console.log('AudioContext initialization failed - falling back to sm2');
                    audio_driver_name = 'sm2';
                }
            } else {
                console.log('AudioContext audio driver requested, but (webkit)AudioContext is undefined - falling back to sm2');
                audio_driver_name = 'sm2';
            }
        }
        if(audio_driver_name == 'sm2') {
            if(FlashDetect.detect()) {
                var swf_location = GameArt.art_url('art/soundmanager2/', false);
                GameArt.audio_driver = new SPAudio.SM2Driver(time, swf_location);
            } else {
                console.log('sm2 audio driver requested, but Flash not detected - falling back to buzz');
                audio_driver_name = 'buzz';
            }
        }
        if(audio_driver_name == 'buzz') {
            GameArt.audio_driver = new SPAudio.BuzzDriver(time);
        }

        if(!GameArt.audio_driver) {
            console.log('no audio driver loaded');
            GameArt.enable_audio = false;
        }
    }

    // set audio driver parameters
    if(GameArt.audio_driver) {
        var max_channels = gamedata['client']['max_audio_channels'][GameArt.audio_driver.kind];
        if(spin_demographics['browser_name'] in gamedata['client']['max_audio_channels']) {
            max_channels = Math.min(max_channels, gamedata['client']['max_audio_channels'][spin_demographics['browser_name']]);
        }

        console.log('Audio: using '+GameArt.audio_driver.kind+' driver with '+max_channels.toString()+' max audio channels');

        GameArt.audio_codec = GameArt.audio_driver.get_codec();
        GameArt.channel_governor = new GameArt.ChannelGovernor(max_channels);
    } else {
        GameArt.audio_codec = '';
        GameArt.channel_governor = null;
    }


    // off by default until client starts, to avoid stay sounds
    // playing during load if user's preference is for no audio
    GameArt.music_volume = 0;
    GameArt.sound_volume = 0;

    // counts number of file downloads we are waiting for
    GameArt.essential_dl_pending_count = 0; // essential downloads only
    GameArt.all_dl_pending_count = 0; // all downloads

    GameArt.essential_dl_total = 0;
    GameArt.all_dl_total = 0;

    GameArt.dl_inflight_count = 0;
    if(1) {
        var data = gamedata['client']['concurrent_art_downloads'];
        GameArt.dl_inflight_max = data['default'] || 20;
        if(spin_demographics['browser_OS'] in data) { GameArt.dl_inflight_max = Math.min(GameArt.dl_inflight_max, data[spin_demographics['browser_OS']]); }
        if(spin_demographics['browser_name'] in data) { GameArt.dl_inflight_max = Math.min(GameArt.dl_inflight_max, data[spin_demographics['browser_name']]); }
    }

    // all assets with a load_priority equal to or greater than this are considered "essential"
    GameArt.essential_priority = 100;

    // function that is called when all art files are finished downloading into the browser
    GameArt.dl_complete_callback = dl_callback || function() {};

    // initialize assets
    GameArt.assets = {};
    for(var name in art_json) {
        var data = art_json[name];
        GameArt.assets[name] = new GameArt.Asset(name, data);
    }

    // sort download requests by priority
    GameArt.dl_heap = new BinaryHeap.BinaryHeap();
    for(var name in GameArt.file_list) {
        var entry = GameArt.file_list[name];

        entry.dl_complete = false;
        entry.dl_started = false;

        if(entry.delay_load) { continue; }
        // if(entry.kind === GameArt.file_kinds.AUDIO) { continue; }

        GameArt.all_dl_total += 1;
        if(entry.priority >= GameArt.essential_priority) {
            GameArt.essential_dl_total += 1;
        }
        GameArt.dl_heap.push(entry, -entry.priority);
    }

    // begin download process
    GameArt.all_dl_pending_count = GameArt.all_dl_total;
    GameArt.essential_dl_pending_count = GameArt.essential_dl_total;
    GameArt.download_more_assets();

    if(GameArt.essential_dl_pending_count < 1 ||
       GameArt.all_dl_pending_count < 1) {
        GameArt.dl_complete_callback();
    }
};

GameArt.download_more_assets = function() {
    //console.log('download: essential '+GameArt.essential_dl_pending_count+'/'+GameArt.essential_dl_total+' all: '+GameArt.all_dl_pending_count+'/'+GameArt.all_dl_total);
    //console.log('download_more '+GameArt.dl_heap.size().toString() + ' inflight '+GameArt.dl_inflight_count+' max '+GameArt.dl_inflight_max);
    while(GameArt.dl_heap && GameArt.dl_heap.size() > 0 && GameArt.dl_inflight_count < GameArt.dl_inflight_max) {
        var entry = GameArt.dl_heap.pop();

        GameArt.dl_inflight_count += 1;

        var SLOWTEST = false;
        if(SLOWTEST && entry.priority < GameArt.essential_priority) {
            // simulate slow net connection
            console.log('GameArt: Simulating slow net connection!');
            var cb = (function(e) { return function() { e.start_load(e); }; })(entry);
            window.setTimeout(cb, 3000*GameArt.all_dl_pending_count);
        } else {
            //console.log('queueing '+entry.filename+' prio '+entry.priority);
            entry.dl_started = true;
            entry.start_load(entry);
        }
    }
};

GameArt.get_dl_progress_all = function() {
    if(!GameArt.initialized) { return 0; }
    if(GameArt.all_dl_pending_count === 0) { return 1; }
    return 1 - (GameArt.all_dl_pending_count/GameArt.all_dl_total);
}
GameArt.get_dl_progress_essential = function() {
    if(!GameArt.initialized) { return 0; }
    if(GameArt.essential_dl_pending_count === 0) { return 1; }
    return 1 - (GameArt.essential_dl_pending_count/GameArt.essential_dl_total);
}

GameArt.image_onload = function(filename) {
    //console.log('loaded '+filename);

    var priority;
    if(filename in GameArt.file_list) {
        var entry = GameArt.file_list[filename]
        priority = entry.priority;
        if(entry.dl_complete) {
            //console.log('duplicate onload call for '+filename+'!');
            return;
        }
        entry.dl_complete = true;
    } else {
        console.log('not found in GameArt file list! '+filename);
        return;
    }

    GameArt.dl_inflight_count -= 1;

    if(entry.delay_load) {
        // does not participate in overall counters
        GameArt.download_more_assets();
        return;
    }

    GameArt.all_dl_pending_count -= 1;

    if(priority >= GameArt.essential_priority) {
        GameArt.essential_dl_pending_count -= 1;
        if(GameArt.essential_dl_pending_count === 0) {
            GameArt.dl_complete_callback();
        }
    }

    if(GameArt.all_dl_pending_count === 0) {
        // the last outstanding image download request has finished

        if(GameArt.dl_heap.size() > 0) {
            throw Error('dl_pending_count = 0 but heap is not empty');
        }
        GameArt.dl_heap = null;

        GameArt.dl_complete_callback();
    } else {
        GameArt.download_more_assets();
        //window.setTimeout(GameArt.download_more_assets, 1);
    }
};

// only send one asset_load_fail per session to avoid spamming server
GameArt.asset_load_fail_sent = false;

GameArt.report_asset_load_fail = function(filename, reason) {
    if(!GameArt.asset_load_fail_sent) {
        GameArt.asset_load_fail_sent = true;
        metric_event('0660_asset_load_fail', add_demographics({'method':filename, 'reason':reason}));
    }
};

GameArt.image_onerror = function(filename, reason) {
    console.log('Error loading art file '+filename+' for reason: '+reason);
    GameArt.report_asset_load_fail(filename, reason);
    GameArt.image_onload(filename);
};

GameArt.image_ontimeout = function(filename) {
    console.log('Timeout loading art file '+filename);
    GameArt.report_asset_load_fail(filename, 'timeout');
    // do not call image_onload() here to abort the load, in case the browser eventually does get the data
};

// the data structure for game art assets looks like this:
//
// ASSET (e.g., "mining_droid")
// contains a set of SPRITEs, one for each state (e.g., "moving", "destroyed", "working", etc)
//
// SPRITE (e.g., "mining_droid while moving")
// contains one or more IMAGEs (e.g., "moving northwest", "working frames 1-10")
//
// IMAGE (e.g., "mining_droid_01.png")
// is just a wrapper around the browser's Image class

/** @constructor
 * @param data A dictionary mapping state names to Sprites (the thing under gamedata['art'])
 */
GameArt.Asset = function(name, data) {
    this.name = name;
    this.states = {};
    for(var statename in data['states']) {
        var src_statename = statename;

        // to save memory, substitute some sprite states for uncommon ones
        var subst_map_name = (GameArt.low_gfx ? 'low_gfx' : 'normal');
        var subst_map = gamedata['client']['merge_sprites'][subst_map_name];
        if((statename in subst_map) && (subst_map[statename] in data['states'])) {
            src_statename = subst_map[statename];
        }

        var spr_name = name+'/'+src_statename;
        var spr_data = data['states'][src_statename];
        var spr;
        if('subassets' in spr_data) {
            spr = new GameArt.CompoundSprite(spr_name, spr_data);
        } else {
            spr = new GameArt.Sprite(spr_name, spr_data);
        }
        this.states[statename] = spr;
    }
};

GameArt.Asset.prototype.has_state = function(state) { return (state in this.states); };

GameArt.Asset.prototype.get_state = function(state) {
    if(!(state in this.states)) {
        throw Error('request for invalid art asset state '+this.name+'.'+state);
    }
    return this.states[state];
};

// Start all necessary delay loading. Return true if ready to draw.
GameArt.Asset.prototype.prep_for_draw = function(xy, facing, time, state) {
    return this.get_state(state).prep_for_draw(xy, facing, time);
};
// Just check if ready to draw. Do not start delay loading.
GameArt.Asset.prototype.ready_to_draw = function(xy, facing, time, state) {
    return this.get_state(state).ready_to_draw(xy, facing, time);
};
// Draw the asset in the state named 'state' facing direction 'facing' (0-2PI) at screen location xy
GameArt.Asset.prototype.draw = function(xy, facing, time, state) {
    this.get_state(state).draw(xy, facing, time);
};

// mouse-click hit detection in screen space
GameArt.Asset.prototype.detect_click = function(xy, facing, time, state, mousexy, zoom, fuzz) {
    return this.get_state(state).detect_click(xy, facing, time, mousexy, zoom, fuzz);
};

GameArt.Asset.prototype.detect_rect = function(xy, facing, time, state, mouserect, zoom, fuzz) {
    return this.get_state(state).detect_rect(xy, facing, time, mouserect, zoom, fuzz);
};

/** @constructor */
GameArt.AbstractSprite = function(name, data) {
    this.name = name;
    this.wh = null;
    this.center = null;
    if('dimensions' in data) {
        this.wh = data['dimensions'];
    }

    if('center' in data) {
        this.center = data['center'];
    } else if(this.wh) {
        this.center = [Math.floor(this.wh[0]/2), Math.floor(this.wh[1]/2)];
    }
};
GameArt.AbstractSprite.prototype.duration = function() { return 0; };
GameArt.AbstractSprite.prototype.get_center = function() { return this.center; };

// draw sprite with CENTER at 'xy'
GameArt.AbstractSprite.prototype.draw = function(xy, facing, time) {
    var ctr, loc;
    ctr = this.get_center();
    if(ctr === null) {
        loc = xy;
    } else {
        loc = vec_sub(xy, ctr);
    }
    this.do_draw(loc, facing, time, this.wh);
};
// draw sprite with TOP-LEFT CORNER at 'xy'
GameArt.AbstractSprite.prototype.draw_topleft = function(xy, facing, time) {
    this.do_draw(xy, facing, time, this.wh);
};
GameArt.AbstractSprite.prototype.draw_topleft_at_size = function(xy, facing, time, dest_wh) {
    if(!dest_wh) { dest_wh = this.wh; }
    this.do_draw(xy, facing, time, dest_wh);
};

/** Return bounding box for sprite-based click detection
    @param {!Array.<number>} xy
    @param {number} facing
    @param {number} time
    @param {number} zoom
    @param {number} fuzz
    @return {(!Array.<!Array.<number>>)|null} */
GameArt.AbstractSprite.prototype.detect_click_bounds = function(xy, facing, time, zoom, fuzz) {
    if(!this.wh) { return null; }
    var loc;
    if(this.center === null) {
        loc = xy;
    } else {
        loc = [xy[0]-zoom*this.center[0],xy[1]-zoom*this.center[1]];
    }
    return [ [loc[0]-zoom*fuzz, loc[0]+zoom*this.wh[0]+zoom*fuzz],
             [loc[1]-zoom*fuzz, loc[1]+zoom*this.wh[1]+zoom*fuzz] ];
};
/** Perform sprite-based click detection against a point
    @param {!Array.<number>} xy
    @param {number} facing
    @param {number} time
    @param {!Array.<number>} mouseloc
    @param {number} zoom
    @param {number} fuzz
    @return {boolean} */
GameArt.AbstractSprite.prototype.detect_click = function(xy, facing, time, mouseloc, zoom, fuzz) {
    var my_bounds = this.detect_click_bounds(xy, facing, time, zoom, fuzz);
    if(!my_bounds) { return false; }
    if(mouseloc[0] >= my_bounds[0][0] && mouseloc[0] < my_bounds[0][1] &&
       mouseloc[1] >= my_bounds[1][0] && mouseloc[1] < my_bounds[1][1]) {
        return true;
    }
    return false;
};

GameArt.range_overlap = function(a0, a1, b0, b1) {
    // a0 -------- a1
    //                b0 --------- b1
    if(a0 < b0 && a1 < b0) { return false; }
    //                      a0 ------------ a1
    // b0 ------------- b1
    if(a0 >= b1 && a1 >= b1) { return false; }
    return true;
};
/** Perform sprite-based click detection against a rectangle
    @param {!Array.<number>} xy
    @param {number} facing
    @param {number} time
    @param {!Array.<!Array.<number>>} mouserect
    @param {number} zoom
    @param {number} fuzz
    @return {boolean} */
GameArt.AbstractSprite.prototype.detect_rect = function(xy, facing, time, mouserect, zoom, fuzz) {
    var my_bounds = this.detect_click_bounds(xy, facing, time, zoom, fuzz);
    if(!my_bounds) { return false; }
    return GameArt.range_overlap(mouserect[0][0], mouserect[0][1], my_bounds[0][0], my_bounds[0][1]) &&
           GameArt.range_overlap(mouserect[1][0], mouserect[1][1], my_bounds[1][0], my_bounds[1][1]);
};

// Sprites are initialized directly from the gamedata JSON
/** @constructor
  * @extends GameArt.AbstractSprite */
GameArt.Sprite = function(name, data) {
    goog.base(this, name, data);

    if('style' in data) {
        this.style = data['style'];
    } else {
        this.style = 'plain'; // just a plain image
    }

    var n_images;
    if(this.style === 'compass') {
        n_images = data['images'].length; // assume entire image array length is # of compass directions
        this.compassdir = n_images;
    } else if(this.style === 'fullness') {
        n_images = data['images'].length; // assume entire image array length is # of fullness stages
    } else if(this.style === 'animation') {
        this.framerate = data['framerate'];
        if(this.framerate < 1 || this.framerate > 100) {
            throw Error('invalid framerate');
        }
        this.loop = data['loop'] || 1;
        n_images = Math.max(('origins' in data ? data['origins'].length >> 1 : 1), data['images'].length);
    } else if(this.style === 'corners') {
        n_images = 1;
        this.corner_width = data['corner_width'];
    } else if(this.style === 'null') {
        n_images = 0;
    } else {
        if('images' in data) {
            if(this.style != 'plain') {
                throw Error('unknown sprite style '+this.style);
            }
            n_images = data['images'].length; // 1
        } else {
            // audio only
            n_images = 0;
        }
    }

    var origins;
    if(n_images > 0) {
        if(!this.wh) {
            console.log('gameart needs dimensions for '+this.name);
        }
        if('origins' in data) {
            origins = data['origins'];
        } else {
            origins = null;
        }
    }

    // record the color to apply to associated text, if the asset specifies it
    this.text_color = data['text_color'] || null;
    this.avg_color = data['avg_color'] || null;

    this.composite_mode = data['composite_mode'] || null;
    this.alpha = data['alpha'] || 1;

    // switch to another state when in this interaction state
    this.on_mouseover = data['on_mouseover'] || false;
    this.on_push = data['on_push'] || false;

    this.images = [];

    var load_priority = data['load_priority'] || 0;
    var delay_load = data['delay_load'] || false;

    if(GameArt.lazy_art && load_priority < GameArt.essential_priority) {
        delay_load = true;
    }

    if(n_images > 0) {
        // NOTE: adding "tint" to a sprite means "make duplicate HTML5
        // image elements FOR EACH SUBIMAGE and will be inefficient
        // for packed sprites, unless "tint_share" is enabled, which
        // shares one tinted image element for the whole sheet.
        var tint = data['tint'] || null;
        if(tint && tint.length < 4) {
            tint = goog.array.clone(tint); // do not mutate gamedata!
            while(tint.length < 4) { tint.push(1); }
        }
        var saturation = ('saturation' in data) ? data['saturation'] : 1;

        var imgname = data['images'][0];
        for(var i = 0; i < n_images; i++) {
            var img_i = Math.min(data['images'].length-1, i);
            if(data['images'][img_i] === '*') {
                // compressed duplicate
            } else {
                imgname = data['images'][img_i];
            }

            var instance;
            if((tint || (saturation != 1)) &&
               (!GameArt.low_gfx || GameArt.enable_pixel_manipulation_in_low_gfx) && gamedata['client']['enable_pixel_manipulation']) {
                instance = new GameArt.TintedImage(imgname,
                                                   (origins ? [origins[2*i], origins[2*i+1]] : null),
                                                   // awkward - corner sprites have different "real" dimensions
                                                   (this.style === 'corners' ? [3*this.corner_width,3*this.corner_width] : this.wh),
                                                   load_priority,
                                                   delay_load,
                                                   tint, saturation,
                                                   ('tint_share' in data ? data['tint_share'] : ((n_images>1) || !!data['tint_mask'])),
                                                   (data['tint_mask'] ? new GameArt.Image(data['tint_mask'], null, this.wh, load_priority, delay_load) : null)
                                                  );
            } else {
                instance = new GameArt.Image(imgname,
                                             (origins ? [origins[2*i], origins[2*i+1]] : null),
                                             this.wh,
                                             load_priority,
                                             delay_load
                                            );
            }
            this.images.push(instance);
        }
    }

    this.audio = null;
    if('audio' in data) {
        var volume;
        if('volume' in data) {
            volume = data['volume'];
        } else {
            volume = 1;
        }
        this.audio = new GameArt.Sound(data['audio'], volume, (data['audio_priority'] || 0),
                                       load_priority, delay_load, data['audio_type'] || "sample");
    }
};
goog.inherits(GameArt.Sprite, GameArt.AbstractSprite);

// return length of animation (in seconds)
GameArt.Sprite.prototype.duration = function() {
    if(this.style === 'animation') {
        return this.images.length / this.framerate;
    } else {
        return 0;
    }
};

// return the Image within images[] for the frame corresponding to this facing and time
GameArt.Sprite.prototype.select_image = function(facing, time) {
    var index;
    if(this.style === 'compass') {
        // choose sprite based on facing direction
        while(facing < 0) { facing += 2*Math.PI; }
        var face = (180.0/Math.PI)*(facing+Math.PI);
        var inc = 360/this.compassdir;
        face = Math.floor(((face+270+inc/2) % 360.0)/inc);
        index = face;
    } else if(this.style === 'fullness') {
        index = 0; // XXXXXX
    } else if(this.style === 'animation') {
        var frame = -1;

        // prevent animated sprites from flickering during
        // loading - if entire sequence is not loaded, then try to show t=0
        for(var i = 0; i < this.images.length; i++) {
            if(!this.images[i].data_loaded) {
                frame = 0;
                break;
            }
        }

        if(frame < 0) {
            frame = Math.floor(this.framerate * time);
            if(this.loop) {
                frame = frame % this.images.length;
            }
        }

        index = frame;
    } else if(this.style === 'plain' || this.style === 'corners') {
        index = 0;
    }

    var img = this.images[index];
    if(!img) {
        var err = 'Sprite image error! '+this.name+' facing '+facing+' index '+index;
        err += ' this.images.length '+this.images.length;
        if(this.images.length > 0) { err += ' this.images[0] '+this.images[0].toString(); }
        throw Error(err);
    }
    return img;
};

GameArt.Sprite.prototype.prep_for_draw = function(xy, facing, time, dest_wh) {
    if(this.style === 'null') { return; }
    var img = this.select_image(facing, time);
    return img.prep_for_draw();
};
GameArt.Sprite.prototype.ready_to_draw = function(xy, facing, time, dest_wh) {
    if(this.style === 'null') { return; }
    var img = this.select_image(facing, time);
    return img.ready_to_draw();
};

// draw with specified destination width/height - can be different from image width/height for resizable sprites
GameArt.Sprite.prototype.do_draw = function(xy, facing, time, dest_wh) {
    if(this.style === 'null') { return; }

    var img = this.select_image(facing, time);

    if(img.data_loaded) {
        var has_state = false;

        if(this.composite_mode || this.alpha < 1) {
            has_state = true;
            GameArt.ctx.save();
            if(this.composite_mode) { GameArt.ctx.globalCompositeOperation = this.composite_mode; }
            if(this.alpha < 1) { GameArt.ctx.globalAlpha = this.alpha; }
        }

        if(this.style === 'corners') {
            // tic-tac-toe sprite pattern
            var w = this.corner_width;

            var h;
            // omit the last few pixels at the bottom of the top row if we are scrunched for space
            h = Math.min(w, Math.floor(dest_wh[1]/2));
            img.drawSubImage([0,0],[w,h],[xy[0],xy[1]],[w,h]); // upper left
            img.drawSubImage([w,0],[w,h],[xy[0]+w,xy[1]],[dest_wh[0]-2*w,h]); // upper center
            img.drawSubImage([2*w,0],[w,h],[xy[0]+(dest_wh[0]-w),xy[1]],[w,h]); // upper right

            // skip drawing the center row if the size would make it shorter than one pixel
            h = dest_wh[1]-2*w;
            if(h > 0) {
                img.drawSubImage([0,w],[w,Math.min(w,h)],[xy[0],xy[1]+w],[w,dest_wh[1]-2*w]); // left column
                img.drawSubImage([w,w],[w,w],[xy[0]+w,xy[1]+w],[dest_wh[0]-2*w,h]); // center
                img.drawSubImage([2*w,w],[w,Math.min(w,h)],[xy[0]+dest_wh[0]-w,xy[1]+w],[w,dest_wh[1]-2*w]); // right column
            }

            // omit the first few pixels at the top of the bottom row if necessary
            h = Math.min(w, dest_wh[1]-Math.floor(dest_wh[1]/2));
            var start = w-h;

            img.drawSubImage([0,2*w+start],[w,w-start],[xy[0],xy[1]+dest_wh[1]-w+start],[w,w-start]); // lower left
            img.drawSubImage([w,2*w+start],[w,w-start],[xy[0]+w,xy[1]+dest_wh[1]-w+start],[dest_wh[0]-2*w,w-start]); // lower center
            img.drawSubImage([2*w,2*w+start],[w,w-start],[xy[0]+dest_wh[0]-w,xy[1]+dest_wh[1]-w+start],[w,w-start]); // lower right

        } else {
            // note: ignores dest_wh and uses the image's native wh
            if(dest_wh && (dest_wh[0] != img.wh[0] || dest_wh[1] != img.wh[1])) { console.log('inconsistent wh on '+img.filename); }
            img.draw(xy);
        }

        if(has_state) {
            GameArt.ctx.restore();
        }
    } else {
        if(img.delay_load) {
            // start delayed loading for all frames
            for(var i = 0; i < this.images.length; i++) {
                this.images[i].check_delay_load();
            }
        }

        if(dest_wh) {
            GameArt.ctx.save();
            GameArt.ctx.fillStyle = 'rgba(50,0,0,0.25)';
            GameArt.ctx.fillRect(xy[0], xy[1], dest_wh[0], dest_wh[1]);
            GameArt.ctx.restore();
        }
    }
};

/** @constructor
  * @extends GameArt.AbstractSprite */
GameArt.CompoundSprite = function(name, data) {
    goog.base(this, name, data);
    this.subassets = data['subassets'];
};
goog.inherits(GameArt.CompoundSprite, GameArt.AbstractSprite);
GameArt.CompoundSprite.prototype.duration = function() { return this.subassets[0].duration(); };
GameArt.CompoundSprite.prototype.get_center = function() {
    return this.get_subasset(this.subassets[0]).get_center();
};
GameArt.CompoundSprite.prototype.get_subasset = function(data) {
    var params = this.get_subasset_params(data);
    return GameArt.assets[params.name].states[params.state];
};
GameArt.CompoundSprite.prototype.get_subasset_params = function(data) {
    var name, state, transform, scale, alpha, offset, centered, clip_to;
    if(typeof(data) === 'string') {
        name = data;
        state = 'normal';
        transform = null;
        scale = 1;
        alpha = 1;
        offset = [0,0];
        centered = false;
        clip_to = null;
    } else {
        name = data['name'];
        state = data['state'] || 'normal';
        transform = ('transform' in data) ? data['transform'] : null;
        scale = ('scale' in data) ? data['scale'] : 1;
        alpha = ('alpha' in data) ? data['alpha'] : 1
        offset = ('offset' in data) ? data['offset'] : [0,0];
        centered = data['centered'] || false;
        clip_to = data['clip_to'] || null;
    }
    return {name:name, state:state, scale:scale, transform:transform, alpha:alpha, offset:offset, centered:centered, clip_to:clip_to};
}

GameArt.CompoundSprite.prototype.prep_for_draw = function(xy, facing, time, dest_wh) {
    var ready = true;
    for(var i = 0; i < this.subassets.length; i++) {
        var params = this.get_subasset_params(this.subassets[i]);
        var sprite = GameArt.assets[params.name].states[params.state];
        if(!sprite.prep_for_draw(xy, facing, time, dest_wh)) {
            ready = false;
        }
    }
    return ready;
};
GameArt.CompoundSprite.prototype.ready_to_draw = function(xy, facing, time, dest_wh) {
    for(var i = 0; i < this.subassets.length; i++) {
        var params = this.get_subasset_params(this.subassets[i]);
        var sprite = GameArt.assets[params.name].states[params.state];
        if(!sprite.ready_to_draw(xy, facing, time, dest_wh)) {
            return false;
        }
    }
    return true;
};

GameArt.CompoundSprite.prototype.do_draw = function(xy, facing, time, dest_wh) {
    for(var i = 0; i < this.subassets.length; i++) {
        var childxy = xy.slice(0);
        var params = this.get_subasset_params(this.subassets[i]);
        var sprite = GameArt.assets[params.name].states[params.state];
        var has_state = (params.clip_to || (params.scale != 1) || (params.alpha != 1) || (!!params.transform));

        if(has_state) { GameArt.ctx.save(); }

        if(params.clip_to) {
            GameArt.ctx.beginPath();
            GameArt.ctx.rect(xy[0]+params.clip_to[0], childxy[1]+params.clip_to[1], params.clip_to[2], params.clip_to[3]);
            GameArt.ctx.clip();
        }

        if(params.transform) {
            var t = params.transform;
            GameArt.ctx.transform(t[0], t[1], t[2], t[3], t[4]+childxy[0], t[5]+childxy[1]);
            childxy = [0,0];
        }

        if(params.scale != 1) {
            GameArt.ctx.transform(params.scale, 0, 0, params.scale, childxy[0], childxy[1]);
            childxy = [0,0];
        }

        if(params.alpha != 1) {
            GameArt.ctx.globalAlpha = params.alpha;
        }

        if(params.centered) {
            params.offset = vec_add(params.offset, vec_floor(vec_scale(0.5/params.scale, dest_wh)));
            sprite.draw(vec_add(childxy, params.offset), facing, time);
        } else {
            sprite.draw_topleft_at_size(vec_add(childxy, params.offset), facing, time, dest_wh);
        }

        if(has_state) { GameArt.ctx.restore(); }
    }
};

// GameArt.Image
// this is a wrapper around an HTML5 Image element
// it brings loading into the GameArt framework and allows delayed loading
// (you can call draw() even if the image data has not arrived yet)

/** @constructor */
GameArt.Image = function(filename, origin, wh, load_priority, delay_load) {
    this.origin = origin;
    this.wh = wh;
    this.data_loaded = false;
    this.delay_load = delay_load;

    if(!GameArt.enable_images) {
        this.entry = null;
        this.img = null;
        return;
    }

    if(filename in GameArt.file_list) {
        // attach to existing download request
        this.entry = GameArt.file_list[filename];
        this.img = this.entry.html_element;
        this.entry.gameart_objects.push(this);
        this.entry.priority = Math.max(this.entry.priority, load_priority);
        if(!delay_load) { this.entry.delay_load = false; }

    } else {
        // create new download request
        this.img = new Image();
        // this.img.setAttribute('crossOrigin','anonymous'); // ???
        this.img.crossOrigin = 'Anonymous'; // necessary to allow getImageData to work via CORS on Firefox and Chrome

        // note: img.src is set by GameArt.init after all the Assets are set up

        this.entry = {html_element: this.img,
                      kind: GameArt.file_kinds.IMAGE,
                      delay_load: delay_load,
                      gameart_objects: [this],
                      filename:filename,
                      // flag to indicate that the image needs special handling because it may trigger CORS
                      // security problems on IE
                      needs_cors:false,
                      watchdog:null,
                      start_load: function(e) {
                          e.html_element.src = GameArt.art_url(e.filename, e.needs_cors);

                          if(e.html_element.complete) { // synchronous completion
                              window.setTimeout(e.html_element.onload, 1);
                          } else {
                              if(gamedata['client']['art_download_timeout']['image'] > 0) {
                                  e.watchdog = window.setTimeout((function (_e) { return function() {
                                      GameArt.image_ontimeout(_e.filename);
                                  }; })(e), 1000 * gamedata['client']['art_download_timeout']['image']);
                              }
                          }
                      },
                      priority:load_priority};

        this.img.onload = (function (_entry) { return function() {
            if(_entry.watchdog) {
                window.clearTimeout(_entry.watchdog);
                _entry.watchdog = null;
            }
            var el = _entry.html_element;
            if(!el.complete || el.width < 1 || el.height < 1) {
                var msg = 'unknown';
                if(!el.complete) {
                    msg = 'loaded_but_not_complete';
                } else if(el.width < 1 || el.height < 1) {
                    msg = 'loaded_but_bad_dimensions';
                }
                GameArt.image_onerror(_entry.filename, msg);
                return;
            }

            for(var i = 0; i < _entry.gameart_objects.length; i++) {
                _entry.gameart_objects[i].got_data();
            }
            GameArt.image_onload(_entry.filename);
        }; })(this.entry);

        this.img.onerror = (function (_entry) { return function() {
            if(_entry.watchdog) {
                window.clearTimeout(_entry.watchdog);
                _entry.watchdog = null;
            }
            GameArt.image_onerror(_entry.filename, 'html_onerror');
        }; })(this.entry);

        GameArt.file_list[filename] = this.entry;
    }
};

// called when this.img (the html_element) becomes valid to draw
GameArt.Image.prototype.got_data = function() {
    this.data_loaded = true;
};

GameArt.Image.prototype.check_delay_load = function() {
    if(!this.entry || !this.entry.delay_load || this.entry.dl_started) { return; }

    if(GameArt.dl_inflight_count >= GameArt.dl_inflight_max) { return; }
    GameArt.dl_inflight_count += 1;

    this.entry.dl_started = true;
    this.entry.start_load(this.entry);
};

GameArt.Image.prototype.check_for_badness = function() {
    // seems to be a bug or undocumented behavior change
    if((spin_demographics['browser_name'] == "Firefox" && spin_demographics['browser_version'] >= 38) &&
       !this.img.complete) {
        // try again next frame
        return true;
    }

    if(!this.img.complete || this.img.width < 1 || this.img.height < 1) {
        this.data_loaded = false;
        GameArt.report_asset_load_fail(this.entry.filename, (!this.img.complete ? 'draw_but_not_complete': 'draw_but_bad_dimensions'));
        return true;
    }
    return false;
};

// return false if not ready to draw
GameArt.Image.prototype.prep_for_draw = function() {
    if(!this.img) { return false; }
    if(!this.data_loaded) {
        this.check_delay_load();
        return false;
    }

    if(this.check_for_badness()) { return false; }
    return true;
};
GameArt.Image.prototype.ready_to_draw = function() {
    return this.img && this.data_loaded;
};

GameArt.Image.prototype.draw = function(xy) {
    if(!this.prep_for_draw()) { return; }

    try {
        if(this.origin) {
            // draw packed sprite
             GameArt.ctx.drawImage(this.img,
                                   this.origin[0], this.origin[1],
                                   this.wh[0], this.wh[1],
                                   xy[0], xy[1],
                                   this.wh[0], this.wh[1]
                                  );
        } else {
            GameArt.ctx.drawImage(this.img, xy[0], xy[1]); // OK
        }
    } catch(e) {}
};

GameArt.Image.prototype.drawSubImage = function(sxy, swh, dxy, dwh) {
    if(!this.prep_for_draw()) { return; }

    try {
        GameArt.ctx.drawImage(this.img,
                              sxy[0] + (this.origin ? this.origin[0] : 0),
                              sxy[1] + (this.origin ? this.origin[1] : 0),
                              swh[0], swh[1], dxy[0], dxy[1], dwh[0], dwh[1]); // OK
    } catch(e) {}
};

// same as drawSubImage(), but clamps source coordinates to avoid requesting pixels outside the bounds of the source image (Firefox doesn't like this)
GameArt.Image.prototype.drawSubImage_clipped = function(sxy, swh, dxy, dwh) {
    var csxy = [sxy[0], sxy[1]], cscorner = [sxy[0]+swh[0], sxy[1]+swh[1]],
        cdxy = [dxy[0], dxy[1]], cdcorner = [dxy[0]+dwh[0], dxy[1]+dwh[1]];
    for(var axis = 0; axis < 2; axis++) {
        if(sxy[axis] < 0) {
            csxy[axis] = 0;
            cdxy[axis] = Math.floor(cdxy[axis] + (-sxy[axis]/swh[axis]*dwh[axis]));
        }
        if(sxy[axis]+swh[axis] >= this.wh[axis]) {
            cscorner[axis] = this.wh[axis]; // -1 ?
            cdcorner[axis] = Math.floor(cdcorner[axis] - (sxy[axis]+swh[axis]-this.wh[axis])/swh[axis]*dwh[axis]);
        }
    }
    return this.drawSubImage(csxy, [cscorner[0]-csxy[0], cscorner[1]-csxy[1]],
                             cdxy, [cdcorner[0]-cdxy[0], cdcorner[1]-cdxy[1]]);
};

GameArt.sRGB_decode = function(f) {
    if(f <= 0.03928) {
        return f*(1.0/12.92);
    } else {
        return Math.pow((f+0.055)*(1.0/1.055), 2.4);
    }
};
GameArt.sRGB_to_float = function(c) { return GameArt.sRGB_decode(c/255.0); };
GameArt.sRGB_encode = function(f) {
    if(f <= 0.00304) {
        return f*12.92;
    } else {
        return 1.055*Math.pow(f, 1.0/2.4) - 0.055;
    }
};
GameArt.float_to_sRGB = function(f) { return Math.min(Math.max(Math.floor(255.0*GameArt.sRGB_encode(f) + 0.5), 0), 255); };

// use an offscreen canvas to derive a tinted version from an HTML Image element
/** @param {Image} img
    @param {Array.<number>} origin
    @param {Array.<number>} wh
    @param {Array.<number>} tint
    @param {number=} saturation
    @param {Image=} mask_img */
GameArt.make_tinted_image = function(img, origin, wh, tint, saturation, mask_img) {
    var ret = new Image();
    var osc = null, con = null, data = null, pixels = null, data_url = null;
    try {
        osc = document.createElement('canvas');
        osc.width = wh[0]; osc.height = wh[1];
        con = osc.getContext('2d');
        if(origin) {
            con.drawImage(img, origin[0], origin[1], wh[0], wh[1], 0, 0, wh[0], wh[1]);
        } else {
            con.drawImage(img, 0, 0);
        }
        data = con.getImageData(0, 0, wh[0], wh[1]);
        pixels = data.data;

        var pixels_mask = null;
        if(mask_img) {
            if(origin) { throw Error('subimage masking not supported'); }
            var osc_mask = document.createElement('canvas');
            osc_mask.width = wh[0]; osc_mask.height = wh[1];
            var con_mask = osc_mask.getContext('2d');
            con_mask.drawImage(mask_img, 0, 0);
            var data_mask = con_mask.getImageData(0, 0, wh[0], wh[1]);
            pixels_mask = data_mask.data;
        }

        for(var i = 0; i < pixels.length; i += 4) {
            var mask = (pixels_mask ? GameArt.sRGB_to_float(pixels_mask[i+0]) : 1);
            var s = new Array(4);

            // load and sRGB decode
            for(var chn = 0; chn < 4; chn += 1) {
                s[chn] = GameArt.sRGB_to_float(pixels[i+chn]);
            }

            // perform saturation adjustment
            if(saturation != 1) {
                var lum = 0.3*s[0] + 0.59*s[1] + 0.11*s[2];
                s[0] = Math.max(0, s[0] + (1-saturation) * (lum - s[0]));
                s[1] = Math.max(0, s[1] + (1-saturation) * (lum - s[1]));
                s[2] = Math.max(0, s[2] + (1-saturation) * (lum - s[2]));
            }

            // perform linear RGB tinting
            if(tint) {
                for(var chn = 0; chn < 4; chn += 1) {
                    s[chn] = s[chn] + mask * (tint[chn]*s[chn] - s[chn]);
                }

                //pixels[i+3] = Math.min(Math.max(Math.floor(255.0*tint[3]*(pixels[i+3]/255.0) + 0.5), 0), 255);
            }

            // sRGB encode and store
            for(var chn = 0; chn < 4; chn += 1) {
                pixels[i+chn] = GameArt.float_to_sRGB(s[chn]);
            }
        }
        con.putImageData(data, 0, 0);
        data_url = osc.toDataURL();
        // XXX no this doesn't fix it ret.crossOrigin = ''; // might avoid the security exceptions we've been seeing?
        ret.src = data_url;
    } catch(e) {
        log_exception(e, 'make_tinted_image: osc = '+(osc||'null').toString()+' con = '+(con||'null').toString()+' data = '+(data||'null').toString()+' pixels = '+(pixels||'null').toString()+' data_url = '+(data_url||'null').toString()+' ret = '+(ret||'null').toString());
    }
    return ret;
};

// TintedImage adds an offscreen canvas version of the image that can be used for tinting effects

// shared library of tinted versions of sprites
GameArt.tint_library = {};
GameArt.tint_library_key = function(filename, tint, saturation) {
    if(tint === null) { tint = [1,1,1,1]; }
    return filename + ':' + tint.map(function (x) { return x.toFixed(2); }).join(',') + ',' + saturation.toFixed(2);
};

/** @constructor
  * @extends GameArt.Image */
GameArt.TintedImage = function(filename, origin, wh, load_priority, delay_load, tint, saturation, tint_share, tint_mask) {
    goog.base(this, filename, origin, wh, load_priority, delay_load);
    if(this.entry) { this.entry.needs_cors = true; }
    this.tint = tint;
    this.saturation = saturation;
    this.tint_done = false;
    this.tint_share = tint_share;
    this.tint_mask = tint_mask;
    if(this.tint_mask && this.tint_mask.entry) {
        this.tint_mask.entry.needs_cors = true;
    }
};
goog.inherits(GameArt.TintedImage, GameArt.Image);

// have to override this because the HTMLImageElement returned from
// make_tinted_image() may be missing the 'complete' property, even though it's OK...
GameArt.TintedImage.prototype.check_for_badness = function() {
    if(this.tint_done) {
        return false;
    } else {
        return goog.base(this, 'check_for_badness');
    }
};
GameArt.TintedImage.prototype.ready_to_draw = function() {
    return !!this.tint_done;
};
GameArt.TintedImage.prototype.prep_for_draw = function() {
    if(!goog.base(this, 'prep_for_draw')) { return false; }

    // lazily right before first draw, overwrite the HTML image
    // element member with a tinted version.

    if(this.img && this.data_loaded && !this.tint_done) {
        if(this.tint_mask && !this.tint_mask.prep_for_draw()) { return false; }

        this.tint_done = true;
        if(!this.tint_share) {
            // make private tinted copy of just the subimage area
            this.img = GameArt.make_tinted_image(this.img, this.origin, this.wh, this.tint, this.saturation);
            this.origin = [0,0];
        } else {
            // tint the entire sprite sheet and share with other instances
            var key = GameArt.tint_library_key(this.entry.filename, this.tint, this.saturation);
            if(!(key in GameArt.tint_library)) {
                // note: pass full sheet img.width/height here, not the subimage size (this.wh)
                GameArt.tint_library[key] = GameArt.make_tinted_image(this.img, null, [this.img.width,this.img.height], this.tint, this.saturation, (this.tint_mask ? this.tint_mask.img : null));
            }
            this.img = GameArt.tint_library[key];
        }
    }
    return true;
};




/** @constructor */
GameArt.Sound = function(filename, volume, priority, load_priority, delay_load, kind) {
    if(!GameArt.enable_audio) {
        this.entry = null;
        this.audio = null;
        return;
    }

    this.data_loaded = false;
    this.delay_load = delay_load;
    this.filename = filename.replace('$AUDIO_CODEC', GameArt.audio_codec);

    this.volume = volume;
    this.priority = priority;
    this.kind = kind;

    // we have to remember if loop() or fadeTo() was called while the
    // data was still loading, so that we can apply the appropriate effect
    // as soon as the download finishes.
    this.load_looped = false;
    this.load_faded = -1;
    this.play_on_load = -1;

    // WORKAROUND for bad browser behavior mixing image and audio downloads:
    // force audio samples to be downloaded lazily even if attached to a non-lazy asset
    if(load_priority >= GameArt.essential_priority) {
        load_priority = GameArt.essential_priority - 40;
    }

    if(this.filename in GameArt.file_list) {
        // attach to existing download request
        var entry = GameArt.file_list[this.filename];
        this.entry = entry;
        this.audio = null; // will be set by start_load
        entry.gameart_objects.push(this);
        entry.priority = Math.max(entry.priority, load_priority);
        if(!this.delay_load) { entry.delay_load = false; }
    } else {
        var entry = {};
        entry.kind = GameArt.file_kinds.AUDIO;
        entry.delay_load = this.delay_load;
        entry.sample = null;
        entry.priority = load_priority;
        entry.gameart_objects = [this];
        entry.filename = this.filename;
        entry.watchdog = null;

        // function that is called to begin the download request
        entry.start_load = function (e) {

            // function that is called when the download completes
            var success_cb = (function(entry) { return function() {
                if(entry.watchdog) {
                    window.clearTimeout(entry.watchdog);
                    entry.watchdog = null;
                }
                for(var i = 0; i < entry.gameart_objects.length; i++) {
                    var snd = entry.gameart_objects[i];
                    snd.data_loaded = true;
                    if(snd.load_looped) {
                        snd.audio.loop();
                        snd.play(GameArt.time);
                    } else if(snd.play_on_load > 0) {
                        snd.play(snd.play_on_load);
                        snd.play_on_load = -1;
                    }
                    if(snd.load_faded != -1) {
                        snd.fadeTo(snd.load_faded, 500);
                    }
                }
                GameArt.image_onload(entry.filename);
            }; })(e);

            // called when download fails
            var fail_cb = (function(entry) { return function() {
                if(entry.watchdog) {
                    window.clearTimeout(entry.watchdog);
                    entry.watchdog = null;
                }
                GameArt.image_onerror(entry.filename, 'audio_sample_onerror');
            }; })(e);

            e.sample = GameArt.audio_driver.create_sample(GameArt.art_url(e.filename, false), e.kind, success_cb, fail_cb);

            for(var i = 0; i < entry.gameart_objects.length; i++) {
                entry.gameart_objects[i].audio = e.sample;
            }

            e.sample.load();

            if(gamedata['client']['art_download_timeout']['audio'] > 0) {
                e.watchdog = window.setTimeout((function (_e) { return function() {
                    GameArt.image_ontimeout(_e.filename);
                }; })(e), 1000 * gamedata['client']['art_download_timeout']['audio']);
            }
        };

        this.entry = entry;
        GameArt.file_list[this.filename] = entry;
    }
};


/** @param {number} t */
GameArt.Sound.prototype.stop = function(t) { if(this.audio && this.data_loaded) { this.audio.stop(t); } };

GameArt.Sound.prototype.setTime = function(t) { if(this.audio && this.data_loaded) { this.audio.setTime(t); } };
GameArt.Sound.prototype.fadeIn = function(t) { this.fadeTo(100, t); }
GameArt.Sound.prototype.fadeOut = function(t) { this.fadeTo(0, t); }
GameArt.Sound.prototype.fadeTo = function(vol, t) {
    this.load_faded = vol;
    this.volume = vol;
    if(!this.entry) { return; }
    if(!this.audio) { this.check_delay_load(); return; }
    if(!this.data_loaded) { return; }
    this.audio.fadeTo(GameArt.music_volume * vol * gamedata['client']['global_audio_volume'], GameArt.time, t);
};
GameArt.Sound.prototype.loop = function() {
    this.load_looped = true;
    if(!this.entry) { return; }
    if(!this.audio) { this.check_delay_load(); return; }
    if(!this.data_loaded) { return; }
    this.audio.loop();
};
GameArt.Sound.prototype.unloop = function() {
    this.load_looped = false;
    if(this.audio && this.data_loaded) { this.audio.unloop(); }
};

GameArt.Sound.prototype.check_delay_load = function() {
    if(!this.entry || !this.entry.delay_load || this.entry.dl_started) { return; }

    if(GameArt.dl_inflight_count >= GameArt.dl_inflight_max) { return; }
    GameArt.dl_inflight_count += 1;

    this.entry.dl_started = true;
    this.entry.start_load(this.entry);
};

GameArt.Sound.prototype.play = function(time) {
    if(isNaN(time) || time < 0.0) {
        console.log('play() at invalid time '+time+' on '+this.filename);
        // fix it up
        time = GameArt.time;
    }

    if(!this.entry) { return false; }

    if(GameArt.sound_volume <= 0) {
        return true;
    }

    if(!this.audio) {
        this.play_on_load = time;
        this.check_delay_load();
        return true;
    }

    if(!this.data_loaded) {
        this.play_on_load = time;
        return true;
    }

    //  normal play
    var dur = this.audio.get_duration();
    if(!dur || isNaN(dur) || dur < 0.001) { console.log('bad audio duration '+dur+' on '+this.filename); }
    if(GameArt.channel_governor && !GameArt.channel_governor.get_chan(time, time + dur)) {
        //console.log('ran out of channels to play '+this.filename);
        return false;
    }
    return this.audio.play(time, 100*this.volume*GameArt.sound_volume*gamedata['client']['global_audio_volume']);
};

