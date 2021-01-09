#!/usr/bin/env python

# Copyright (c) 2020 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import xml.etree.ElementTree as ET
from signxml import XMLVerifier

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
            result.append({product_receipt.get('ProductId')): product_receipt.get('Id')})
    except:
        return []
    return result
