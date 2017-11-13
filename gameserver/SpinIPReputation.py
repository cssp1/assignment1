#!/usr/bin/env python

# IP address reputation library

# relies on the ip-reputation.json file generated within ../spinpunch-private
# can be reloaded when proxyserver is HUP'ed

import SpinJSON
from ipaddress import IPv6Address, IPv4Address, IPv6Network, IPv4Network, v4_int_to_packed, v6_int_to_packed

class CheckerResult(object):
    def __init__(self, entry):
        self.entry = entry
        self.flags = entry.get('flags',{})
        self.description = entry['description']

    def __repr__(self):
        flag_list = sorted(self.flags.keys())
        if flag_list:
            return '[' + ','.join(flag_list) + ']' + (' %r from %s' % (self.description, self.entry['source']))
        else:
            return 'OK'

    def is_toxic(self): return self.flags.get('toxic',0)

class Checker(object):
    def __init__(self):
        ip_dict = {} # map from range_lo -> ip-reputation entry dict
        for line in open('../spinpunch-private/ip-reputation.json', 'r'):
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

            else:
                # convert CIDR entries to pure lo/hi ranges
                assert ('cidr' in entry)
                if ':' in entry['cidr']:
                    # IPv6 network
                    net = IPv6Network(entry['cidr'])
                    entry['lo*'] = v6_int_to_packed(int(IPv6Address(net[0])))
                    entry['hi*'] = v6_int_to_packed(int(IPv6Address(net[-1])))
                else:
                    # IPv4 network
                    net = IPv4Network(entry['cidr'])
                    entry['lo*'] = v4_int_to_packed(int(IPv4Address(net[0])))
                    entry['hi*'] = v4_int_to_packed(int(IPv4Address(net[-1])))

            # remove some fields to save memory
            for FIELD in ('lo','hi','cidr'):
                if FIELD in entry:
                    del entry[FIELD]

            # intern the common "source" strings
            entry['source'] = intern(str(entry['source']))

            ip_dict[entry['lo*']] = entry

        # tuple of entries, in order of "lo*"
        self.ip_list = tuple(ip_dict[k] for k in sorted(ip_dict.keys()))

    def query(self, ipaddr):
        # convert the ipaddr to binary string
        if ':' in ipaddr:
            # IPv6
            ip = v6_int_to_packed(int(IPv6Address(unicode(ipaddr))))
        else:
            ip = v4_int_to_packed(int(IPv4Address(unicode(ipaddr))))

        # binary search in the sorted list
        hi = len(self.ip_list)-1
        lo = 0
        while hi >= lo:
            med = int((hi+lo)//2)
            if self.ip_list[med]['lo*'] > ip:
                hi = med - 1
            elif self.ip_list[med]['hi*'] < ip:
                lo = med + 1
            else:
                return CheckerResult(self.ip_list[med])

        return None # nothing found

if __name__ == '__main__':
    import sys, getopt

    mode = 'test'
    check_ip = None

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['update','check='])

    for key, val in opts:
        if key == '--update': mode = 'update'
        elif key == '--check': mode = 'check'; check_ip = val

    c = Checker()

    if mode == 'check':
        print check_ip, '->', c.query(check_ip)
    elif mode == 'test':
        for addr in ('127.0.0.1',
                     '8.8.8.8',
                     '5.9.128.128',
                     '69.181.139.56',
                     '2602:0306:36d6:46d0:45eb:f0d6:accc:3819',
                     '2a02:0c7f:5242:9200:5cd5:c475:7388:977a',
                     '2601:701:c100:1e76:5cd5:c475:7388:977a',
                     ):
            print addr, '->', c.query(addr)
