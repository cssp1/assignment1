#!/usr/bin/env python
# Python code to query Facebook for the number of people who like a "thing":
import urllib2, SpinJSON, SpinFacebook
thing_id = "294844430555178"
url = SpinFacebook.versioned_graph_endpoint('page', thing_id)
print url
request = urllib2.Request(url)
result = urllib2.urlopen(request).read()
print "Number of people who like", thing_id, ":", SpinJSON.loads(result)['likes']
