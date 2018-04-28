#!/usr/bin/env python

# IP address geolocation library

# SP3RDPARTY : GeoIP2 library : Apache License

# (for the shipped GeoLite2-Country.mmdb):
# SP3RDPARTY : GeoLite2 GeoIP2 database : CC-by-sa License
# This product includes GeoLite2 data created by MaxMind, available from http://www.maxmind.com.

import sys, os
import geoip2, geoip2.database, geoip2.errors
import logging

log = logging.getLogger('SpinGeoIP')

UNKNOWN = 'unknown'

class SpinGeoIP_Stub(object):
    def get_country(self, ipaddr):
        return UNKNOWN

class SpinGeoIP_geoip2(object):
    def __init__(self, path_to_db_file):
        self.path_to_db_file = path_to_db_file
        self.reader = None
        self.db_file_mtime = -1 # mtime of the db file we're using - allows us to skip reload

        self.reload()

    def reload(self, new_path_to_db_file = None):
        if new_path_to_db_file is not None and new_path_to_db_file != self.path_to_db_file:
            self.path_to_db_file = new_path_to_db_file
            self.db_file_mtime = -1

        if os.path.exists(self.path_to_db_file):
            mtime = os.path.getmtime(self.path_to_db_file)

            if self.db_file_mtime >= mtime:
                # skip the update if the file hasn't changed
                return

            self.reader = geoip2.database.Reader(self.path_to_db_file)
            self.db_file_mtime = mtime

        else:
            log.warning('geoip2 database file not found: %s' % self.path_to_db_file)

    def get_country(self, ipaddr):
        if not self.reader: return UNKNOWN

        try:
            code = self.reader.country(ipaddr).country.iso_code
            if not code:
                return UNKNOWN
            return str(code.lower())
        except geoip2.errors.AddressNotFoundError:
            return UNKNOWN

def SpinGeoIP(path_to_db_file):
    if path_to_db_file:
        return SpinGeoIP_geoip2(path_to_db_file)
    else:
        log.info('No geoip2 database file available. Unable to use IP geolocation.')
        return SpinGeoIP_Stub()

if __name__ == '__main__':
    import getopt

    db_filename = './GeoLite2-Country.mmdb'
    s3_bucket_name = 'spinpunch-puppet'
    s3_key_name = 'GeoLite2-Country.mmdb'
    force = False
    verbose = True

    mode = 'lookup'

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['test','put','get','db-filename=','s3-bucket=','s3-key=','force'])

    for key, val in opts:
        if key == '--test': mode = 'test'
        elif key == '--put': mode = 'put'
        elif key == '--get': mode = 'get'
        elif key == '--db-filename': db_filename = val
        elif key == '--s3-bucket': s3_bucket_name = val
        elif key == '--s3-key': s3_key_name = val
        elif key == '-q': verbose = False
        elif key == '--force': force = True

    logging.basicConfig(level = logging.INFO if verbose else logging.WARNING)

    if mode == 'test': # quick self-test
        geo = SpinGeoIP(db_filename)
        print geo.get_country('182.168.1.1')
        print geo.get_country('8.8.8.8')
        print geo.get_country('2602:0306:36d6:46d0:45eb:f0d6:accc:3819')
        print geo.get_country('2a02:0c7f:5242:9200:5cd5:c475:7388:977a')
        print 'OK!'

    elif mode == 'put':
        # download the latest GeoLite2-Country database file from MaxMind and stash it in S3
        import requests
        import tarfile
        import cStringIO
        import geoip2.database
        import boto3

        url = 'https://geolite.maxmind.com/download/geoip/database/GeoLite2-Country.tar.gz'
        log.info('Downloading %s...', url)
        r = cStringIO.StringIO(requests.get(url).content)

        # annoyingly, the database is packaged inside a directory in this TAR file.
        # unpack the one piece of the TAR that we want, and write it to disk.
        tarf = tarfile.open(fileobj = r, mode = 'r:gz')
        data = None
        for tarinfo in tarf:
            if tarinfo.name.endswith('GeoLite2-Country.mmdb'): # recognize the filename
                data = tarf.extractfile(tarinfo).read() # dump the raw bytes
                break

        if not data:
            log.error('did not find the .mmdb file in the archive!')
        else:
            print type(data)
            log.info('Downloaded and unpacked successfully')
            log.info('Uploading to s3://%s/%s...', s3_bucket_name, s3_key_name)
            boto3.client('s3').upload_fileobj(cStringIO.StringIO(data), s3_bucket_name, s3_key_name,
                                              ExtraArgs = {'ContentType': 'application/octet-stream'})
            log.info('Done! Successfully updated s3://%s/%s', s3_bucket_name, s3_key_name)

    elif mode == 'get':
        # download the S3 copy of the DB to a local file
        import boto3
        import calendar
        client = boto3.client('s3')

        # skip the download if the current file is up to date
        if not force and os.path.exists(db_filename):
            mtime = os.path.getmtime(db_filename)
            response = client.head_object(Bucket = s3_bucket_name, Key = s3_key_name)
            s3_mtime = calendar.timegm(response['LastModified'].timetuple())
            if mtime >= s3_mtime:
                log.info('%s is up to date with s3://%s/%s already.', db_filename, s3_bucket_name, s3_key_name)
                sys.exit(0)

        client.download_file(s3_bucket_name, s3_key_name, db_filename)
        log.info('Downloading s3://%s/%s to %s ...', s3_bucket_name, s3_key_name, db_filename)
        client.download_file(s3_bucket_name, s3_key_name, db_filename)
        log.info('Done! Downloaded %s', db_filename)

    elif mode == 'lookup':
        geo = SpinGeoIP()
        for arg in args:
            print arg, geo.get_country(arg)
