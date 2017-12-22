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
    import getopt

    mode = 'lookup'

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['update'])

    for key, val in opts:
        if key == '--update': mode = 'update'

    if mode == 'test':
        geo = SpinGeoIP()
        print geo.get_country('182.168.1.1')
        print geo.get_country('8.8.8.8')
        print geo.get_country('2602:0306:36d6:46d0:45eb:f0d6:accc:3819')
        print geo.get_country('2a02:0c7f:5242:9200:5cd5:c475:7388:977a')

    elif mode == 'update':
        # download the latest GeoLite2-Country database file, and
        # replace the copy in the gameserver/ directory with it

        import requests
        import tarfile
        import cStringIO
        import AtomicFileWrite
        import geoip2.database

        filename = 'GeoLite2-Country.mmdb'

        r = cStringIO.StringIO(requests.get('https://geolite.maxmind.com/download/geoip/database/GeoLite2-Country.tar.gz').content)

        # annoyingly, the database is packaged inside a directory in this TAR file.
        # unpack the one piece of the TAR that we want, and write it to disk.
        tarf = tarfile.open(fileobj = r, mode = 'r:gz')
        for tarinfo in tarf:
            if tarinfo.name.endswith(filename): # recognize the filename
                data = tarf.extractfile(tarinfo).read() # dump the raw bytes
                atom = AtomicFileWrite.AtomicFileWrite(filename, 'wb') # write to disk
                atom.fd.write(data)
                atom.complete()
                break

        print 'Updated! Check in the new file to the SCM.'

    elif mode == 'lookup':
        geo = SpinGeoIP()
        for arg in args:
            print arg, geo.get_country(arg)
