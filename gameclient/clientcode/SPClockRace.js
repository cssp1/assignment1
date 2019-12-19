goog.provide('SPClockRace');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet

    Launch timer races to compare server and client clock speeds.
*/

// global tag counter
SPClockRace.last_tag = 9876;

// tag for in-flight request. Stringified number.
SPClockRace.current_tag = null;

// for throttling purposes, prevent launching new races until this time
SPClockRace.hold_until = -1;

SPClockRace.launch = function() {
    if(SPClockRace.current_tag) {
        return; // still in progress
    }

    var interval_range = gamedata['client']['counter_query_interval_range'];
    if(!interval_range) {
        return; // not enabled
    }

    // timer interval, in seconds
    var interval = interval_range[0] + Math.random() * (interval_range[1] - interval_range[0]);

    var start_time = (new Date()).getTime()/1000.0;
    if(start_time < SPClockRace.hold_until) {
        return; // held off
    }

    if(Math.random() >= gamedata['client']['counter_query_interval_ratio']) {
        // do not launch this query, just pause for the interval
        SPClockRace.hold_until = start_time + interval;
        return;
    }

    SPClockRace.current_tag = (SPClockRace.last_tag++).toString();

    send_to_server.func(["WORLD_COUNTER_UPDATE", SPClockRace.current_tag]);
    flush_message_queue(true);

    setTimeout((function (_start_time, _interval) { return function() {
        var client_elapsed_time = (new Date()).getTime()/1000.0 - _start_time;
        send_to_server.func(["WORLD_COUNTER_QUERY", SPClockRace.current_tag, client_elapsed_time, _interval]);
        flush_message_queue(true);
        SPClockRace.current_tag = null;
    }; })(start_time, interval), interval * 1000.0);
};
