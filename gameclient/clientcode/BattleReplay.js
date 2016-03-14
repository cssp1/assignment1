goog.provide('BattleReplay');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('Base');
goog.require('World');
goog.require('SPFX'); // only for item usage display - move out of here?
goog.require('ItemDisplay'); // only for item usage display - move out of here?
goog.require('SPGzip'); // for replay uploads
goog.require('SPStringCoding'); // for replay uploads
goog.require('goog.crypt.base64'); // for replay uploads
goog.require('goog.array');
goog.require('goog.object');

BattleReplay.invoke = function(log) {
    if(!log || log.length < 1 || log[0]['event_name'] !== '3820_battle_start' ||
       !log[0]['base'] || !log[0]['base_objects']) {
        throw Error('invalid battle log');
    }

    var props_3820 = log[0];

    var base = new Base.Base(props_3820['base_id'], props_3820['base']);
    var objects = [];
    goog.array.forEach(props_3820['base_objects'], function(state) {
        var obj = create_object(state, false);
        objects.push(obj);
    });

    // 3900_unit_exists always comes in one big block
    goog.array.forEach(log, function(event) {
        if(event['event_name'] === '3900_unit_exists') {
            if(goog.array.find(objects, function(x) { return x.id === event['obj_id']; }) !== null) { return; } // already in object list
            if(!('state' in event)) { throw Error('incompatible battle log: no state in 3900_unit_exists'); }
            var obj = create_object(event['state'], false);
            objects.push(obj);
        }
    });

    var world = new World.World(base, objects, false);
    session.push_world(world);
};

/** RECORDER
    @constructor @struct
    @param {!World.World} world
    @param {string} token
*/
BattleReplay.Recorder = function(world, token) {
    this.world = world;
    this.token = token;
    this.snapshots = []; // cleared after each flush
    this.snapshot_count = 0;
    this.listen_keys = {};
    this.diff_snap = null;
    this.sent_lines = 0;

    // parameter to control flush interval. By default, flush no fewer than 50 snapshots at once for compression efficiency.
    this.min_snapshots_to_flush = /** @type {number} */ (gamedata['client']['replay_min_snapshots_to_flush']);
};
BattleReplay.Recorder.prototype.start = function() {
    if('before_control' in this.listen_keys) { throw Error('already started'); }

    // need to grab objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys['before_control'] = this.world.listen('before_control', this.before_control, false, this);
    this.listen_keys['before_damage_effects'] = this.world.listen('before_damage_effects', this.before_damage_effects, false, this);
    this.listen_keys['after_damage_effects'] = this.world.listen('after_damage_effects', this.after_damage_effects, false, this);
};
/** @private
    @param {string} reason */
BattleReplay.Recorder.prototype.compare_snapshots = function(reason) {
    if(this.diff_snap) {
        var new_snap = this.world.objects.serialize();
        console.log(reason +' diffs:');
        console.log(json_diff(this.diff_snap, new_snap));
        this.diff_snap = new_snap;
    }
};

BattleReplay.Recorder.prototype.before_control = function() {
    if(player.is_developer()) {
        console.log('Recorded snapshot '+this.snapshot_count.toString());
    }
    var snap = {'tick_time': this.world.last_tick_time,
                'objects': this.world.objects.serialize_incremental()};
    if(this.snapshots.length < 1) {
        // grab base on first snapshot only
        snap['base'] = this.world.base.serialize();
    }
    this.snapshots.push(snap);
    this.snapshot_count += 1;

    // uncomment this line to enable checking which fields mutated across the World control passes
    // XXX note: this breaks playback since the incremental serialization is stateful
    //this.diff_snap = this.world.objects.serialize();
};
BattleReplay.Recorder.prototype.before_damage_effects = function() {
    this.compare_snapshots('run_control');
    this.snapshots[this.snapshots.length-1]['combat_engine'] = this.world.combat_engine.serialize_incremental();
};
BattleReplay.Recorder.prototype.after_damage_effects = function() {
    this.compare_snapshots('damage effects');
};
BattleReplay.Recorder.prototype.stop = function() {
    goog.array.forEach(goog.object.getKeys(this.listen_keys), function(k) {
        this.world.unlistenByKey(this.listen_keys[k]);
        delete this.listen_keys[k];
    }, this);
    if(player.is_developer()) {
        console.log('Recorder stopped with '+this.snapshots.length.toString()+' snapshots');
    }
};

// A packed replay is a native JS string consisting of newline-separated lines.
// Each line is an independently-parsable JSON object.
// The first line is a header and all subsequent lines contain world snapshots.
// Lines may be sent in batches, but a batch will always contain a complete set of lines.
// (this allows the server to terminate the recording after any batch and get a valid replay).

/** Transmit one or more lines to the server
    @private
    @param {!Array<!Object>} json_obj_arr
    @param {boolean=} is_final */
BattleReplay.Recorder.prototype.send_lines = function(json_obj_arr, is_final) {

    var pack_list = goog.array.map(json_obj_arr, function(json_obj) { return JSON.stringify(json_obj); });

    pack_list.push(''); // to get a final newline on the end after join()
    var raw_string = pack_list.join('\n');

    var raw_array = SPStringCoding.js_string_to_utf8_array(raw_string);

    // note! this takes advantage of the fact that the gzip format allows you to concatenate
    // successive gzipped blobs together.
    // XXX could be made more efficient by digging in to the zlib library and sharing
    // a single stream for successive lines.
    // however, with 50 snapshots per flush, the compression ratio is only ~3% worse than smashing it all together.
    var zipped = goog.crypt.base64.encodeByteArray(SPGzip.gzip(raw_array));

    send_to_server.func(["UPLOAD_BATTLE_REPLAY", this.token, 'gzip',
                         this.sent_lines, // first_line
                         json_obj_arr.length, // n_lines
                         !!is_final,
                         raw_array.length, // raw_length (pre-base64)
                         zipped]);
    this.sent_lines += json_obj_arr.length;
};

/** Transmit any pending snapshots
    @param {boolean=} is_final */
BattleReplay.Recorder.prototype.flush = function(is_final) {
    if(!is_final && this.snapshots.length < this.min_snapshots_to_flush) { return; }

    if(this.snapshots.length > 0 || (is_final && this.snapshot_count > 0)) {
        var to_send = this.snapshots;
        this.snapshots = [];
        if(this.sent_lines === 0) {
            // prepend the header
            var header = {'version': gamedata['replay_version']};
            to_send = [header].concat(to_send);
        }
        this.send_lines(to_send, !!is_final);
    }
};

/** finalize and upload the rest of the recording */
BattleReplay.Recorder.prototype.finish = function() {
    this.flush(true);
};

/** LINK FROM DOWNLOAD TO PLAYER
    @param {string} packed - native JS string, possibly including Unicode
    @return {BattleReplay.Player|null} - null if error */
BattleReplay.replay_from_download = function(packed) {
    var lines = packed.split('\n');
    // trim trailing empty line from the final newline
    if(lines[lines.length-1] == '') {
        lines.length = lines.length - 1;
    }

    if(lines.length < 2) {
        console.log('Replay has fewer than 2 lines');
        return null;
    }

    var header = JSON.parse(lines[0]);
    var cur_ver = gamedata['replay_version'] || 0;
    if(header['version'] !== cur_ver) {
        console.log('Replay version mismatch: '+header['version'].toString()+' vs '+cur_ver.toString());
        return null;
    }
    var snapshots = goog.array.map(lines.slice(1, lines.length), function(f) { return JSON.parse(f); });
    return new BattleReplay.Player(snapshots);
};

/** LINK FROM RECORDER TO PLAYER
    @param {!BattleReplay.Recorder} recorder */
BattleReplay.replay = function(recorder) {
    if(recorder.snapshots.length < 1) { throw Error('recorded not initialized'); }
    return new BattleReplay.Player(recorder.snapshots);
};

/** PLAYER
    @constructor @struct
    @param {!Array<!Object>} snapshots
*/
BattleReplay.Player = function(snapshots) {
    if(snapshots.length < 1) { throw Error('no snapshots'); }
    if(!('base' in snapshots[0])) { throw Error('first snapshot does not contain base'); }
    this.snapshots = snapshots;
    this.world = new World.World(new Base.Base(snapshots[0]['base']['base_id'], snapshots[0]['base']), [], false);
    this.world.ai_paused = true;
    //this.world.control_paused = true;
    // *throw away* damage effects added by our control code, in favor of the recorded ones
    this.world.combat_engine.accept_damage_effects = false;
    this.index = 0;
    // need to apply objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys = {'before_control': this.world.listen('before_control', this.before_control, false, this),
                        'before_damage_effects': this.world.listen('before_damage_effects', this.before_damage_effects, false, this)};
    console.log('Initialized replay with '+this.snapshots.length.toString()+' snapshots');
};
/** @return {number} */
BattleReplay.Player.prototype.num_ticks = function() { return this.snapshots.length; };
/** @return {number} */
BattleReplay.Player.prototype.cur_tick = function() { return this.index; };
/** @private */
BattleReplay.Player.prototype.before_control = function(event) {
    console.log('Applying snapshot '+this.index.toString()+' at tick '+this.world.combat_engine.cur_tick.get());
    if(this.index === 0) {
        this.world.objects.clear();
        this.world.combat_engine.clear_queued_damage_effects();
    }
    this.world.objects.apply_snapshot(this.snapshots[this.index]['objects']);
};
/** @private */
BattleReplay.Player.prototype.before_damage_effects = function(event) {
    var combat_snap = this.snapshots[this.index]['combat_engine'];

    // grab any item-usage events and post them to on-screen log
    if('item_log' in combat_snap) {
        goog.array.forEach(combat_snap['item_log'], function(event) {
            var spec = ItemDisplay.get_inventory_item_spec(event['item']['spec']);

            if('use_effect' in spec) {
                // check for null separately from checking if the effect exists so we can use a null effect
                // in the item spec to disable the game-wide effect
                if(spec['use_effect']) {
                    this.world.fxworld._add_visual_effect([0,0], 0, [0,1,0], this.world.fxworld.now_time(), spec['use_effect'], true, null);
                }
            } else if(gamedata['client']['vfx']['item_use']) {
                this.world.fxworld._add_visual_effect([0,0], 0, [0,1,0], this.world.fxworld.now_time(), gamedata['client']['vfx']['item_use'], true, null);
            }

            var ui_text = ItemDisplay.get_inventory_item_ui_name(spec, event['item']['level'] || 1, event['item']['stack'] || 1) + " " + gamedata['strings']['combat_messages']['activated'];
            if(event['target_pos']) {
                this.world.fxworld.add_under(new SPFX.ClickFeedback(event['target_pos'], [1,1,1,1], this.world.fxworld.now_time(), 0.15));
                this.world.fxworld.add(new SPFX.CombatText(event['target_pos'], 0,
                                                           ui_text,
                                                           [1,1,0.3],
                                                           this.world.fxworld.now_time(), 3.0,
                                                           { drop_shadow: true, font_size: 20, text_style: 'thick' }));
            } else {
                user_log.msg(ui_text, new SPUI.Color(1,1,0,1));
            }
        }, this);
    }

    this.world.combat_engine.apply_snapshot(combat_snap);
    this.index += 1;
    if(this.index >= this.snapshots.length) {
        if(!this.world.control_paused) { // pause at end
            this.world.control_paused = true;
        }
        this.index = 0;
    }
};
BattleReplay.Player.prototype.restart = function() {
    this.index = 0;
    if(this.world.control_paused) { // force a single-step to reset
        this.world.control_step = 1;
    }
};
