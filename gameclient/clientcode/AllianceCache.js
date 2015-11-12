goog.provide('AllianceCache');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

// client-side alliance info cache
// this is a central respository for things we know about alliances

goog.require('goog.object');
goog.require('SPHTTP');

// imports from main.js: send_to_server

var AllianceCache = {
    entries: {}, // mapping from alliance_id -> {'pending':1} or cache entry
    callbacks: {}, // mapping from alliance_id -> list of callbacks waiting for info results
    receivers: {}, // callbacks waiting for results other than info

    batch_info_queries: [],
    last_query_tag: 0,

    turf_cache: []
};

AllianceCache.init = function() {
};

AllianceCache.turf_update = function(region_id, data) {
    // get rid of all entries for this region
    AllianceCache.turf_cache = AllianceCache.turf_cache.filter(function(entry) { return entry['region_id'] !== region_id; });
    AllianceCache.turf_cache = AllianceCache.turf_cache.concat(data);
};
AllianceCache.turf_get_leader_by_region = function(region_id) {
    var winner_entry = null;
    for(var i = 0; i < AllianceCache.turf_cache.length; i++) {
        var entry = AllianceCache.turf_cache[i];
        if(entry['region_id'] == region_id && entry['rank'] == 0) {
            if(winner_entry !== null) { // tie! no winner - return fake entry with alliance_id < 0
                return {'alliance_id':-2, 'points':entry['points']};
            } else {
                winner_entry = entry;
            }
        }
    }
    return winner_entry;
};
AllianceCache.turf_get_next_check_by_region = function(region_id) {
    for(var i = 0; i < AllianceCache.turf_cache.length; i++) {
        var entry = AllianceCache.turf_cache[i];
        if(entry['region_id'] == region_id && entry['next_check'] > 0) {
            return entry['next_check'];
        }
    }
    return -1;
};

AllianceCache.update = function(alliance_id, info) {
    if(alliance_id in AllianceCache.entries) {
        if(info === null) {
            AllianceCache.entries[alliance_id] = null;
        } else if(AllianceCache.entries[alliance_id] === null) {
            AllianceCache.entries[alliance_id] = info;
        } else {
            for(var key in info) {
                AllianceCache.entries[alliance_id][key] = info[key];
            }
        }
    } else {
        AllianceCache.entries[alliance_id] = info;
    }
};
AllianceCache.invalidate = function(alliance_id) {
    if(alliance_id in AllianceCache.entries) {
        delete AllianceCache.entries[alliance_id];
    }
};
AllianceCache.query_info_sync = function(alliance_id) {
    if(!(alliance_id in AllianceCache.entries)) { return null; }
    var entry = AllianceCache.entries[alliance_id];
    if((entry === null) || (!entry['pending'] && ('num_members' in entry))) {
        return entry;
    }
    return null;
};

/** @param {number} alliance_id
    @param {function((Object|null)) | null=} callback
    @param {Object=} props */
AllianceCache.query_info = function (alliance_id, callback, props) {
    if(!props) { props = {}; }
    var get_private_fields = props.get_private_fields;

    var entry = {'pending':0};

    if(!props.force && (alliance_id in AllianceCache.entries)) {
        entry = AllianceCache.entries[alliance_id];
        if(entry === null || (!entry['pending'] && entry['id'] && ('num_members' in entry) && (!get_private_fields || ('chat_motd' in entry)))) {
            if(callback) { callback(entry); }
            return entry;
        }
    } else if(!(alliance_id in AllianceCache.entries) || AllianceCache.entries[alliance_id] === null) {
        AllianceCache.entries[alliance_id] = entry;
    }

    if(callback) {
        if(!(alliance_id in AllianceCache.callbacks)) { AllianceCache.callbacks[alliance_id] = []; }
        AllianceCache.callbacks[alliance_id].push(callback);
    }

    if(!entry['pending']) {
        entry['pending'] = 1;
        if(get_private_fields) {
            // launch individual query
            AllianceCache.query("QUERY_ALLIANCE_INFO_PRIVATE", [alliance_id], null);
        } else {
            // queue batch query
            AllianceCache.batch_info_queries.push(alliance_id);
        }
    }
    return null;
};

AllianceCache.launch_batch_queries = function() {
    if(AllianceCache.batch_info_queries.length > 0) {
        var ls = AllianceCache.batch_info_queries;
        AllianceCache.batch_info_queries = [];
        AllianceCache.query("QUERY_ALLIANCE_INFO", ls, null);
    }
};

AllianceCache.query_members = function (alliance_id, check_for_invite, check_scores, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["QUERY_ALLIANCE_MEMBERS", alliance_id, check_for_invite, tag, check_scores]);
};

AllianceCache.query_list = function (callback) {
    AllianceCache.query("QUERY_ALLIANCE_LIST", null, callback);
};
AllianceCache.query_score_leaders = function (addr, include_my_alliance, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["QUERY_ALLIANCE_SCORE_LEADERS", addr, include_my_alliance, tag]);
};
AllianceCache.search_list = function (terms, callback) {
    AllianceCache.query("QUERY_ALLIANCE_LIST", SPHTTP.wrap_string(terms), callback);
};
// wrap client-provided text strings for safe AJAX transmission
AllianceCache.encode_props = function(props) {
    var wire_props = goog.object.clone(props);
    wire_props['ui_name_enc'] = SPHTTP.wrap_string(wire_props['ui_name']); delete wire_props['ui_name'];
    wire_props['chat_tag_enc'] = SPHTTP.wrap_string(wire_props['chat_tag']); delete wire_props['chat_tag'];
    wire_props['ui_descr_enc'] = SPHTTP.wrap_string(wire_props['ui_descr']); delete wire_props['ui_descr'];
    wire_props['chat_motd_enc'] = SPHTTP.wrap_string(wire_props['chat_motd']); delete wire_props['chat_motd'];
    return wire_props;
};
AllianceCache.send_create = function (props, callback) {
    var tag = AllianceCache.install_receiver(callback);
    var wire_props = AllianceCache.encode_props(props);
    wire_props['tag'] = tag;
    send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "ALLIANCE_CREATE", wire_props]);
};
AllianceCache.send_modify = function (props, callback) {
    var tag = AllianceCache.install_receiver(callback);
    var wire_props = AllianceCache.encode_props(props);
    wire_props['tag'] = tag;
    send_to_server.func(["CAST_SPELL", GameObject.VIRTUAL_ID, "ALLIANCE_MODIFY", wire_props]);
};
AllianceCache.send_invite = function (alliance_id, user_id, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["ALLIANCE_INVITE", alliance_id, user_id, tag]);
};
AllianceCache.send_kick = function (alliance_id, user_id, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["ALLIANCE_KICK", alliance_id, user_id, tag]);
};
AllianceCache.send_promote = function (alliance_id, user_id, old_role, new_role, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["ALLIANCE_PROMOTE", alliance_id, user_id, old_role, new_role, tag]);
};
AllianceCache.send_join_request = function(alliance_id, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["ALLIANCE_SEND_JOIN_REQUEST", alliance_id, tag]);
};
AllianceCache.ack_join_request = function(alliance_id, user_id, accept, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func(["ALLIANCE_ACK_JOIN_REQUEST", alliance_id, user_id, accept, tag]);
};

AllianceCache.install_receiver = function(callback) {
    AllianceCache.last_query_tag += 1;
    var tag = 'qai'+AllianceCache.last_query_tag.toString();
    if(callback) { AllianceCache.receivers[tag] = callback; }
    return tag;
};
AllianceCache.query = function(query_msg, arg, callback) {
    var tag = AllianceCache.install_receiver(callback);
    send_to_server.func([query_msg, arg, tag]);
    return tag;
};
AllianceCache.call_receivers = function(tag, result) {
   if(tag in AllianceCache.receivers) {
        var cb = AllianceCache.receivers[tag];
        delete AllianceCache.receivers[tag];
        cb(result);
    }
};


AllianceCache.call_info_callbacks = function(alliance_id) {
    if(alliance_id in AllianceCache.callbacks) {
        var entry = AllianceCache.entries[alliance_id];
        var cblist = AllianceCache.callbacks[alliance_id];
        delete AllianceCache.callbacks[alliance_id];
        for(var i = 0; i < cblist.length; i++) {
            cblist[i](entry);
        }
    }
};

AllianceCache.receive_info_result = function(alliance_ids, tag, result) {
    for(var i = 0; i < alliance_ids.length; i++) {
        if(result[i]) { result[i]['pending'] = 0; }
        AllianceCache.update(alliance_ids[i], result[i]);
    }
    for(var i = 0; i < alliance_ids.length; i++) {
        AllianceCache.call_info_callbacks(alliance_ids[i]);
    }
};

AllianceCache.receive_members = function(alliance_id, tag, result, invite_status) {
    AllianceCache.update(alliance_id, {'members': result, 'invite_status': invite_status});
    AllianceCache.call_receivers(tag, AllianceCache.entries[alliance_id]);
};

AllianceCache.receive_list_result = AllianceCache.call_receivers;
AllianceCache.receive_create_or_modify_result = AllianceCache.call_receivers;
AllianceCache.receive_invite_or_kick_result = AllianceCache.call_receivers;
AllianceCache.receive_send_join_request_result = AllianceCache.call_receivers;
AllianceCache.receive_ack_join_request_result = AllianceCache.call_receivers;
