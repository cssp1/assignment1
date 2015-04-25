goog.provide('FBUploadPhoto');

// Copyright (c) 2015 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Facebook Photo upload
    !!! DOES NOT WORK ON IE9 DUE TO Uint8Array, Blob, and FormData !!!
*/

goog.require('SPFB');
goog.require('goog.net.XhrIo');
goog.require('goog.crypt.base64');
goog.require('goog.events');

/** Check for browser support
    @return {boolean} */
FBUploadPhoto.supported = function() {
    return (typeof('Blob') !== 'undefined') &&
        (typeof('FormData') !== 'undefined') &&
        (typeof('Uint8Array') !== 'undefined');
};

/** Convert base64/URLEncoded data component to a Blob
    @param {string} dataURI
    @return {!Blob} */
FBUploadPhoto.dataURItoBlob = function(dataURI) {
    /** @type {string} */
    var byteString;

    if(dataURI.split(',')[0].indexOf('base64') >= 0) {
        byteString = goog.crypt.base64.decodeString(dataURI.split(',')[1]);
    } else {
        byteString = unescape(dataURI.split(',')[1]);
    }

    // separate out the mime component
    var mimeString = dataURI.split(',')[0].split(':')[1].split(';')[0];

    // write the bytes of the string to a typed array
    var ia = new Uint8Array(byteString.length);
    for(var i = 0; i < byteString.length; i++) {
        ia[i] = byteString.charCodeAt(i);
    }
    return new Blob([ia], {'type':mimeString});
};

/**
 Example: upload(canvas.toDataURL('image/jpeg'), 'SCREENSHOT.jpg', 'My Caption', true, 'player_statistics', null)
 @param {string} dataURI canvas.toDataURL('image/jpeg')
 @param {string} ui_filename 'SCREENSHOT.jpg'
 @param {boolean} post_story
 @param {string} reason
 @param {string|null} caption
 @param {function(boolean)|null} callback
 @suppress {reportUnknownTypes,checkTypes} - Closure doesn't deal with the nested callbacks well
 Also, Closure's exten definition for append() is missing the third argument
*/
FBUploadPhoto.upload = function(dataURI, ui_filename, caption, post_story, reason, callback) {
    var auth_token = spin_facebook_oauth_token;
    var url = SPFB.versioned_graph_endpoint('photos', spin_facebook_user+'/photos?access_token='+auth_token);
    var img_blob = FBUploadPhoto.dataURItoBlob(dataURI);

    var fd = new FormData();

    fd.append('file', img_blob, ui_filename);

    if(!post_story) {
        fd.append('no_story', 'true');
    }
    if(caption) {
        fd.append('caption', caption);
    }

    metric_event('7272_photo_upload_attempted', {'facebook_id':spin_facebook_user, 'reason':reason});

    goog.net.XhrIo.send(url,
                        (function (_cb) { return function(event) { FBUploadPhoto.on_response(event, _cb); }; })(callback),
                        'POST', fd);
};

/** @param {goog.events.Event} event
    @param {function(boolean)|null} callback */
FBUploadPhoto.on_response = function(event, callback) {
    var success = false;
    var io = /** @type {goog.net.XhrIo} */ (event.target);
    if(!io.isSuccess()) {
        var code = io.getLastErrorCode();
        var text = io.getResponseText();
        console.log('FBUploadPhoto error code '+code+' text '+text);
        metric_event('7274_photo_upload_failed', {'facebook_id':spin_facebook_user, 'code':code, 'text':text});
    } else {
        var data = JSON.parse(io.getResponseText());
        console.log(data);
        var props = {'facebook_id':spin_facebook_user, 'photo_id':data['id']};
        if(data['post_id']) { props['post_id'] = data['post_id']; }
        metric_event('7273_photo_upload_completed', props);
        success = true;
    }
    callback(success);
};
