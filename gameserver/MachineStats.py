#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# retrieve stats about CPU/memory/disk usage

import sys, os, resource

# returns a dictionary with {key:val} pairs
def get_stats(filesystems = ['/']):
    stats = {}

    if sys.platform != 'linux2':
        stats['error'] = 'unhandled platform'
        fake = 1
    else:
        fake = 0

    pagesize = resource.getpagesize()

    if fake:
        statm = '25240 80 63 11 0 79 0\n'
    else:
        statm = open('/proc/self/statm').readlines()[0]

    resident_pages = int(statm.split(' ')[1])

    # (resident) memory used by this process
    stats['process_memory_mb'] = float(resident_pages*pagesize)/(1024*1024)

    if fake:
        loadavg = '0.00 0.01 0.05 1/109 9911\n'
    else:
        loadavg = open('/proc/loadavg').readlines()[0]

    load_15min = float(loadavg.split(' ')[2])
    stats['loadavg_15min'] = load_15min

    # disk space
    for filesystem in filesystems:
        vfs = os.statvfs(filesystem)
        safe_name = filesystem.replace('.', '&#46;') # for safety, in case we stick this into MongoDB
        free_space_gb = float(vfs.f_bsize*vfs.f_bavail)/float(1024*1024*1024)
        total_space_gb = float(vfs.f_frsize*vfs.f_blocks)/float(1024*1024*1024)
        stats['disk_space_free_gb (%s)' % safe_name] = free_space_gb
        stats['disk_space_total_gb (%s)' % safe_name] = total_space_gb
        stats['disk_space_used_gb (%s)' % safe_name] = total_space_gb - free_space_gb

    # meminfo stats
    if fake:
        meminfo_raw = ("""MemTotal:         611252 kB
        MemFree:           45392 kB
        Buffers:           35948 kB
        SwapTotal:             0 kB
        SwapFree:              0 kB
        Cached:           186284 kB""").split('\n')
    else:
        meminfo_raw = open('/proc/meminfo').readlines()
    meminfo = {}
    for line in meminfo_raw:
        fields = line.split()
        key = fields[0][0:-1]
        val = int(fields[1])
        meminfo[key] = val
    kb_main_total = meminfo['MemTotal']
    kb_swap_total = meminfo['SwapTotal']
    kb_main_free = meminfo['MemFree']
    kb_swap_free = meminfo['SwapFree']
    kb_main_buffers = meminfo['Buffers']
    kb_main_cached = meminfo['Cached']
    kb_main_used = kb_main_total - kb_main_free
    kb_swap_used = kb_swap_total - kb_swap_free
    buffers_plus_cached = kb_main_buffers + kb_main_cached

    stats['machine_mem_used_mb'] = (float(kb_main_used - buffers_plus_cached)/1024)
    stats['machine_mem_free_mb'] = (float(kb_main_free + buffers_plus_cached)/1024)
    stats['machine_swap_used_mb'] = (float(kb_swap_used)/1024)
    stats['machine_swap_free_mb'] = (float(kb_swap_free)/1024)

    return stats

# TEST CODE

if __name__ == '__main__':
    import json
    print json.dumps(get_stats())
