goog.provide('SPAudio');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    Note: in the outward-facing API, "volume" should be in the range 0.0-1.0 and times are in seconds.
*/

goog.require('buzz');
goog.require('spin_SoundManager2');

SPAudio = {};

/** @constructor */
SPAudio.Driver = function() {
    this.kind = 'unknown';
};

////////////////////////////////////////////////////////////////////////////////////////
// SoundManager2 DRIVER
////////////////////////////////////////////////////////////////////////////////////////

/** @constructor
  * @extends SPAudio.Driver */
SPAudio.SM2Driver = function(client_time, swf_location) {
    this.kind = 'sm2';
    this.sm2 = new SoundManager(swf_location);
    window['soundManager'] = this.sm2;
    this.sm2.flashVersion = 9;
    this.sm2.consoleOnly = true;
    this.sm2.debugMode = false;
//    this.sm2.debugFlash = true;
    this.sm2.preferFlash = true;
    this.sm2.flashLoadTimeout = 30000;
    this.sm2.useHighPerformance = true;
    this.sm2.useHTML5Audio = false;
    this.faders = [];

    // stupid async init...
    this.sample_queue = [];
    this.sm2.onready((function (driver) { return function() {
        for(var i = 0; i < driver.sample_queue.length; i++) {
            driver.sample_queue[i].do_load();
        }
        driver.sample_queue = null;
    }; })(this));

    this.sm2.beginDelayedInit();
};

goog.inherits(SPAudio.SM2Driver, SPAudio.Driver);
SPAudio.SM2Driver.prototype.get_codec = function() { return 'mp3'; };

SPAudio.SM2Driver.prototype.sync_time = function(client_time) {
    for(var i = 0; i < this.faders.length; i++) {
        this.faders[i].fade_step(client_time);
    }
};


SPAudio.SM2Driver.prototype.create_sample = function(url, kind, success_cb, fail_cb) {
    return new SPAudio.SM2Sample(this, url, kind, success_cb, fail_cb);
};

/** @constructor */
SPAudio.SM2Sample = function(driver, url, kind, success_cb, fail_cb) {
    this.driver = driver;
    this.url = url;
    this.success_cb = success_cb;
    this.fail_cb = fail_cb;
    this.obj = null;
    this.loaded = false;
    this.play_looped = false;
    this.last_volume = -1;
    this.fade_start = -1;
    this.fade_end = -1;
    this.fade_vol = -1;
};

SPAudio.SM2Sample.prototype.load = function() {
    if(this.driver.sample_queue !== null) {
        // SM2 init not done, queue it
        this.driver.sample_queue.push(this);
        return;
    }
    this.do_load();
};

SPAudio.SM2Sample.prototype.loop = function() {
    this.play_looped = true;
    if(this.loaded && !this.obj.playState) {
        // XXX hack until we separate streaming audio
        this.play((new Date()).getTime()/1000, 0.25);
    }
};

SPAudio.SM2Sample.prototype.unloop = function() {
    this.play_looped = false;
};

SPAudio.SM2Sample.prototype.do_load = function() {
    this.obj = this.driver.sm2.createSound({
        id:this.url, url:this.url,
        autoLoad: true, autoPlay: false, stream: false,
        onload: (function(sample) { return function(success) {
            if(success) {
                sample.loaded = true;
                sample.success_cb();
            } else {
                sample.fail_cb();
            }
        }; })(this)
    });
};
SPAudio.SM2Sample.prototype.play = function(t, v) {
    if(!this.loaded) { return false; }
    if(!this.play_looped || !this.obj.playState) {
        this.obj.play({volume:v*100, loops: this.play_looped ? 999 : 1, multiShot: !this.play_looped});
    }
    this.last_volume = v;
    return true;
};
SPAudio.SM2Sample.prototype.stop = function(t) {
    if(!this.loaded) { return; }
    this.obj.stop();
    this.last_volume = -1;
};
SPAudio.SM2Sample.prototype.get_duration = function() { return (this.loaded ? this.obj.duration/1000.0 : -1); };

SPAudio.SM2Sample.prototype.fadeTo = function(v, start_time, dur) {
    for(var i = 0; i < this.driver.faders.length; i++) {
        if(this === this.driver.faders[i]) {
            break;
        }
    }
    if(i >= this.driver.faders.length) { this.driver.faders.push(this); }

    this.fade_start = start_time;
    this.fade_end = start_time + dur;
    this.fade_vol = v;
};

SPAudio.SM2Sample.prototype.fade_step = function(t) {
    if(this.fade_start < 0) { return; }
    var fade_dur = this.fade_end - this.fade_start;
    var progress = (fade_dur > 0 ? (t - this.fade_start) / fade_dur : 1);
    if(progress < 0) { return; }
    if(progress >= 1) {
        progress = 1;
        this.last_volume = this.fade_vol;
        this.fade_start = -1;
        this.fade_end = -1;
        if(this.fade_vol <= 0) { this.stop(t); console.log('stop at end of fade'); }
    }
    if(this.loaded) {
        var vol = this.last_volume + progress * (this.fade_vol - this.last_volume);
        this.obj.setVolume(100*vol);
    }
};

SPAudio.SM2Sample.prototype.setTime = function(t) { console.log('SM2Sample.setTime not implemented'); };

////////////////////////////////////////////////////////////////////////////////////////
// BUZZ DRIVER
////////////////////////////////////////////////////////////////////////////////////////

/** @constructor
  * @extends SPAudio.Driver */
SPAudio.BuzzDriver = function(client_time) {
    this.kind = 'buzz';
};
goog.inherits(SPAudio.BuzzDriver, SPAudio.Driver);

SPAudio.BuzzDriver.prototype.get_codec = function() {
  if(!buzz.isMP3Supported() && buzz.isOGGSupported()) {
      return 'ogg';
  } else {
      return 'mp3';
  }
};

SPAudio.BuzzDriver.prototype.sync_time = function(t) {};

SPAudio.BuzzDriver.prototype.create_sample = function(url, kind, success_cb, fail_cb) {
    return new SPAudio.BuzzSample(url, success_cb, fail_cb);
};

/** @constructor */
SPAudio.BuzzSample = function(url, success_cb, fail_cb) {
    this.url = url;
    this.buzz_sound = new buzz.sound(url, {preload:true});
    this.duration = -1;
    this.end_time = -1;
    this.play_looped = false;

    var wrapped_success_cb = (function (samp, cb) { return function(unused) {
        samp.duration = samp.buzz_sound.sound.duration;
        cb();
    }; })(this, success_cb);

    var wrapped_fail_cb = (function (samp, cb) { return function(unused) {
        if(samp.buzz_sound.getNetworkStateCode() === 3) { // NO_SOURCE
            cb();
        }
    }; })(this, fail_cb);

    // function that is called when the download completes
    this.buzz_sound.bind('canplaythrough', wrapped_success_cb);
    this.buzz_sound.bind('abort error empty loadstart', wrapped_fail_cb);
};
SPAudio.BuzzSample.prototype.load = function() { this.buzz_sound.load(); };
SPAudio.BuzzSample.prototype.loop = function() { this.play_looped = true; this.buzz_sound.loop(); };
SPAudio.BuzzSample.prototype.get_duration = function() { return this.duration; };
SPAudio.BuzzSample.prototype.unloop = function() { this.play_looped = false; this.buzz_sound.unloop(); };
SPAudio.BuzzSample.prototype.play = function(time, volume) {
    // prevent overlap on non-looped samples
    if(!this.play_looped && time > 0 && time < this.end_time) { return false; }
    this.buzz_sound.setVolume(100*volume);

    this.end_time = time + this.duration;
    try {
        this.buzz_sound.play();
    } catch (ex) {
        log_exception(ex, 'buzz.play "'+this.url+'"');
    }
    return true;
};
SPAudio.BuzzSample.prototype.stop = function(t) { this.buzz_sound.stop(); };
SPAudio.BuzzSample.prototype.setTime = function(t) { this.buzz_sound.setTime(t); };
SPAudio.BuzzSample.prototype.fadeTo = function(v, start, t) {
    try {
        this.buzz_sound.fadeTo(100*v, 1000*t);
    } catch (ex) {
        log_exception(ex, 'buzz.fadeTo "'+this.url+'"');
    }
};

////////////////////////////////////////////////////////////////////////////////////////
// AudioContext (WebKit/Chrome) DRIVER
////////////////////////////////////////////////////////////////////////////////////////

SPAudio.ACDriverImpl = {
    WEBKIT: 1,
    WEB_AUDIO: 2
};

/** @constructor
  * @extends SPAudio.Driver */
SPAudio.ACDriver = function(client_time) {
    this.kind = 'AudioContext';

    // try both Chrome/webkit and final Web Audio implementations
    if(typeof(AudioContext) != 'undefined') {
        this.context = new AudioContext();
        this.impl = SPAudio.ACDriverImpl.WEB_AUDIO;
    } else {
        this.context = new webkitAudioContext();
        this.impl = SPAudio.ACDriverImpl.WEBKIT;
        // name changed from Chrome implementation (createGainNode) to final Web Audio API (createGain)
        if(typeof(this.context['createGain']) === 'undefined') {
            this.context['createGain'] = this.context['createGainNode'];
        }
    }

    this.time_offset = this.context.currentTime - client_time;
    this.faders = [];
}
goog.inherits(SPAudio.ACDriver, SPAudio.Driver);

SPAudio.ACDriver.prototype.get_codec = function() {
    if(navigator.userAgent.indexOf('Edge/') >= 0) {
        return 'mp3'; // MS Edge has no OGG support
    }
    return 'ogg';
};

SPAudio.ACDriver.prototype.sync_time = function(client_time) {
    this.time_offset = this.context.currentTime - client_time;
    for(var i = 0; i < this.faders.length; i++) {
        this.faders[i].fade_step(client_time);
    }
};

SPAudio.ACDriver.prototype.create_sample = function(url, kind, success_cb, fail_cb) {
    return new SPAudio.ACSample(this, url, success_cb, fail_cb);
};

/** @constructor */
SPAudio.ACSample = function(driver, url, success_cb, fail_cb) {
    this.driver = driver;
    this.url = url;
    this.buffer = null;
    /** @type {?} */
    this.last_voice = null;
    this.last_gain = null;
    this.last_volume = -1;
    this.fade_start = -1;
    this.fade_end = -1;
    this.fade_vol = -1;

    this.success_cb = success_cb;
    this.fail_cb = fail_cb;
    this.play_looped = false;

    this.request = new XMLHttpRequest();
    this.request.open('GET', url, true);
    this.request.responseType = 'arraybuffer';

    var onload = (function(sample) { return function() {
        if(sample.driver.impl == SPAudio.ACDriverImpl.WEBKIT) {
            // old synchronous decode
            sample.buffer = sample.driver.context.createBuffer(sample.request.response, false);
            sample.success_cb();
        } else {
            // new async decode - note: Chrome may be capable of this now
            sample.driver.context.decodeAudioData(sample.request.response, (function (_sample) { return function(newbuf) {
                _sample.buffer = newbuf;
                _sample.success_cb();
            }; })(sample), (function (_sample) { return function() { _sample.fail_cb(); }; })(sample));
        }
    }; })(this);

    var onerror = (function(sample) { return function() {
        sample.fail_cb();
    }; })(this);

    this.request.onload = onload;
    this.request.onerror = onerror;
};
SPAudio.ACSample.prototype.load = function() { this.request.send(); };
SPAudio.ACSample.prototype.get_duration = function() { return (this.buffer ? this.buffer['duration'] : -1); };
SPAudio.ACSample.prototype.play = function(t, v) {
    if(this.play_looped && this.last_voice != null) {
        console.log('second play() on looped audio voice!');
        return false;
    }

    var voice = this.driver.context.createBufferSource();
    voice['buffer'] = this.buffer;
    voice['loop'] = this.play_looped;
    var gain = this.driver.context.createGain();
    voice['connect'](gain);

    gain['gain']['value'] = v;
    gain['connect'](this.driver.context['destination']);

    // name changed from Chrome implementation (noteOn) to final Web Audio API (start)
    if(typeof(voice['start']) != 'undefined') {
        voice['start'](t + this.driver.time_offset);
    } else {
        voice['noteOn'](t + this.driver.time_offset);
    }

    this.last_voice = voice;
    this.last_gain = gain;
    this.last_volume = v;
    return true;
};

SPAudio.ACSample.prototype.loop = function() {
    this.play_looped = true;
    if(this.last_voice) {
        this.last_voice['loop'] = true;
    } else {
        // XXX hack until we separate streaming audio
        this.play((new Date()).getTime()/1000, 0.25);
    }
};
SPAudio.ACSample.prototype.unloop = function() {
    this.play_looped = false;
    if(this.last_voice) { this.last_voice['loop'] = false; }
};

SPAudio.ACSample.prototype.stop = function(t) {
    if(this.last_voice) {
        // name changed from Chrome implementation (noteOff) to final Web Audio API (stop)
        if(typeof(this.last_voice['stop']) != 'undefined') {
            this.last_voice['stop'](t + this.driver.time_offset);
        } else {
            this.last_voice['noteOff'](t + this.driver.time_offset);
        }
        this.last_voice = null;
        this.last_gain = null;
        this.last_volume = -1;
        this.fade_start = -1;
        this.fade_end = -1;
        this.fade_vol = -1;
    }
};

SPAudio.ACSample.prototype.fadeTo = function(v, start_time, dur) {
    if(!this.last_voice) {
        console.log('fadeTo on non-playing sound!');
        return;
    }
    //console.log('fadeTo '+v);
    for(var i = 0; i < this.driver.faders.length; i++) {
        if(this === this.driver.faders[i]) {
            break;
        }
    }
    if(i >= this.driver.faders.length) { this.driver.faders.push(this); }

    this.fade_start = start_time;
    this.fade_end = start_time + dur;
    this.fade_vol = v;
};

SPAudio.ACSample.prototype.fade_step = function(t) {
    if(this.fade_start < 0) { return; }
    var fade_dur = this.fade_end - this.fade_start;
    var progress = (fade_dur > 0 ? (t - this.fade_start) / fade_dur : 1);
    if(progress < 0) { return; }
    if(progress >= 1) {
        progress = 1;
        this.last_volume = this.fade_vol;
        this.fade_start = -1;
        this.fade_end = -1;
        if(this.fade_vol <= 0 && this.last_voice) { this.stop(t); console.log('stop at end of fade'); }
    }
    if(this.last_voice) {
        var vol = this.last_volume + progress * (this.fade_vol - this.last_volume);
        this.last_gain['gain']['value'] = vol;
    }
};

SPAudio.ACSample.prototype.setTime = function(t) { console.log('ACSample.setTime NOT IMPLEMENTED'); };

