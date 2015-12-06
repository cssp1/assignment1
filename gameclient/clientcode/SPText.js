goog.provide('SPText');

// Copyright (c) 2015 Battlehouse Inc. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('goog.object');

// ABlock = a string of text with associated properties
// ABlock strings can contain spaces but NOT newlines
// ABlocks are passed around in arrays of arrays (lines)
// with an implicit newline between each subarray
// [ [block, block, block], <- line 1
//   [block, block] ] <- line 2 etc.

/** @constructor */
SPText.ABlock = function(str, props) {
    this.kind = 'a';
    this.str = str;
    this.props = props;
};


/** One line of text is an array of ABlocks
    @typedef {!Array.<!SPText.ABlock>} */
SPText.ABlockLine;

/** "Paragraphs" of text is an array of ABlockLines (i.e. an array of array of ABlocks)
    @typedef {!Array.<!SPText.ABlockLine>} */
SPText.ABlockParagraphs;

// convert raw JavaScript string (possibly containing newlines) into
// the array-of-arrays ABlock structure
/** @param {string} str
    @param {Object=} props */
SPText.cstring_to_ablocks = function(str, props) {
    var ret = [];
    var line = [];
    var word = new SPText.ABlock('', props);
    for(var i = 0; i < str.length; i++) {
        var c = str.charAt(i);
        if(c === '\n') {
            // end line
            line.push(word);
            ret.push(line);
            line = [];
            word = new SPText.ABlock('', props);
        } else {
            word.str += c;
        }
    }
    // close final line
    if(word.str.length > 0) {
        line.push(word);
    }
    if(line.length > 0) {
        ret.push(line);
    }
    return ret;
};

/** quote all special characters so that an arbitrary string will not trigger BBCode
    @param {string} str
    @return {string} */
SPText.bbcode_quote = function(str) {
    var r = '';
    for(var i = 0; i < str.length; i++) {
        var c = str.charAt(i);
        if(c === '\\' || c === '[' || c === ']') {
            r += '\\'+c;
        } else {
            r += c;
        }
    }
    return r;
};

SPText.BBCODE_STATES = { LITERAL: 0, CODE: 1, CODE_OPEN: 2, CODE_CLOSE: 3, ESCAPED: 4 };

// strip out all BBCode from the string to get its raw content
SPText.bbcode_strip = function(str) {
    var r = '';
    var state = SPText.BBCODE_STATES.LITERAL;
    for(var i = 0; i < str.length; i++) {
        var c = str.charAt(i);
        if(c === '[' && state != SPText.BBCODE_STATES.ESCAPED) {
            if(state != SPText.BBCODE_STATES.LITERAL) {
                console.log("parse error: double [");
                break;
            }
            state = SPText.BBCODE_STATES.CODE;
        } else if(c === ']' && state != SPText.BBCODE_STATES.ESCAPED) {
            state = SPText.BBCODE_STATES.LITERAL;
        } else if(c === '\\' && state == SPText.BBCODE_STATES.LITERAL) {
            state = SPText.BBCODE_STATES.ESCAPED;
        } else {
          if(state == SPText.BBCODE_STATES.LITERAL) {
              r += c;
          } else if(state == SPText.BBCODE_STATES.ESCAPED) {
              r += c;
              state = SPText.BBCODE_STATES.LITERAL;
          }
        }
    }
    return r;
};

// return a list of space-separated words in a string, but don't split when below toplevel
SPText.bbcode_split_words = function(str) {
    var r = [];
    var word = '';
    var depth = 0;
    var state = SPText.BBCODE_STATES.LITERAL;
    for(var i = 0; i < str.length; i++) {
        var c = str.charAt(i);
        if(c === '[' && state != SPText.BBCODE_STATES.ESCAPED) {
            if(state != SPText.BBCODE_STATES.LITERAL) {
                console.log("parse error: double [");
                break;
            }
            state = SPText.BBCODE_STATES.CODE;
        } else if(c === '/' && state == SPText.BBCODE_STATES.CODE) {
            state = SPText.BBCODE_STATES.CODE_CLOSE;
        } else if(c === ']' && state != SPText.BBCODE_STATES.ESCAPED) {
            if(state == SPText.BBCODE_STATES.CODE_CLOSE) {
                depth -= 1;
            } else {
                depth += 1;
            }
            state = SPText.BBCODE_STATES.LITERAL;
        } else if(c === '\\' && state == SPText.BBCODE_STATES.LITERAL) {
            state = SPText.BBCODE_STATES.ESCAPED;
        } else {
            if(state == SPText.BBCODE_STATES.CODE) {
                state = SPText.BBCODE_STATES.CODE_OPEN;
            } else if(state == SPText.BBCODE_STATES.LITERAL) {
                if(c === ' ' && depth == 0) {
                    if(word) { r.push(word); }
                    word = '';
                    continue; // do not append
                } else {
                    // do append
                }
            } else if(state == SPText.BBCODE_STATES.ESCAPED) {
                state = SPText.BBCODE_STATES.LITERAL;
                // do append
            }
        }
        word += c;
    }
    if(word) { r.push(word); }
    return r;
};

/** @param {string} str
    @param {Object=} props
    @param {Object.<string,function(string)>=} plugins */
SPText.cstring_to_ablocks_bbcode = function(str, props, plugins) {
    if(typeof(props) == 'undefined') { props = {}; }
    var ret = [];
    var line = [];
    var word = new SPText.ABlock('', props);

    var state = SPText.BBCODE_STATES.LITERAL;
    var code = null;
    var prop_stack = [];
    var code_stack = [];
    var code_text_stack = []; // just the literal text inside a [code]...[/code] block
    var word_props = goog.object.clone(props);

    for(var i = 0; i < str.length; i++) {
        var c = str.charAt(i);
        if(c === '\n') {
            if(state != SPText.BBCODE_STATES.LITERAL) {
                console.log("parse error: unexpected newline");
                break;
            }

            // end line
            if(word) { line.push(word); }
            ret.push(line);
            line = [];
            word = new SPText.ABlock('', goog.object.clone(word_props));
        } else if(c === '[' && state != SPText.BBCODE_STATES.ESCAPED) {
            if(state != SPText.BBCODE_STATES.LITERAL) {
                console.log("parse error: double [");
                break;
            }
            state = SPText.BBCODE_STATES.CODE;
            line.push(word);
            word = null;
        } else if(c === '/' && state == SPText.BBCODE_STATES.CODE) {
            state = SPText.BBCODE_STATES.CODE_CLOSE;
            code = '';

        } else if(c === ']' && state != SPText.BBCODE_STATES.ESCAPED) {
            var insert_string = '';

            if(state == SPText.BBCODE_STATES.CODE_OPEN) {
                var root_and_arg = code.split('=');
                var root = root_and_arg[0];
                var arg = (root_and_arg.length > 1 ? root_and_arg[1] : null);

                prop_stack.push(word_props);
                code_stack.push(root);
                code_text_stack.push('');
                word_props = goog.object.clone(word_props);

                if(root == 'color') {
                    word_props.color = arg;
                } else if(root === 'b') {
                    word_props.style = 'bold';
                } else if(root === 'u') {
                    word_props.underline = true;
                } else if(root === 'absolute_time') {
                    // do not descend since there is no closing code for this
                    prop_stack.pop();
                    code_stack.pop();
                    code_text_stack.pop();
                    insert_string = pretty_print_date(parseInt(arg,10)); // XXX imported from main.js
                } else if(root === 'url') {
                    // XXX not sure if this is safe to enable at this low level
                    word_props.onclick = (function (_url) { return function(w, mloc) {
                        var handle = window.open(_url, '_blank');
                        if(handle) { handle.focus(); }
                    }; })(arg);
                } else if(plugins && (root in plugins)) {
                    // note: don't call the handler yet, because we need to wait until text is accumulated to the close of the block
                    // also note we need to add a *reference* to a state object, not a literal, since inner blocks are going to clone this.
                    if('onclick' in plugins[root]) {
                        word_props.onclick_state = {root:root, handler: plugins[root]['onclick'], arg:arg, callback:null};
                        word_props.onclick = null; // remove any existing old-style handler
                   }
                } else {
                    console.log("parse error: unknown BBCode "+code);
                    break;
                }

            } else if(state == SPText.BBCODE_STATES.CODE_CLOSE) {
                var last_root = code_stack.pop();
                code_text_stack.pop(); // we want the one before this

                if(code != last_root) {
                    console.log("parse error: mismatched code blocks");
                    break;
                }
                var cur_code_text = code_text_stack[code_text_stack.length-1];

                if(word_props.onclick_state) {
                    var onc = word_props.onclick_state;
                    onc.callback = onc.handler(onc.arg, cur_code_text);
                }

                word_props = prop_stack.pop();
            } else {
                console.log("parse error: ] without [");
                break;
            }

            state = SPText.BBCODE_STATES.LITERAL;
            word = new SPText.ABlock(insert_string, goog.object.clone(word_props));
        } else if(c === '\\' && state == SPText.BBCODE_STATES.LITERAL) {
            state = SPText.BBCODE_STATES.ESCAPED;
        } else {
            if(state == SPText.BBCODE_STATES.CODE) {
                state = SPText.BBCODE_STATES.CODE_OPEN;
                code = c;
            } else if(state == SPText.BBCODE_STATES.CODE_OPEN || state == SPText.BBCODE_STATES.CODE_CLOSE) {
                code += c;
            } else if(state == SPText.BBCODE_STATES.LITERAL || state == SPText.BBCODE_STATES.ESCAPED) {
                word.str += c;
                // also update all nested code text in the stack
                for(var tx = 0; tx < code_text_stack.length; tx++) { code_text_stack[tx] += c; }
                state = SPText.BBCODE_STATES.LITERAL;
            }
        }
    }

    // close final line
    if(word && word.str.length > 0) {
        line.push(word);
    }
    if(line.length > 0) {
        ret.push(line);
    }
    return ret;
};

// SBlocks are ABlocks annotated with width/height information, used
// for line breaking to fit a given pixel area

/** @constructor */
SPText.SBlock = function(str, props, wh) {
    this.kind = 's';
    this.str = str;
    this.props = props;
    this.wh = wh;
};

// transform a group of ABlocks into SBlocks, adding extra line breaks
// (and even possibly breaking up single ABlocks across lines) where
// necessary to fit all lines within 'width' pixels

SPText.break_lines = function(inlines, width, default_font) {
    var ret = [];
    var line = [];
    var bold_font = null;

    // XXX reset by block if font changes
    var space_width = SPUI.ctx.measureText(' ').width;
    var em_width = SPUI.ctx.measureText('@').width; // @ is wider than M
    var max_chars = Math.max(Math.floor(width / em_width), 1);

    for(var n = 0; n < inlines.length; n++) {
        var inl = inlines[n];
        // forced line break from input
        if(n != 0) {
            ret.push(line);
            line = [];
        }

        // add to line by blocks
        var x = 0;
        for(var b = 0; b < inl.length; b++) {

            var inb = inl[b];
            var has_state = false;

            if(inb.props && inb.props.style && inb.props.style == 'bold') {
                SPUI.ctx.save();
                has_state = true;
                if(!bold_font) {
                    bold_font = SPUI.make_font(default_font.size, default_font.leading, 'bold');
                }
                SPUI.ctx.font = bold_font.str();
            }

            if(inb.kind != 'a') { throw Error('input is not ABlocks'); }
            var words = inb.str.split(' ');
            var block = new SPText.SBlock('', inb.props, [0,0]);
            for(var i = 0; i < words.length; i++) {
                if(i > 999 || words.length > 999) { console.log('infinite loop in break_lines!'); break; }
                var meas = SPUI.ctx.measureText(words[i]);

                var word_size = [meas.width, 0]; // no need for height info
                if(x + word_size[0] >= width) {
                    // word too big to fit, break line here
                    if(block.str.length > 0) {
                        line.push(block);
                    }
                    if(line.length > 0) {
                        ret.push(line);
                    }
                    line = [];
                    block = new SPText.SBlock('', inb.props, [0,0]);
                    x = 0;
                } else if(x != 0 && i != 0) {
                    // insert space
                    block.str += ' ';
                    block.wh[0] += space_width;
                    x += space_width;
                }

                if(x == 0 && word_size[0] >= width && words[i].length > max_chars) {
                    // word too long even on a line by itself, so break it manually
                    var first = words[i].slice(0,max_chars);
                    var rest = words[i].slice(max_chars);
                    block.str += first;
                    block.wh[0] += SPUI.ctx.measureText(first).width;
                    line.push(block);
                    ret.push(line);
                    line = [];
                    block = new SPText.SBlock('', inb.props, [0,0]);
                    x = 0;
                    // stick 'rest' back onto the input
                    words.splice(i+1, 0, rest);
                } else {
                    // normal word
                    block.str += words[i];
                    block.wh[0] += word_size[0];
                    x += word_size[0];
                }
            }
            // close out last block
            if(block.str.length > 0) {
                line.push(block);
            }

            if(has_state) {
                SPUI.ctx.restore();
            }
        }
    }
    // close out last line
    if(line.length > 0) {
        ret.push(line);
    }

    return ret;
};

// RBlocks are "renderable"
// they are like SBlocks, but also have xy coordinates for each block

/** @constructor */
SPText.RBlock = function(str, props, wh, xy) {
    this.kind = 'r';
    this.str = str;
    this.props = props;
    this.wh = wh;
    this.xy = xy;
};

// transform a group of SBlocks into RBlocks, assigning the xy
// positions according to desired justification.

SPText.layout_text = function(sblocklines, wh, hjustify, vjustify, deffont, offset) {

    // pass #1: accumulate line sizes
    var line_sizes = [];
    var total_h = 0;
    for(var n = 0; n < sblocklines.length; n++) {
        var sbline = sblocklines[n];
        var linewidth = 0;
        for(var b = 0; b < sbline.length; b++) {
            var sb = sbline[b];
            if(sb.kind != 's') { throw Error('input is not SBlocks'); }
            linewidth += sb.wh[0];
        }
        line_sizes.push([linewidth, deffont.leading]);
        total_h += deffont.leading;
    }

    var y = 0;
    if(vjustify === 'top') {
        y = deffont.size;
    } else if(vjustify === 'center') {
        y = Math.floor((wh[1]-total_h)/2) + deffont.size;
    } else if(vjustify === 'bottom') {
        y = wh[1]-total_h + deffont.size;
    }

    // pass #2: assign xy positions
    var ret = [];
    for(var n = 0; n < sblocklines.length; n++) {
        var sbline = sblocklines[n];
        var linewidth = line_sizes[n][0];
        var line = [];
        var x = 0;
        if(hjustify === 'center') {
            x = Math.floor((wh[0] - linewidth)/2);
        } else if(hjustify === 'left') {
            x = 0;
        } else if(hjustify === 'right') {
            x = wh[0] - linewidth;
        }

        for(var b = 0; b < sbline.length; b++) {
            var sb = sbline[b];
            line.push(new SPText.RBlock(sb.str, sb.props,
                                        [sb.wh[0], deffont.leading],
                                        [x+offset[0],y+offset[1]]));
            x += sb.wh[0];
        }
        ret.push(line);
        y += deffont.leading;
    }
    return ret;
};

/** @param {Array.<Array.<SPText.RBlock>>} rblocklines
    @param {Array.<number>} offset coordinates
    @param {SPUI.Font} default_font
    @param {boolean=} no_color */
SPText.render_text = function(rblocklines, offset, default_font, no_color) {
    var bold_font = null;
    for(var n = 0; n < rblocklines.length; n++) {
        var rbline = rblocklines[n];
        for(var b = 0; b < rbline.length; b++) {
            var rb = rbline[b];
            if(rb.kind != 'r') { throw Error('input is not RBlocks'); }
            if(rb.props) {
                SPUI.ctx.save();
                if(rb.props && rb.props.color && !no_color) {
                    SPUI.ctx.fillStyle = SPUI.ctx.strokeStyle = rb.props.color;
                }
                if(rb.props && rb.props.alpha !== undefined) {
                    if(rb.props.alpha <= 0) {
                        SPUI.ctx.restore();
                        continue; // fully transparent
                    } else if(rb.props.alpha < 1) {
                        SPUI.ctx.globalAlpha *= rb.props.alpha;
                    }
                }
                if(rb.props && rb.props.style && rb.props.style == 'bold') {
                    if(!bold_font) {
                        bold_font = SPUI.make_font(default_font.size, default_font.leading, 'bold');
                    }
                    SPUI.ctx.font = bold_font.str();
                }
            }
            //if(n == rblocklines.length-1) { console.log(rb.str); }
            SPUI.ctx.fillText(rb.str,
                              rb.xy[0]+offset[0], rb.xy[1]+offset[1]);

            // draw underline
            if(rb.props && rb.props.underline) {
                var min_underline_width = 1; // 2 makes for a very strong underline, 1 is a less intense underline
                SPUI.ctx.lineWidth = Math.max(min_underline_width, Math.floor(default_font.size/16) + 1);
                // how far to sink the underline beneath the baseline of the text
                var sink_height = Math.floor(rb.wh[1]/10)+1;
                SPUI.ctx.beginPath();
                SPUI.ctx.moveTo(rb.xy[0]+offset[0], rb.xy[1]+offset[1]+sink_height);
                SPUI.ctx.lineTo(rb.xy[0]+rb.wh[0]+offset[0], rb.xy[1]+offset[1]+sink_height);
                SPUI.ctx.stroke();
            }

            if(rb.props) {
                SPUI.ctx.restore();
            }
        }
    }
};

SPText.detect_hit = function(rblocklines, hitxy) {
    for(var n = 0; n < rblocklines.length; n++) {
        var rbline = rblocklines[n];
        for(var b = 0; b < rbline.length; b++) {
            var rb = rbline[b];
            if(hitxy[0] >= rb.xy[0] && hitxy[0] < (rb.xy[0]+rb.wh[0]) &&
               hitxy[1] >= rb.xy[1] && hitxy[1] < (rb.xy[1]+rb.wh[1])) {
                return rb.props;
            }
        }
    }
    return null;
};
