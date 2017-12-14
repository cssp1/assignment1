#!/usr/bin/env python

# print total size, number of objects, and size/name of biggest object in an S3 bucket

import sys

from boto.s3.connection import S3Connection

s3bucket = S3Connection().get_bucket(sys.argv[1])
size = 0
maxSize = 0
maxName = None
totalCount = 0

BUCKETS = [{'name': '<16KB', 'size': [0,1<<14]},
           {'name': '16-32KB', 'size': [1<<14,1<<15]},
           {'name': '32-64KB', 'size': [1<<15,1<<16]},
           {'name': '64-128KB', 'size': [1<<16,1<<17]},
           {'name': '128-256KB', 'size': [1<<17,1<<18]},
           {'name': '256-512KB', 'size': [1<<18,1<<19]},
           {'name': '512-1024KB', 'size': [1<<19,1<<20]},
           {'name': '1MB-2MB', 'size': [1<<20,1<<21]},
           {'name': '2MB-4MB', 'size': [1<<21,1<<22]},
           {'name': '4MB-8MB', 'size': [1<<22,1<<23]},
           {'name': '8MB-16MB', 'size': [1<<23,1<<24]},
           {'name': '16MB+', 'size': [1<<24,1<<31]}]
histogram = [0] * len(BUCKETS)

for key in s3bucket.list():
    totalCount += 1
    size += key.size
    if key.size > maxSize:
        maxSize = key.size
        maxName = key.name
    for i, buck in enumerate(BUCKETS):
        if key.size >= buck['size'][0] and key.size < buck['size'][1]:
            histogram[i] += 1

print 'total size:'
print "%.3f GB" % (size*1.0/1024/1024/1024)
print 'total count:'
print totalCount
print 'histogram of sizes:'
for i, buck in enumerate(BUCKETS):
    print '%-12s %8d' % (buck['name']+':', histogram[i])
print 'max object size and name:'
print maxSize, maxName
