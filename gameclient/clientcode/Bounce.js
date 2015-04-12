goog.provide('Bounce');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Utility for animating "bouncy" icons
*/

/** @type {!Array.<{height:number, duration:number}>} */
Bounce.parabolas = [
    {height:1.000, duration:0.6},
    {height:0.500, duration:0.5},
    {height:0.250, duration:0.4},
    {height:0.125, duration:0.2},
    {height:0.000, duration:1.5}
];

/** @param {number} t
    @return {number} */
Bounce.get = function(t) {
    /** @type {number} */
    var total_duration = 0;
    goog.array.forEach(Bounce.parabolas, function(p) {
        total_duration += p.duration;
    });
    t = t % total_duration;
    for(var i = 0; i < Bounce.parabolas.length; i++) {
        var p = Bounce.parabolas[i];
        if(t >= p.duration) {
            t -= p.duration;
            continue;
        }
        t = 2*t/p.duration;
        if(p.height > 0) {
            return p.height * (1 - (t-1)*(t-1));
        }
        return 0;
    }
    return 0;
};

