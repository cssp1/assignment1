#!/usr/bin/env python

# Copyright (c) 2020 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import xml.etree.ElementTree as ET
from signxml import XMLVerifier
import time

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
            purchase['time'] = get_purchase_time(product_receipt.get('PurchaseDate'))
            price = product_receipt.get('PurchasePrice')
            currency = get_currency(price)
            purchase['price'] = price.replace(currency,'')
            purchase['currency'] = currency
            result.append(purchase)
    except:
        return []
    return result

def get_currency(price):
    for currency in ("NOK","SEK","GBP","EUR","QAR","BRL","AED","DKK","USD","AUD","NZD","CAD","ZAR","ISK","IDR"):
        if currency in price: return currency
    # maybe log any currency not found incidents?
    return 'USD'

def get_purchase_time(purchase_time):
    try:
        # MS receipt timestamps are in the format '2021-01-01T18:34:35.231Z'
        int_time = int(time.mktime(time.strptime(purchase_time, '%Y-%m-%dT%H:%M:%S.%fZ')))
    except:
        # maybe log any errors somehow?
        int_time = -1
    return int_time
