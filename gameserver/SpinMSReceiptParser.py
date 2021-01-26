#!/usr/bin/env python

# Copyright (c) 2020 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import xml.etree.ElementTree as ET
from signxml import XMLVerifier
import time

# Return the URL from which to get the certificate to validate an MS store receipt XML document
def validate_receipt_request_url(receipt):
    ms_cert_url = "https://lic.apps.microsoft.com/licensing/certificateserver/?cid="
    root = ET.fromstring(receipt)
    certificate_id = root.get('CertificateId')
    ms_cert_url += certificate_id
    return ms_cert_url

# After retrieving the certificate, parse and validate the response.
# Return a list of valid receipts found in the response. Throws exception on error.
def validate_receipt_response(receipt, cert):
    result = []
    root = XMLVerifier().verify(receipt, x509_cert=cert).signed_xml
    for product_receipt in root.findall('{http://schemas.microsoft.com/windows/2012/store/receipt}ProductReceipt'):
        purchase = {'spellname': product_receipt.get('ProductId'), 'purchase_id': product_receipt.get('Id')}
        purchase['time'] = get_purchase_time(product_receipt.get('PurchaseDate'))
        price = product_receipt.get('PurchasePrice')
        currency = get_currency(price)
        purchase['price'] = float(price.replace(currency,'')) # note: return as a floating-point number in the local currency
        purchase['currency'] = 'microsoft:' + currency # note: prepend 'microsoft:' to fit spell currency requirements. See make_country_skus2.py
        result.append(purchase)
    return result

def get_currency(price):
    for currency in ("ARS","AUD","BDT","BGN","BHD","BRL","CAD","CHF","CLP","CNY","COP","CRC","CZK","DKK","DZD",
                     "EGP","EUR","GBP","GTQ","HKD","HUF","IDR","ILS","INR","IQD","ISK","JOD","JPY","KES","KRW",
                     "KWD","KZT","LBP","MAD","MRO","MXN","MYR","NGN","NOK","NZD","OMR","PEN","PHP","PKR","PLN",
                     "QAR","RON","RSD","SAR","SEK","SGD","THB","TND","TRY","TTD","TWD","UAH","USD","VND","ZAR"):
        if currency in price: return currency
    raise Exception('%s could not be identified as a valid currency' % price)

def get_purchase_time(purchase_time):
    # MS receipt timestamps are in the format '2021-01-01T18:34:35.231Z'
    return int(time.mktime(time.strptime(purchase_time, '%Y-%m-%dT%H:%M:%S.%fZ')))
