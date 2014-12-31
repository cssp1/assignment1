goog.provide('SPay');

// Copyright (c) 2014 SpinPunch. All rights reserved.
// Use of this source code is governed by an MIT-style license that can be
// found in the LICENSE file.

goog.require('SPFB');
goog.require('SPKongregate');

// Note: assumes Facebook client-side JavaScript SDK has been included
// see https://developers.facebook.com/docs/creditsapi/

// global namespace
SPay = {
    api: null
};

SPay.set_api = function(api) {
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
    return SPKongregate.purchaseItemsRemote(order_info, callback);
};

SPay.buy_more_credits = function(callback) {
    SPFB.ui({'method':'pay', 'credits_purchase':true}, callback);
};

SPay.redeem_fb_gift_card = function(callback) {
    SPFB.ui({'method':'pay', 'action':'redeem'}, callback);
};

SPay.earn_credits_with_offers = function(callback) {
    SPFB.ui({'method':'pay', 'action':'earn_credits'}, callback);
};

SPay.offer_payer_promo = function(currency_url, callback) {
    SPFB.ui({'method':'fbpromotion', 'display': 'popup',
             //'package_name': 'zero_promo',
             'quantity': 300,
             'product': currency_url}, callback);
};
