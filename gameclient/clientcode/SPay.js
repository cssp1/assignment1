goog.provide('SPay');

// Copyright (c) 2015 SpinPunch Studios. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

/** @fileoverview
    Some common interfaces for payments backends.

    @suppress {reportUnknownTypes} XXX we are not typesafe yet
*/

goog.require('SPFB');
goog.require('SPKongregate');

// global namespace
SPay = {
    /** @type {string|null} */
    api: null
};

/** @param {string} api - "fbpayments", "kgcredits", or "xsolla" */
SPay.set_api = function(api) {
    if(!goog.array.contains(['fbpayments', 'kgcredits', 'xsolla'], api)) {
        throw Error('invalid SPay API '+api);
    }
    SPay.api = api;
};

// NEW FB Payments order flow
SPay.place_order_fbpayments = function (product_url, quantity, request_id, callback, test_currency) {
    var props = {'method': 'pay', 'action': 'purchaseitem',
                 'product': product_url, 'quantity': quantity,
                 'request_id': request_id};
    if(test_currency) { props['test_currency'] = test_currency; }
    SPFB.ui(props, callback);
};

// OLD FB Credits order flow
SPay.place_order_fbcredits = function (order_info, callback, use_local_currency) {

    // if use_oscif is true, this tells Facebook to use the simplified order pop-up
    // note: disabled for now because it causes some kind of cross-site scripting error

    var use_oscif = use_local_currency;

    SPFB.ui({'method': 'pay', 'order_info': order_info, 'purchase_type': 'item',
             'dev_purchase_params': {'oscif':use_oscif}}, callback);
};

SPay.place_order_kgcredits = function (order_info, callback) {
    SPKongregate.purchaseItemsRemote(order_info, callback);
};

SPay.buy_more_credits = function(callback) {
    SPFB.ui({'method':'pay', 'credits_purchase':true}, callback);
};

SPay.redeem_fb_gift_card = function(callback) {
    SPFB.ui({'method':'pay', 'action':'redeem'}, callback);
};

SPay.offer_payer_promo = function(currency_url, callback) {
    SPFB.ui({'method':'fbpromotion', 'display': 'popup',
             //'package_name': 'zero_promo',
             'quantity': 300,
             'product': currency_url}, callback);
};

// Xsolla API - see http://developers.xsolla.com/api.html#virtual-currency

SPay.xsolla_available = function() {
    if(!spin_xsolla_sdk_loaded /* from XsollaSDK.js */ ||
       typeof XPayStationWidget === 'undefined') { return false; }
    return true;
};

// TrialPay API - see http://help.trialpay.com/facebook/offer-wall/

SPay.trialpay_available = function() {
    // client also needs to check frame_platform == 'fb' and facebook_third_party_id exists
    if(typeof TRIALPAY === 'undefined') { return false; }
    return true;
};

/** Annoying global callback needed for TrialPay API
    @type {function(string,Object=)|null} */
SPay.trialpay_user_cb = null;

SPay.trialpay_on_open = function() { SPay.trialpay_user_cb('open'); };
SPay.trialpay_on_close = function() { SPay.trialpay_user_cb('close'); };
SPay.trialpay_on_transact = function(result) {
    if(result['completions'] > 0 && result['vc_amount'] > 0) {
        SPay.trialpay_user_cb('complete', result);
    }
};

/** @param {string} app_id
    @param {string} vendor_id
    @param {string} callback_url
    @param {string} currency_url
    @param {string} third_party_id
    @param {string} order_info
    @param {function(string,Object=)} user_cb */
SPay.trialpay_invoke = function(app_id, vendor_id, callback_url, currency_url, third_party_id, order_info, user_cb) {
    if(SPay.trialpay_user_cb && SPay.trialpay_user_cb !== user_cb) {
        throw Error('user_cb already set to something else');
    }
    SPay.trialpay_user_cb = user_cb;

    TRIALPAY.fb.show_overlay(app_id,
                             'fbdirect',
                             {'tp_vendor_id': vendor_id,
                              'callback_url': callback_url,
                              'currency_url': currency_url,
                              'sid': third_party_id,
                              'order_info': order_info,
                              // Terrible API - it requires the *name* of a callback function!
                              'onOpen': 'SPay.trialpay_on_open',
                              'onTransact': 'SPay.trialpay_on_transact',
                              'onClose': 'SPay.trialpay_on_close'
                             });
};

// make sure compiler does not mangle these
goog.exportSymbol('SPay.trialpay_on_open', SPay.trialpay_on_open);
goog.exportSymbol('SPay.trialpay_on_transact', SPay.trialpay_on_transact);
goog.exportSymbol('SPay.trialpay_on_close', SPay.trialpay_on_close);
