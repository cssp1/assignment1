#!/usr/bin/env python

import subprocess, socket, os, urllib, time, json, sys, getopt

logdna_ingestion_key = os.environ.get('LOGDNA_INGESTION_KEY')
if not logdna_ingestion_key:
    sys.exit(0) # not configured

level = 'INFO'
appname = 'logdna-send'
sitename = os.environ.get('SITENAME','unknown') # ensured by cloud-init runcmd

opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['level=', 'app='])

for key, val in opts:
    if key == '--level': level = val
    elif key == '--app': appname = val

ingest_url = 'https://logs.logdna.com/logs/ingest'
query_params = {'hostname': socket.gethostname(),
                'now': str(int(time.time()))}

file_list = args if len(args) > 0 else ['-',]
lines = []
for filename in file_list:
    fd = open(filename, 'r') if filename != '-' else sys.stdin
    for line in fd.readlines():
        lines.append(line.strip())

if not lines: sys.exit(0) # nothing to send
if len(lines) >= 1000:
    print 'too many lines'; sys.exit(1)

postdata = {'lines': [{'line': line,
                       'app': appname,
                       'level': level.upper(),
                       'env': sitename,
                       } for line in lines]
            }
command = ['curl', ingest_url + '?' + urllib.urlencode(query_params),
           '-s', '-u', logdna_ingestion_key+':',
           '-H', 'Content-Type: application/json; charset=UTF-8',
           '-d', json.dumps(postdata)]
subprocess.check_call(command, stdout=open(os.devnull, 'w'))
