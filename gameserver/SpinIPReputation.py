#!/usr/bin/env python

# IP address reputation library

# relies on the ip-reputation.json file generated within ../spinpunch-private
# can be reloaded when proxyserver is HUP'ed

import SpinJSON
from ipaddress import IPv6Address, IPv4Address, IPv6Network, IPv4Network, v4_int_to_packed, v6_int_to_packed
import os
import logging

log = logging.getLogger('SpinIPReputation')

class CheckerResult(object):
    def __init__(self, entry):
        self.entry = entry
        self.flags = entry.get('flags',{})
        self.description = entry['description']
        self.asn = entry.get('asn', -1)
        self.country = entry.get('country','zz')

    def __repr__(self):
        flag_list = sorted(self.flags.keys())
        if flag_list:
            return '[' + ','.join(flag_list) + ']' + (' %r from %s' % (self.description, self.entry['source']))
        else:
            return 'OK'

    def is_toxic(self): return self.flags.get('toxic',0)

    def is_alt_factory(self): return self.flags.get('alt_factory',0)

    def is_proxy(self): return self.flags.get('proxy',0)

    def is_tor(self): return self.flags.get('tor',0)

    def is_datacenter(self): return self.flags.get('datacenter',0)

    def is_vpn(self): return self.is_tor() or self.is_proxy() or self.is_datacenter()

class Checker(object):
    @classmethod
    def get_db_file_hash(cls, path_to_db_file):
        """ Return a stable hash of the reputation DB file.
        None if it doesn't exist, otherwise (size, mtime) tuple. """
        if not os.path.exists(path_to_db_file):
            log.warning('IP reputation database not found: %s', path_to_db_file)
            return None
        stats = os.stat(path_to_db_file)
        return (stats.st_size, stats.st_mtime)

    def __init__(self, path_to_db_file):
        self.path_to_db_file = path_to_db_file
        self.cached_db_file_hash = None
        self.ip_dict = {} # stores single entries to prevent conflicts with lo/hi and CIDR entries.
        self.ip_list4 = tuple()
        self.ip_list6 = tuple()
        self.reload()

    def reload(self):
        """ Reload the reputation DB file from disk into memory.
        But do nothing if the DB file hash hasn't changed since the previous load.
        Return True if new data was loaded. """

        if (not self.path_to_db_file):
            # silently disable the checker
            return False

        new_db_file_hash = self.get_db_file_hash(self.path_to_db_file)

        # if hash is up to date, do nothing
        if new_db_file_hash == self.cached_db_file_hash:
            log.debug('In-memory DB is current. Not reloading.')
            return False

        elif new_db_file_hash:
            log.debug('Reloading in-memory DB...')
            self.do_reload()
            self.cached_db_file_hash = new_db_file_hash
            log.debug('Done reloading in-memory DB.')
            return True

        else: # new_db_file_hash is None, meaning the file is missing
            return False

    def do_reload(self):
        ip_dict4 = {} # map from range_lo -> ip-reputation entry dict
        ip_dict6 = {} # map from range_lo -> ip-reputation entry dict

        for line in open(self.path_to_db_file, 'r'):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            entry = SpinJSON.loads(line)

            # add a packed byte string representation of the lo/hi bounds
            # as 'lo*' or 'hi*' for efficient lookups

            if 'lo' in entry and 'hi' in entry:
                # these are guaranteed to be IPv4
                assert ('.' in entry['lo']) and (':' not in entry['lo'])
                entry['lo*'] = v4_int_to_packed(int(IPv4Address(entry['lo'])))
                entry['hi*'] = v4_int_to_packed(int(IPv4Address(entry['hi'])))
                ipv = 4
            else:
                # convert CIDR entries to pure lo/hi ranges
                assert ('cidr' in entry)
                if '/' not in entry['cidr']:
                    # place solo IP into ip dict and proceed
                    ip = entry['cidr'].lower()
                    entry['source'] = intern(str(entry['source']))
                    self.ip_dict[ip] = entry
                    continue
                if ':' in entry['cidr']:
                    # IPv6 network
                    net = IPv6Network(entry['cidr'])
                    entry['lo*'] = v6_int_to_packed(int(IPv6Address(net[0])))
                    entry['hi*'] = max(v6_int_to_packed(int(IPv6Address(net[-1]))), ip_dict4.get(entry['lo*'], {'hi*': v6_int_to_packed(0)})['hi*'])
                    ipv = 6
                else:
                    # IPv4 network
                    net = IPv4Network(entry['cidr'])
                    entry['lo*'] = v4_int_to_packed(int(IPv4Address(net[0])))
                    entry['hi*'] = max(v4_int_to_packed(int(IPv4Address(net[-1]))), ip_dict4.get(entry['lo*'], {'hi*': v4_int_to_packed(0)})['hi*'])
                    ipv = 4

            # remove some fields to save memory
            for FIELD in ('lo','hi','cidr'):
                if FIELD in entry:
                    del entry[FIELD]

            # intern the common "source" strings
            entry['source'] = intern(str(entry['source']))

            if ipv == 4:
                ip_dict4[entry['lo*']] = entry
            elif ipv == 6:
                ip_dict6[entry['lo*']] = entry
            else:
                raise Exception('unknown ipv')

        # tuple of entries, in order of "lo*"
        self.ip_list4 = tuple(ip_dict4[k] for k in sorted(ip_dict4.keys()))
        self.ip_list6 = tuple(ip_dict6[k] for k in sorted(ip_dict6.keys()))

    def query(self, ipaddr):

        # a solo entry from tor lists or ip-reputation-manual.json can be returned directly to save time
        if ipaddr.lower() in self.ip_dict:
            return CheckerResult(self.ip_dict[ipaddr.lower()])

        # convert the ipaddr to binary string
        if ':' in ipaddr:
            # IPv6
            ip = v6_int_to_packed(int(IPv6Address(unicode(ipaddr))))
            ip_list = self.ip_list6
        else:
            ip = v4_int_to_packed(int(IPv4Address(unicode(ipaddr))))
            ip_list = self.ip_list4

        # binary search in the sorted list
        hi = len(ip_list)-1
        lo = 0
        while hi >= lo:
            med = int((hi+lo)//2)
            if ip_list[med]['lo*'] > ip:
                hi = med - 1
            elif ip_list[med]['hi*'] < ip:
                lo = med + 1
            else:
                return CheckerResult(ip_list[med])

        return None # nothing found

if __name__ == '__main__':
    import sys, getopt

    s3_bucket_name = 'spinpunch-puppet'
    s3_key_name = 'ip-reputation.json'
    db_filename = './ip-reputation.json'
    mode = 'check'
    force = False
    verbose = True

    opts, args = getopt.gnu_getopt(sys.argv[1:], 'q', ['test','get','db-filename=','s3-bucket-name=','s3-key-name=','force'])

    for key, val in opts:
        if key == '--get': mode = 'get'
        elif key == '--test': mode = 'test'
        elif key == '--db-filename': db_filename = val
        elif key == '--s3-bucket-name': s3_bucket_name = val
        elif key == '--s3-key-name': s3_key_name = val
        elif key == '--force': force = True
        elif key == '-q': verbose = False

    logging.basicConfig(level = os.environ.get('LOGLEVEL') or (logging.INFO if verbose else logging.WARNING))

    if mode == 'check':
        c = Checker(db_filename)
        for check_ip in args:
            print check_ip, '->', c.query(check_ip)
    elif mode == 'test':
        c = Checker(db_filename)
        for addr in ('127.0.0.1', # None
                     '8.8.8.8', # None
                     '5.9.128.128', # datacenter
                     '69.181.139.56', # None
                     '2602:0306:36d6:46d0:45eb:f0d6:accc:3819', # None
                     '2a02:0c7f:5242:9200:5cd5:c475:7388:977a', # None
                     '2601:701:c100:1e76:5cd5:c475:7388:977a', # None
                     '2600:1700:fe30:7ca0:542e:f64f:b412:da4a', # None
                     ):
            print addr, '->', c.query(addr)
        c.reload()

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

        log.info('Downloading s3://%s/%s to %s ...', s3_bucket_name, s3_key_name, db_filename)
        client.download_file(s3_bucket_name, s3_key_name, db_filename)
        log.info('Done! Downloaded %s', db_filename)
