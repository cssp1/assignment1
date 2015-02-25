goog.provide('ShakeSynth');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

// Synthesize shaky animation channel based on real power spectrum
// based on Dan's animation work

/** @const */
ShakeSynth = {
    SAMPLES: 256,
    AXES: 3,
    DATASCALE: 24.0/2589.0
};

/** @constructor
    @struct
    @param {number} seed */
ShakeSynth.Shake = function(seed) {
    this.seed = seed;
    this.speed = 5.3;
    this.offset = 0.0;
    this.start_freq = 4;
    this.end_freq = 15;

    // XXX pretend we're seeding the random number generator here
    this.phases = [];
    for(var a = 0; a < ShakeSynth.AXES; a++) {
        this.phases.push([]);
        for(var i = 0; i < ShakeSynth.SAMPLES; i++) {
            this.phases[a].push(2*Math.PI*Math.random());
        }
    }
};

/** @param {number} t
    @return {Array.<number>} */
ShakeSynth.Shake.prototype.evaluate = function(t) {
    var start = Math.min(Math.max(this.start_freq, 0), ShakeSynth.SAMPLES-1);
    var end = Math.min(Math.max(this.end_freq, 0), ShakeSynth.SAMPLES-1);
    var x = (this.speed*t + this.offset) * ShakeSynth.DATASCALE;
    var ret = [];
    for(var a = 0; a < ShakeSynth.AXES; a++) {
        ret.push(0.0);
        for(var j = start; j < end; j++) {
            ret[a] += ShakeSynth.noise_spectrum[j] * Math.cos(x * 2.0 * Math.PI * j + this.phases[a][j]);
        }
    }
    return ret;
};

ShakeSynth.noise_spectrum = [
0.000000e+00,
4.857771e-01,
1.192326e-01,
2.063079e-02,
7.536398e-02,
6.742394e-02,
2.210798e-02,
3.663491e-02,
3.475564e-02,
3.180257e-02,
2.153413e-02,
2.116205e-02,
1.044586e-02,
2.012097e-02,
1.845829e-02,
7.577885e-03,
4.804327e-03,
1.467319e-02,
4.911850e-03,
1.450011e-02,
1.128158e-02,
6.088526e-03,
1.303416e-02,
1.040846e-02,
4.455414e-03,
9.056887e-03,
8.349558e-03,
9.011875e-03,
8.940478e-03,
1.371349e-02,
1.221341e-02,
6.974461e-03,
5.284104e-03,
5.424535e-03,
6.165653e-03,
9.564439e-03,
1.983768e-03,
5.300896e-03,
8.599972e-03,
8.101000e-03,
6.236279e-03,
5.708745e-03,
7.586879e-03,
4.761028e-03,
6.072877e-03,
7.292682e-03,
4.564680e-03,
3.874877e-03,
5.842919e-03,
2.422631e-03,
5.520637e-03,
6.142305e-03,
2.384664e-03,
5.480351e-03,
5.840554e-03,
2.635990e-03,
2.748401e-03,
3.134883e-03,
4.048508e-03,
4.618548e-03,
2.892914e-03,
3.577765e-03,
2.589600e-03,
3.216274e-03,
3.948973e-03,
2.758984e-03,
3.674112e-03,
4.064016e-03,
1.472141e-03,
3.595053e-03,
3.398805e-03,
3.096556e-03,
3.043179e-03,
3.999744e-03,
3.157283e-03,
1.245069e-03,
3.794767e-03,
3.040089e-03,
1.624037e-03,
3.956031e-03,
2.478528e-03,
2.640672e-03,
3.453304e-03,
2.167517e-03,
2.775913e-03,
2.204785e-03,
2.668207e-03,
1.904576e-03,
2.187848e-03,
2.473432e-03,
1.543914e-03,
3.351570e-03,
3.004750e-03,
1.799499e-03,
2.878944e-03,
1.818795e-03,
1.876510e-03,
2.265754e-03,
1.912959e-03,
2.777052e-03,
2.710864e-03,
1.531133e-03,
2.161361e-03,
1.848998e-03,
1.807203e-03,
2.237049e-03,
1.940713e-03,
2.148969e-03,
1.453176e-03,
2.092739e-03,
1.915965e-03,
8.312202e-04,
2.670635e-03,
1.887779e-03,
1.600663e-03,
2.286525e-03,
1.459540e-03,
1.751599e-03,
1.743790e-03,
1.528990e-03,
1.547673e-03,
1.880120e-03,
2.077607e-03,
1.315018e-03,
2.148167e-03,
1.830001e-03,
1.069652e-03,
1.889395e-03,
1.225380e-03,
1.531886e-03,
1.778273e-03,
1.510992e-03,
1.455926e-03,
1.585058e-03,
1.201677e-03,
1.400051e-03,
1.828464e-03,
1.650022e-03,
1.421852e-03,
1.805910e-03,
1.438145e-03,
1.047846e-03,
1.424072e-03,
1.461633e-03,
1.554613e-03,
2.000690e-03,
1.395813e-03,
1.176613e-03,
1.277115e-03,
9.799595e-04,
1.369170e-03,
1.302254e-03,
1.660997e-03,
1.520645e-03,
1.147736e-03,
1.260087e-03,
8.800502e-04,
1.575257e-03,
1.294629e-03,
1.347516e-03,
1.597189e-03,
1.019267e-03,
1.387356e-03,
1.267230e-03,
1.149710e-03,
1.659276e-03,
1.289653e-03,
1.365696e-03,
1.264799e-03,
1.008576e-03,
1.157244e-03,
1.252520e-03,
1.236544e-03,
1.493954e-03,
1.282524e-03,
1.144934e-03,
1.343774e-03,
1.010977e-03,
1.243205e-03,
1.203319e-03,
1.259489e-03,
1.148618e-03,
9.301934e-04,
1.370944e-03,
9.688650e-04,
1.144842e-03,
1.575592e-03,
9.100067e-04,
1.301835e-03,
1.141539e-03,
8.569397e-04,
1.093474e-03,
1.092708e-03,
1.226828e-03,
1.121282e-03,
1.231123e-03,
1.084664e-03,
9.279804e-04,
1.016759e-03,
8.807044e-04,
9.995061e-04,
1.124430e-03,
1.178985e-03,
9.633438e-04,
1.108365e-03,
9.542361e-04,
9.351199e-04,
1.167549e-03,
9.886885e-04,
1.201048e-03,
9.070367e-04,
9.087832e-04,
9.731806e-04,
7.113664e-04,
1.218165e-03,
1.044474e-03,
1.109015e-03,
1.171665e-03,
7.999631e-04,
9.372421e-04,
9.310076e-04,
9.394074e-04,
9.992747e-04,
1.013874e-03,
1.160483e-03,
9.623752e-04,
9.730948e-04,
9.537398e-04,
9.912501e-04,
9.158297e-04,
1.102400e-03,
8.358480e-04,
8.596464e-04,
9.616554e-04,
6.032882e-04,
1.092593e-03,
1.006738e-03,
9.166623e-04,
1.182467e-03,
7.949431e-04,
9.474597e-04,
7.812602e-04,
8.720920e-04,
9.363063e-04,
8.001832e-04,
1.010424e-03,
7.107108e-04,
8.733074e-04,
9.005857e-04,
8.424795e-04,
9.758927e-04,
7.849667e-04,
8.628846e-04,
8.609101e-04,
8.108317e-04,
7.945030e-04
];
