#!/usr/bin/env python

# print total size, number of objects, and size/name of biggest object in an S3 bucket

import sys

from boto.s3.connection import S3Connection

s3bucket = S3Connection().get_bucket(sys.argv[1])
size = 0
maxSize = 0
maxName = None
totalCount = 0

for key in s3bucket.list():
    totalCount += 1
    size += key.size
    if key.size > maxSize:
        maxSize = key.size
        maxName = key.name

print 'total size:'
print "%.3f GB" % (size*1.0/1024/1024/1024)
print 'total count:'
print totalCount
print 'max object size and name:'
print maxSize, maxName
