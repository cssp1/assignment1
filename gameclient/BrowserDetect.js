// http://www.quirksmode.org/js/detect.html
// Copyright (c) 2014 Niels Leenheer
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use, copy,
// modify, merge, publish, distribute, sublicense, and/or sell copies
// of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
// MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
// BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
// ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
// CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
// SP3RDPARTY : BrowserDetect.js (now WhichBrowser) : MIT License

// please keep in sync with gameserver/BrowserDetect.py!

var BrowserDetect = {
        init: function () {
                this.browser = this.searchString(this.dataBrowser) || "An unknown browser";
                this.version = this.searchVersion(navigator.userAgent)
                        || this.searchVersion(navigator.appVersion)
                        || "an unknown version";
                this.OS = this.searchString(this.dataOS) || "an unknown OS";
                this.hardware = this.searchString(this.dataHardware) || "unknown";
        },
        searchString: function (data) {
            var ret = null;
            for (var i=0;i<data.length;i++) {
                var dataString = data[i].string;
                var dataProp = data[i].prop;
                var dataTest = data[i].test;
                this.versionSearchString = data[i].versionSearch || data[i].identity;

                if (dataString) {
                    if (dataString.indexOf(data[i].subString) != -1) {
                        ret = data[i].identity;
                    }
                } else if (dataProp) {
                    ret = data[i].identity;
                }

                if(ret && dataTest && !dataTest()) { ret = null; }

                if(ret) { break; }
            }
            return ret;
        },
        searchVersion: function (dataString) {
                var index = dataString.indexOf(this.versionSearchString);
                if (index == -1) return;
                return parseFloat(dataString.substring(index+this.versionSearchString.length+1));
        },
        dataBrowser: [
                {
                        string: navigator.userAgent,
                        subString: "Chrome",
                        identity: "Chrome"
                },
                {       string: navigator.userAgent,
                        subString: "OmniWeb",
                        versionSearch: "OmniWeb/",
                        identity: "OmniWeb"
                },
                {
                        string: navigator.vendor,
                        subString: "Apple",
                        identity: "Safari",
                        versionSearch: "Version"
                },
                {
                        prop: window.opera,
                        identity: "Opera",
                        versionSearch: "Version"
                },
                {
                        string: navigator.vendor,
                        subString: "iCab",
                        identity: "iCab"
                },
                {
                        string: navigator.vendor,
                        subString: "KDE",
                        identity: "Konqueror"
                },
                {
                        string: navigator.userAgent,
                        subString: "Firefox",
                        identity: "Firefox"
                },
                {
                        string: navigator.vendor,
                        subString: "Camino",
                        identity: "Camino"
                },
                {               // for newer Netscapes (6+)
                        string: navigator.userAgent,
                        subString: "Netscape",
                        identity: "Netscape"
                },
                {
                        string: navigator.userAgent,
                        subString: "MSIE",
                        identity: "Explorer",
                        versionSearch: "MSIE"
                },
                {
                        //"Mozilla/5.0 (Windows NT 6.1. WOW64. Trident/7.0. rv:11.0) like Gecko",
                        string: navigator.userAgent,
                        subString: "Trident/",
                        identity: "Explorer",
                        versionSearch: "rv"
                },
                {
                        string: navigator.userAgent,
                        subString: "Gecko",
                        identity: "Mozilla",
                        versionSearch: "rv"
                },
                {               // for older Netscapes (4-)
                        string: navigator.userAgent,
                        subString: "Mozilla",
                        identity: "Netscape",
                        versionSearch: "Mozilla"
                }
        ],
        dataOS : [
                {
                        string: navigator.platform,
                        subString: "Win",
                        identity: "Windows"
                },
                {
                        string: navigator.platform,
                        subString: "Mac",
                        identity: "Mac"
                },
                {
                           string: navigator.userAgent,
                           subString: "iPhone",
                           identity: "iOS"
                },
                {
                           string: navigator.userAgent,
                           subString: "iPad",
                           identity: "iOS"
                },
                {
                           string: navigator.userAgent,
                           subString: "iPod",
                           identity: "iOS"
                },
                {
                        string: navigator.platform,
                        subString: "Linux",
                        identity: "Linux"
                }
        ],
        dataHardware: [
            {
                string: navigator.userAgent,
                subString: "iPhone",
                identity: "iPhone"
            },
            {
                string: navigator.userAgent,
                subString: "iPad",
                identity: "iPad"
            },
            {
                string: navigator.userAgent,
                subString: "iPod",
                identity: "iPod"
            }
        ]
};
BrowserDetect.init();
