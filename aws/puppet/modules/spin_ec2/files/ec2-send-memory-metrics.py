#!/usr/bin/env python
# from http://arr.gr/blog/2013/08/monitoring-ec2-instance-memory-usage-with-cloudwatch/

'''
Send memory usage metrics to Amazon CloudWatch

This is intended to run on an Amazon EC2 instance and requires an IAM
role allowing to write CloudWatch metrics. Alternatively, you can create
a boto credentials file and rely on it instead.

Original idea based on https://github.com/colinbjohnson/aws-missing-tools
'''

import sys
import re
from boto.ec2 import cloudwatch
from boto.utils import get_instance_metadata

def collect_memory_usage():
    meminfo = {}
    pattern = re.compile('([\w\(\)]+):\s*(\d+)(:?\s*(\w+))?')
    with open('/proc/meminfo') as f:
        for line in f:
            match = pattern.match(line)
            if match:
                key = match.group(1)
                val = float(match.group(2))
                if match.group(3): # has units
                    units = match.group(3).strip()
                else:
                    units = None
                assert val == 0 or units is None or units == 'kB' # check units
                meminfo[key] = val
    return meminfo

def send_multi_metrics(instance_id, region, metrics, namespace='EC2/Memory',
                       unit='Percent'):
    '''
    Send multiple metrics to CloudWatch
    metrics is expected to be a map of key -> value pairs of metrics
    '''
    cw = cloudwatch.connect_to_region(region)
    cw.put_metric_data(namespace, metrics.keys(), metrics.values(),
                       unit=unit,
                       dimensions={"InstanceId": instance_id})

if __name__ == '__main__':
    metadata = get_instance_metadata()
    instance_id = metadata['instance-id']
    region = metadata['placement']['availability-zone'][0:-1]
    mem_usage = collect_memory_usage()

    mem_free = mem_usage['MemFree'] + mem_usage['Buffers'] + mem_usage['Cached']
    mem_used = mem_usage['MemTotal'] - mem_free
    mem_percent = mem_used / mem_usage['MemTotal'] * 100

    if mem_usage['SwapTotal'] != 0:
        swap_used = mem_usage['SwapTotal'] - mem_usage['SwapFree'] - mem_usage['SwapCached']
        swap_percent = swap_used / mem_usage['SwapTotal'] * 100
    else:
        swap_percent = 0

    metrics = {'MemUsage': mem_percent,
               'SwapUsage': swap_percent }

    send_multi_metrics(instance_id, region, metrics)
