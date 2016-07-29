#!/usr/bin/env python

# Delete outdated backup files in s3

import sys, getopt, re, time
import boto.s3.connection, boto.s3.prefix
import logging
from logging import info
import SpinParallel

TASKS = [
    {'bucket': 'spinpunch-forums', 'pattern': 'spinpunch-forums-backup-YYYYMMDD.tar.gz'},
    {'bucket': 'battlehouse-vbulletin-backups', 'pattern': 'battlehouse-vbulletin-YYYYMMDD.tar.gz'},
    {'bucket': 'spinpunch-mattermost-backups', 'pattern': 'spinpunch-mattermost-YYYYMMDD.tar.gz'},
    {'bucket': 'spinpunch-www', 'pattern': 'about-battlehouse-backup-YYYYMMDD.tar.gz'},
    {'bucket': 'spinpunch-www', 'pattern': 'spinpunch-www-backup-YYYYMMDD.tar.gz'},
    {'bucket': 'spinpunch-backups', 'pattern': 'analytics/YYYYMMDD-.*'},
    {'bucket': 'spinpunch-backups', 'pattern': 'skynet/YYYYMMDD-.*'},
    {'bucket': 'spinpunch-backups', 'pattern': 'spinpunch-svn/spinpunch-corp-backup-YYYYMMDD.tar.gz'},

    # per-title userdb/playerdb backups
    {'bucket': 'spinpunch-backups', 'pattern': 'marsfrontier-player-data-YYYYMMDD.*', 'is_dir': True},
    {'bucket': 'spinpunch-backups', 'pattern': 'thunderrun-player-data-YYYYMMDD.*', 'is_dir': True},
    {'bucket': 'spinpunch-backups', 'pattern': 'marsfrontier2-player-data-YYYYMMDD.*', 'is_dir': True},
    {'bucket': 'spinpunch-backups', 'pattern': 'battlefrontmars-player-data-YYYYMMDD.*', 'is_dir': True},
    {'bucket': 'spinpunch-backups', 'pattern': 'summonersgate-player-data-YYYYMMDD.*', 'is_dir': True},
    {'bucket': 'spinpunch-backups', 'pattern': 'daysofvalor-player-data-YYYYMMDD.*', 'is_dir': True},
    ]

ymd_pattern = '(\d{4})(\d{2})(\d{2})'

ts_now = time.gmtime()
def is_old(y, m, d):
    "Files are considered 'old' if from a previous month. But keep monthly files on the 1st."
    if y < ts_now.tm_year and d != 1: return True
    if m < ts_now.tm_mon and d != 1: return True
    return False

def delete_dirs(s3bucket, to_delete):
    deleted_bytes = 0
    for dirkey in to_delete:
        info('DELETING directory %s ...' % dirkey.name)
        keys = s3bucket.list(prefix=dirkey.name)
        deleted_bytes += sum((key.size for key in keys), 0)
        s3bucket.delete_keys(key.name for key in keys)
    return deleted_bytes

def do_task(task, dry_run = False):
    info('checking %s %s ...' % (task['bucket'], task['pattern']))

    is_dir = task.get('is_dir', False)
    s3bucket = boto.s3.connection.S3Connection().get_bucket(task['bucket'])
    common_prefix = task['pattern'].split('YYYYMMDD')[0]
    my_re = re.compile(task['pattern'].replace('YYYYMMDD', ymd_pattern))
    candidates = []
    seen_bytes = 0
    deleted_bytes = 0
    first_days_by_month = {}

    # first pass - get key names and check the first recorded backup date in each month
    # (which might not be the 1st!)
    for key in s3bucket.list(prefix = common_prefix, delimiter = '/' if is_dir else None):
        if is_dir and not isinstance(key, boto.s3.prefix.Prefix):
            info('SKIPPING - not a directory: %s' % key.name)
            continue
        match = my_re.match(key.name)
        if match:
            y, m, d = map(int, match.groups())
            if (y,m) not in first_days_by_month:
                first_days_by_month[(y,m)] = d
            else:
                first_days_by_month[(y,m)] = min(first_days_by_month[(y,m)], d)
            candidates.append((key, (y,m,d)))
            if not is_dir:
                seen_bytes += key.size # note! doesn't count files under this prefix for dirs!

    to_delete = []
    for key, ymd in candidates:
        y, m, d = ymd
        if d == first_days_by_month[(y,m)]:
            if d != 1:
                info('SKIPPING - first data of month: %s' % key.name)
            continue
        if is_old(y,m,d):
            to_delete.append(key)

    if to_delete:
        to_delete.sort()
        info('DELETING:' if not dry_run else 'intend to delete the following:')
        info('\n'.join(key.name for key in to_delete))

        if not dry_run:
            if is_dir:
                deleted_bytes += delete_dirs(s3bucket, to_delete)
            else:
                s3bucket.delete_keys(key.name for key in to_delete)
                deleted_bytes += sum((key.size for key in to_delete), 0)

    return {'seen_bytes': seen_bytes,
            'deleted_bytes': deleted_bytes}

def do_slave(input):
    return do_task(input['task'], dry_run = input['dry_run'])

def reduce(accum, result_list):
    accum['seen_bytes'] += sum((r['seen_bytes'] for r in result_list), 0)
    accum['deleted_bytes'] += sum((r['deleted_bytes'] for r in result_list), 0)

if __name__ == "__main__":
    logging.basicConfig(level = logging.INFO)

    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['dry-run','parallel='])
    dry_run = False
    parallel = len(TASKS)

    for key, val in opts:
        if key == '--dry-run': dry_run = True
        elif key == '--parallel': parallel = int(val)

    accum = {'seen_bytes': 0, 'deleted_bytes': 0}

    if parallel <= 1:
        reduce(accum, (do_task(task, dry_run = dry_run) for task in TASKS))
    else:
        reduce(accum, SpinParallel.go([{'task':task, 'dry_run':dry_run} for task in TASKS],
                                      [sys.argv[0], '--slave'], on_error = 'continue', nprocs=parallel, verbose = False))
    gig = 1024.0*1024.0*1024.0
    info('DONE! Saw %.1fGB (excluding userdb/playerdb), deleted %.1fGB' % (accum['seen_bytes']/gig, accum['deleted_bytes']/gig))
