#!/usr/bin/env python

# note: duplicated under game/aws/terraform/modules/ipranges/ and battlehouse-infra/terraform/modules/ipranges/

import json, sys, subprocess

qs = json.load(sys.stdin)

raw_data = subprocess.check_output(['/usr/bin/curl', '-s', 'https://ip-ranges.amazonaws.com/ip-ranges.json'])
data= json.loads(raw_data)

if qs['protocol'] == 'IPv4':
    prefix_list = [x['ip_prefix'] for x in data['prefixes'] if x['service'] == qs['service']]
elif qs['protocol'] == 'IPv6':
    prefix_list = [x['ipv6_prefix'] for x in data['ipv6_prefixes'] if x['service'] == qs['service']]
else:
    raise Exception('"protocol" must be "IPv4" or "IPv6"')

json.dump({'prefix_list_comma_separated': ",".join(prefix_list)}, sys.stdout)
sys.stdout.write('\n')
