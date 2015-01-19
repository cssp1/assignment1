goog.provide('PlayerCache');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('goog.array');

// client-side player info cache
// this is a central respository for things we know about other players

// imports from main.js: send_to_server

var PlayerCache = {
    config: null,
    entries: {}, // mapping from user_id -> {'pending':1} or cache entry (which may be null)
    batch: [], // current batch to query, to be launched at next frame draw
    inflight: {}, // mapping from tag -> list of user_ids being queried
    last_query_tag: 0,
    last_query_time: 0
};

PlayerCache.init = function(config) {
    PlayerCache.config = config;
};

PlayerCache.clear_all_except = function(save_id) {
    var save_entry = null;
    if(save_id && save_id in PlayerCache.entries) { save_entry = PlayerCache.entries[save_id]; }
    PlayerCache.entries = {};
    if(save_entry) { PlayerCache.entries[save_id] = save_entry; }
};

PlayerCache.receive_result = function(tag, result) {
    if(tag in PlayerCache.inflight) {
        var myquery = PlayerCache.inflight[tag];
        delete PlayerCache.inflight[tag];
        for(var i = 0; i < myquery.length; i++) {
            var user_id = myquery[i];
            if(result[i] && !('user_id' in result[i])) { result[i]['user_id'] = user_id; }
            PlayerCache.entries[user_id] = result[i]; // gets rid of the 'pending' status
        }
    }
};
PlayerCache.update = function(user_id, data) {
    if(user_id in PlayerCache.entries) {
        for(var key in data) {
            PlayerCache.entries[user_id][key] = data[key];
        }
    } else {
        if(data && !('user_id' in data)) { data['user_id'] = user_id; }
        PlayerCache.entries[user_id] = data;
    }
};
PlayerCache.update_batch = function(datalist) {
    if(!datalist) { return; }
    for(var i = 0; i < datalist.length; i++) {
        if(datalist[i] && datalist[i]['user_id']) {
            PlayerCache.update(datalist[i]['user_id'], datalist[i]);
        }
    }
};
PlayerCache.update_lock_state = function(user_id, state) {
    if(!(user_id in PlayerCache.entries)) {
        PlayerCache.entries[user_id] = {};
    }
    PlayerCache.entries[user_id]['LOCK_STATE'] = state;
};
PlayerCache.update_alliance_membership = function(user_id, alliance_id) {
    if(!(user_id in PlayerCache.entries)) {
        PlayerCache.entries[user_id] = {};
    }
    PlayerCache.entries[user_id]['alliance_id'] = alliance_id;
};
PlayerCache.query_sync = function(user_id) {
    if(is_ai_user_id_range(user_id)) { return PlayerCache.get_client_ai_entry(user_id); }
    if(!(user_id in PlayerCache.entries)) { return null; }
    var entry = PlayerCache.entries[user_id];
    if((entry === null) || !entry['pending']) {
        return entry;
    }
    return null;
};
PlayerCache.query_sync_fetch = function(user_id) {
    if(!user_id) { throw Error('bad user_id in query_sync_fetch'); }
    if(is_ai_user_id_range(user_id)) { return PlayerCache.get_client_ai_entry(user_id); }

    var entry;
    if(user_id in PlayerCache.entries) {
        entry = PlayerCache.entries[user_id];
        // note: check for presence of user_id since it might be a dummy entry with just a LOCK_STATE or alliance_id
        if(entry === null || (!entry['pending'] && entry['user_id'])) {
            // data is here now, return immediately
            return entry;
        }
    } else {
        entry = {'pending':0};
        PlayerCache.entries[user_id] = entry;
    }
    if(!entry['pending']) {
        entry['pending'] = 1;
        PlayerCache.batch.push(user_id);
    }
    return null;
};

PlayerCache.force_fetch = function(user_id) {
    if(!goog.array.contains(PlayerCache.batch, user_id)) {
        PlayerCache.batch.push(user_id);
    }
};

PlayerCache.launch_batch_queries = function(time, force) {
    if(PlayerCache.batch.length > 0 && (force || (time >= PlayerCache.last_query_time + PlayerCache.config['query_interval']))) {
        PlayerCache.last_query_tag += 1;
        PlayerCache.last_query_time = time;
        var tag = 'qpc'+PlayerCache.last_query_tag.toString();
        var this_batch = PlayerCache.batch.splice(0, Math.min(PlayerCache.batch.length, PlayerCache.config['query_max']));
        PlayerCache.inflight[tag] = this_batch;
        send_to_server.func(["QUERY_PLAYER_CACHE", this_batch, tag]);
    }
};

// get a client-side PlayerCache entry representing what we know about an AI
PlayerCache._get_client_ai_entry = function(user_id) {
    if(user_id.toString() in gamedata['ai_bases_client']['bases']) {
        var base = gamedata['ai_bases_client']['bases'][user_id.toString()];
        return {'user_id': user_id,
                'player_level': base['resources']['player_level'],
                'ui_name': base['ui_name'],
                'social_id': 'ai'};
    }
    return null; // no fallback
};
PlayerCache.get_client_ai_entry = function(user_id) {
    var ret = PlayerCache._get_client_ai_entry(user_id);
    if(!ret) { throw Error('PlayerCache.get_ai_entry: '+user_id.toString()+' not found'); }
    return ret;
};

// operates on an individual entry
PlayerCache.get_is_ai = function(info) {
    if(info['social_id'] == 'ai') { return true; }
    return false;
};

// operates on an individual entry
PlayerCache._get_ui_name = function(info) {
    if('ui_name' in info) {
        return info['ui_name'];
    } else if('facebook_first_name' in info) { // legacy cache entries
        return info['facebook_first_name'];
    } else if('facebook_name' in info) { // legacy cache entries
        var ret = info['facebook_name'];
        if(ret.indexOf(' ') > 0) {
            ret = ret.split(' ')[0];
        }
        return ret;
    } else {
        return null;
    }
};
// this has a fallback for missing info, the _ version does not
PlayerCache.get_ui_name = function(info) {
    return PlayerCache._get_ui_name(info) || 'Unknown(pc)';
};
