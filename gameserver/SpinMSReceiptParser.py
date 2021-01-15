#!/usr/bin/env python

# Copyright (c) 2020 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import xml.etree.ElementTree as ET
from signxml import XMLVerifier
import time
from twisted.internet.defer import inlineCallbacks, returnValue

@inlineCallbacks
def validate_receipt(receipt, gamesite, server_time):
    ms_cert_url = "https://lic.apps.microsoft.com/licensing/certificateserver/?cid="
    root = ET.fromstring(receipt)
    certificate_id = root.get('CertificateId')
    ms_cert_url += certificate_id
    cert = yield gamesite.AsyncHTTP_Battlehouse.queue_request_deferred(server_time, ms_cert_url)
    result = []
    try:
        XMLVerifier().verify(receipt, x509_cert=cert.text)
        for product_receipt in root.findall('{http://schemas.microsoft.com/windows/2012/store/receipt}ProductReceipt'):
            purchase = {'spellname': product_receipt.get('ProductId')), 'purchase_id': product_receipt.get('Id')}
            purchase['time'] = get_purchase_time(product_receipt.get('PurchaseDate'), gamesite, server_time)
            price = product_receipt.get('PurchasePrice')
            currency = get_currency(price, gamesite, server_time)
            purchase['price'] = price.replace(currency,'')
            purchase['currency'] = currency
            result.append(purchase)
    except:
        gamesite.exception_log.event(server_time, 'Exception Microsoft receipt: %s could not be verified with certificate' % (receipt))
        return []
    returnValue(result)

def get_currency(price, gamesite, server_time):
    for currency in ("NOK","SEK","GBP","EUR","QAR","BRL","AED","DKK","USD","AUD","NZD","CAD","ZAR","ISK","IDR"):
        if currency in price: return currency
    gamesite.exception_log.event(server_time, 'Exception Microsoft receipt currency: %s could not be identified as a valid currency, defaulting to USD' % (price))
    return 'USD'

def get_purchase_time(purchase_time, gamesite, server_time):
    try:
        # MS receipt timestamps are in the format '2021-01-01T18:34:35.231Z'
        int_time = int(time.mktime(time.strptime(purchase_time, '%Y-%m-%dT%H:%M:%S.%fZ')))
    except:
        int_time = server_time
        gamesite.exception_log.event(server_time, 'Exception Microsoft receipt purchase time %s could not be decoded, defaulting to server time' % purchase_time)
    return int_time
