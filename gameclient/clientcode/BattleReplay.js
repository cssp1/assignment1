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
    @param {number} end_client_time - cut off recording at this client_time (-1 for unlimited)
    Normally the battle should end and recording should stop before this. But if the client's
    clock is wonky, we might still send snapshots past that time. Currently we continue to
    record and upload snapshots, but the player will just ignore anything with tick_time beyond the end.
*/
BattleReplay.Recorder = function(world, token, end_client_time) {
    this.world = world;
    this.token = token;
    this.end_client_time = end_client_time;
    this.snapshots = []; // cleared after each flush
    this.snapshot_count = 0;
    this.listen_keys = {};
    this.diff_snap = null;
    this.sent_lines = 0;

    /** @type {Object<string,?>|null} */
    this.header = null; // initialized in start()

    // parameter to control flush interval. By default, flush no fewer than 50 snapshots at once for compression efficiency.
    this.min_snapshots_to_flush = /** @type {number} */ (gamedata['client']['replay_min_snapshots_to_flush']);
};
BattleReplay.Recorder.prototype.start = function() {
    if('before_control' in this.listen_keys) { throw Error('already started'); }

    // cut-down version of battle summary
    this.header = {'replay_version': gamedata['replay_version'] || 0,
                   'server_time_according_to_client': server_time // unreliable
                  };
    if(this.end_client_time > 0) {
        this.header['end_client_time'] = this.end_client_time;
    }
    if(this.world.base.base_landlord_id === session.user_id) {
        // defending
        this.header['attacker_name'] = session.incoming_attacker_name || 'Unknown';
        this.header['defender_name'] = player.get_ui_name();
        this.header['defender_level'] = player.resource_state['player_level'];
    } else {
        // attacking
        this.header['attacker_name'] = player.get_ui_name();
        this.header['attacker_level'] = player.resource_state['player_level'];
        this.header['defender_name'] = session.ui_name;
        this.header['defender_level'] = enemy.resource_state['player_level'];
    }

    // need to grab objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys['before_control'] = this.world.listen('before_control', this.before_control, false, this);
    this.listen_keys['before_projectile_effects'] = this.world.listen('before_projectile_effects', this.before_projectile_effects, false, this);
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
    /*
    if(player.is_developer()) {
        console.log('Recorded snapshot '+this.snapshot_count.toString());
    }
    */
    var snap = {'tick_time': this.world.last_tick_time,
                'objects': this.world.objects.serialize_incremental()};
    if(this.snapshots.length < 1) {
        // grab full base on first snapshot only
        snap['base'] = this.world.base.serialize();
    } else {
        // look for base power state changes
        var base_snap = this.world.base.serialize_incremental();
        if(base_snap) {
            snap['base'] = base_snap;
        }
    }
    this.snapshots.push(snap);
    this.snapshot_count += 1;

    // uncomment this line to enable checking which fields mutated across the World control passes
    // XXX note: this breaks playback since the incremental serialization is stateful
    //this.diff_snap = this.world.objects.serialize();
};
BattleReplay.Recorder.prototype.before_projectile_effects = function() {
    this.compare_snapshots('run_control');
    // serialize just the "header" and the projectile effects
    var eng = this.world.combat_engine;
    var snap = this.snapshots[this.snapshots.length-1]['combat_engine'] = {
        'cur_tick': eng.cur_tick.get(),
        'cur_client_time': eng.cur_client_time};
    var proj = eng.projectile_queue.serialize_incremental();
    if(proj) {
        snap['projectile_queue'] = proj;
    }
};
BattleReplay.Recorder.prototype.before_damage_effects = function() {
    this.compare_snapshots('projectile effects');
    // serialize the rest of the combat engine
    var eng = this.world.combat_engine;
    var snap = this.snapshots[this.snapshots.length-1]['combat_engine'];
    var dmg;

    // XXXXXX CombatEngine.Queue.serialize_incremental() doesn't work
    // for the first snapshot if existing damage effects are queued.
    // This is due to the placement of damage_effect_queue.clear_dirty_added()
    // which will clear out dirty_added on the previous tick before recording starts.
    // Until a proper fix is made, work around this by using non-incremental serialization
    // on the first tick.
    if(this.snapshots.length === 1) {
        dmg = eng.damage_effect_queue.serialize();
    } else {
        dmg = eng.damage_effect_queue.serialize_incremental();
    }

    if(dmg) {
        snap['damage_effect_queue'] = dmg;
    }
    var item = eng.item_log.serialize_incremental();
    if(item) {
        snap['item_log'] = item;
    }
    var anno = eng.annotation_log.serialize_incremental();
    if(anno) {
        snap['annotation_log'] = anno;
    }
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
            to_send = [this.header].concat(to_send);
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

    var header = /** @type {!Object<string,?>} */ (JSON.parse(lines[0]));
    var cur_ver = gamedata['replay_version'] || 0;
    var header_ver = ('replay_version' in header ? header['replay_version'] : header['version']);
    if(header_ver !== cur_ver) {
        console.log('Replay version mismatch: '+header_ver.toString()+' vs '+cur_ver.toString());
        return null;
    }
    var snapshots = goog.array.map(lines.slice(1, lines.length), function(f) { return JSON.parse(f); });
    return new BattleReplay.Player(header, snapshots);
};

/** LINK FROM RECORDER TO PLAYER
    @param {!BattleReplay.Recorder} recorder */
BattleReplay.replay = function(recorder) {
    if(recorder.snapshots.length < 1) { throw Error('recorded not initialized'); }
    return new BattleReplay.Player({}, recorder.snapshots);
};

/** PLAYER
    @constructor @struct
    @param {!Object<string,?>} header
    @param {!Array<!Object>} snapshots
*/
BattleReplay.Player = function(header, snapshots) {
    if(snapshots.length < 1) { throw Error('no snapshots'); }

    // chop off excess snapshots that were recorded after end_client_time
    if(snapshots.length > 2 && 'end_client_time' in header &&
       header['end_client_time'] > 0 && header['end_client_time'] < snapshots[snapshots.length-1]['tick_time']) {
        var last_index = goog.array.binarySelect(snapshots, function(entry) {
            if(entry['tick_time'] > header['end_client_time']) {
                return -1;
            } else if(entry['tick_time'] < header['end_client_time']) {
                return 1;
            }
            return 0;
        });
        if(last_index < 0) { // no exact match
            last_index = Math.max(1, Math.min(-(last_index+1) - 1, snapshots.length-1));
        }
        if(last_index < snapshots.length - 1) {
            if(player.is_developer()) {
                console.log('chopping to '+last_index.toString());
            }
            snapshots = snapshots.slice(0, last_index+1);
        }
    }

    if(!('base' in snapshots[0])) { throw Error('first snapshot does not contain base'); }
    this.header = header;
    this.snapshots = BattleReplay.Player.migrate_snapshots(snapshots);
    this.world = new World.World(new Base.Base(snapshots[0]['base']['base_id'], snapshots[0]['base']), [], false);
    this.world.ai_paused = true;
    //this.world.control_paused = true;
    // *throw away* damage effects added by our control code, in favor of the recorded ones
    this.world.combat_engine.accept_damage_effects = false;
    this.index = -1;
    // need to apply objects snapshot before control pass, but wait until after control pass for damage effects
    this.listen_keys = {'before_control': this.world.listen('before_control', this.before_control, false, this),
                        'before_projectile_effects': this.world.listen('before_projectile_effects', this.before_projectile_effects, false, this),
                        'before_damage_effects': this.world.listen('before_damage_effects', this.before_damage_effects, false, this)};
    console.log('Initialized replay with '+this.snapshots.length.toString()+' snapshots');
};
/** @return {number} */
BattleReplay.Player.prototype.num_ticks = function() { return this.snapshots.length; };
/** @return {number} */
BattleReplay.Player.prototype.cur_tick = function() { return this.index; };
/** @private */
BattleReplay.Player.prototype.before_control = function(event) {
    this.index += 1;
    if(this.index >= this.snapshots.length) {
        this.index = 0;
    }
    if(this.index === 0) {
        this.world.objects.clear();
        this.world.combat_engine.clear_queued_effects();
    }
    if(player.is_developer()) {
        console.log('Applying snapshot '+this.index.toString()+' of tick '+this.snapshots[this.index]['combat_engine']['cur_tick'].toString());
    }

    if('base' in this.snapshots[this.index]) {
        this.world.base.apply_snapshot(this.snapshots[this.index]['base']);
    }
    this.world.objects.apply_snapshot(this.snapshots[this.index]['objects']);
};
/** @private */
BattleReplay.Player.prototype.before_projectile_effects = function(event) {
    var combat_snap = this.snapshots[this.index]['combat_engine'];
    this.world.combat_engine.cur_tick = new GameTypes.TickCount(combat_snap['cur_tick']);
    this.world.combat_engine.cur_client_time = combat_snap['cur_client_time'];
    if('projectile_queue' in combat_snap) {
        this.world.combat_engine.projectile_queue.apply_snapshot(combat_snap['projectile_queue']);
    }
};
/** @private */
BattleReplay.Player.prototype.before_damage_effects = function(event) {
    var combat_snap = this.snapshots[this.index]['combat_engine'];

    // grab any item-usage events and post them to on-screen log
    if('item_log' in combat_snap && ('queue' in combat_snap['item_log'] || ('added' in combat_snap['item_log']))) {
        goog.array.forEach(combat_snap['item_log']['queue'] || combat_snap['item_log']['added'], function(event) {
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
    if('annotation_log' in combat_snap && ('queue' in combat_snap['annotation_log'] || ('added' in combat_snap['annotation_log']))) {
        goog.array.forEach(combat_snap['annotation_log']['queue'] || combat_snap['annotation_log']['added'], function(event) {
            if(event['kind'] === 'BattleStarAnnotation' && event['name'] in gamedata['battle_stars']) {
                user_log.msg(gamedata['battle_stars'][event['name']]['ui_name'], new SPUI.Color(1,1,0,1));
            }
        }, this);
    }

    if('damage_effect_queue' in combat_snap) {
        this.world.combat_engine.damage_effect_queue.apply_snapshot(combat_snap['damage_effect_queue']);
    }

    if(this.index >= this.snapshots.length - 1) {
        if(!this.world.control_paused) { // pause at end
            this.world.control_paused = true;
        }
        this.index = this.snapshots.length - 1;
    }
};
BattleReplay.Player.prototype.restart = function() {
    this.index = -1;
    if(this.world.control_paused) { // force a single-step to reset
        this.world.control_step = 1;
    }
};

/** Handle any backwards-compatibility issues with replay snapshots
    Return a migrated version of the snapshot array */
BattleReplay.Player.migrate_snapshots = function(snapshots) {
    return goog.array.map(snapshots, BattleReplay.Player.migrate_snapshot);
};
BattleReplay.Player.migrate_snapshot = function(original_snap) {
    var snap = original_snap; // will return unmodified original if there are no changes
    if('combat_engine' in snap) {
        var combat_engine = snap['combat_engine'];

        // transform flat arrays to queue replacements
        goog.array.forEach(['damage_effect_queue', 'projectile_queue', 'item_log', 'annotation_log'], function(kind) {
            if(kind in combat_engine && combat_engine[kind] instanceof Array) {
                // copy-on-write
                if(snap === original_snap) { snap = goog.object.clone(original_snap); combat_engine = snap['combat_engine']; }
                combat_engine[kind] = {'queue': combat_engine[kind] };
            }
        });
        // transform queue increments to new format
        goog.array.forEach(['damage_effect_queue', 'projectile_queue'], function(kind) {
            if(kind + '_added' in combat_engine) {
                // copy-on-write
                if(snap === original_snap) { snap = goog.object.clone(original_snap); combat_engine = snap['combat_engine']; }
                // note: don't include a 'length' because it will probably mis-match what the engine expects
                // (due to incorrect serialization timing in legacy replays)
                combat_engine[kind] = {'added': combat_engine[kind+'_added'] };
                delete combat_engine[kind+'_added'];
                if(kind+'_length' in combat_engine) {
                    delete combat_engine[kind+'_length'];
                }
            }
        });
    }
    return snap;
};
