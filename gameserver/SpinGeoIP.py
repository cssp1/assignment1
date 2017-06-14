#!/usr/bin/env python

# IP address geolocation library

# SP3RDPARTY : GeoIP2 library : Apache License

# (for the shipped GeoLite2-Country.mmdb):
# SP3RDPARTY : GeoLite2 GeoIP2 database : CC-by-sa License
# This product includes GeoLite2 data created by MaxMind, available from http://www.maxmind.com.

import SpinConfig
import sys

UNKNOWN = 'unknown'

class SpinGeoIP_Stub(object):
    def get_country(self, ipaddr):
        return UNKNOWN

class SpinGeoIP_geoip2(object):
    def __init__(self, geoip2):
        self.geoip2 = geoip2
        self.reader = self.geoip2.database.Reader(SpinConfig.config['geoip2_country_database'])
    def get_country(self, ipaddr):
        try:
            code = self.reader.country(ipaddr).country.iso_code
            if not code:
                return UNKNOWN
            return str(code.lower())
        except self.geoip2.errors.AddressNotFoundError:
            return UNKNOWN

def SpinGeoIP():
    if 'geoip2_country_database' in SpinConfig.config:
        try:
            import geoip2.database, geoip2.errors
            return SpinGeoIP_geoip2(geoip2)
        except ImportError:
            sys.stderr.write('geoip2 module not found, geolocation disabled\n')
            pass
    return SpinGeoIP_Stub()

if __name__ == '__main__':
    geo = SpinGeoIP()
    print geo.get_country('182.168.1.1')
    print geo.get_country('8.8.8.8')
    print geo.get_country('2602:0306:36d6:46d0:45eb:f0d6:accc:3819')
    print geo.get_country('2a02:0c7f:5242:9200:5cd5:c475:7388:977a')

