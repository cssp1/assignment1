#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# scan through userdb/playerdb and update upcache

# this utility used to do much more (output aggregate totals as breakdowns by search keys
# and annotate metrics logs with cross-references to userdb). However, it has slowly been
# replaced by other tools, like ANALYTICS2, that read directly from upcache.

# nowadays, dump_userdb.py exists only to be run regularly to keep upcache up to date.

import sys, os, time, traceback
import FastGzipFile
import getopt
import SpinJSON
import SpinConfig
import SpinUpcache
import SpinUpcacheIO
import SpinS3
import SpinUserDB
import SpinNoSQL
import AtomicFileWrite
import SpinParallel
import SpinSingletonProcess

gamedata = SpinJSON.load(open(SpinConfig.gamedata_filename()))

def open_cache(cache_read, cache_segments, from_s3_bucket, from_s3_keyfile, progress):
    if not cache_read: return None
    try:
        if from_s3_bucket:
            cache = SpinUpcacheIO.S3Reader(SpinS3.S3(from_s3_keyfile, verbose = progress), from_s3_bucket, cache_read, verbose = progress, skip_empty = False, skip_developer = False)
        else:
            cache = SpinUpcacheIO.LocalReader(cache_read, skip_empty = False, skip_developer = False)
        if cache.num_segments() != cache_segments:
            sys.stderr.write('got cache %s but number of segments is different (cache %d req %d)\n' % \
                             (cache_read, cache.num_segments(), cache_segments))
            cache = None
    except Exception as e:
        sys.stderr.write('error reading previous upcache: %r\n%s\n' % (e, traceback.format_exc()))
        cache = None
    return cache

def dump_user(seg, id, entry, method, cache_fd, nosql_table, nosql_deltas_only, ignore_users, mod_users, progress, user_count, user_total, userdb_driver, time_now):
    if id in ignore_users: return

    if entry and (mod_users is not None) and (id not in mod_users):
        method += ' (not modified!)'
        user_mtime = 1
        changed = False
    else:
        method += ' (possible mod!)\n'
        user_mtime = -1 # ping filesystem to get mtime
        changed = True

    if progress:
        sys.stderr.write('\rreading segment %3d user %7d of %7d (%5.2f%%) ID %7d from %s' % (seg, user_count, user_total, 100.0*float(user_count)/float(user_total), id, method))

    obj = None

    try:
        obj = SpinUpcache.update_upcache_entry(id, userdb_driver, entry, time_now, gamedata, user_mtime = user_mtime)
    except:
        sys.stderr.write('error updating user %d:\n' % id + traceback.format_exc() + '\n')

    if not obj:
        return None

    # perform upcache output
    if cache_fd:
        SpinJSON.dump(obj, cache_fd, pretty = False, newline = True)

    if nosql_table and (changed or (not nosql_deltas_only)):
        obj['_id'] = obj['user_id'] # SpinNoSQL.NoSQLClient.encode_object_id('%024d'%obj['user_id'])
        nosql_table.replace_one({'_id':obj['_id']}, obj, upsert=True)

    return obj



def do_slave(input):
    seg = input['seg']
    ignore_users = set(input['ignore_users'])
    mod_users = set(input['mod_users']) if (input['mod_users'] is not None) else None

    if input['s3_userdb']:
        userdb_driver = SpinUserDB.S3Driver()
    else:
        userdb_driver = SpinUserDB.driver

    to_mongodb_config = input['to_mongodb_config']
    if to_mongodb_config:
        import pymongo # 3.0+ OK
        nosql_client = pymongo.MongoClient(*input['to_mongodb_config']['connect_args'],
                                           **input['to_mongodb_config']['connect_kwargs'])[to_mongodb_config['dbname']]
        nosql_table = nosql_client[to_mongodb_config['tablename']].with_options(write_concern = pymongo.write_concern.WriteConcern(w=0))
    else:
        nosql_table = None
    nosql_deltas_only = input.get('nosql_deltas_only', False)

    cache = open_cache(input['cache_read'], input['cache_segments'], input['from_s3_bucket'], input['from_s3_keyfile'], False)

    # list of all user_ids in this segment
    user_id_set = set([id for id in xrange(input['user_id_range'][0], input['user_id_range'][1]+1) if SpinUpcache.get_segment_for_user(id, input['cache_segments']) == seg])
    user_count = 0 # number updated so far
    user_total = len(user_id_set) # total number to update

    # set up segment output
    if input['filename']:
        write_atom = AtomicFileWrite.AtomicFileWrite(input['filename'], 'w')
        write_process = FastGzipFile.WriterProcess(write_atom.fd)
        write_zipfd = write_process.stdin
    else:
        write_zipfd = None

    # first stream through upcache, in whatever order the segment upcache is in
    if cache:
        cache_seg = cache.iter_segment(seg)
        for entry in cache_seg:
            id = entry['user_id']

            if SpinUpcache.get_segment_for_user(id, input['cache_segments']) != seg:
                sys.stderr.write('\nuser %d does not belong in segment %d!\n' % (id, seg))
                continue

            if id not in user_id_set: continue
            # mark the user as already done so we skip him in the second pass
            user_id_set.remove(id)

            dump_user(seg, id, entry, 'cache', write_zipfd, nosql_table, nosql_deltas_only, ignore_users, mod_users, input['progress'], user_count, user_total, userdb_driver, input['time_now'])
            user_count += 1

        if input['progress']:
            sys.stderr.write('\ncached pass done seg %d\n' % seg)

    # now get the remaining users belonging to this segment from original userdb files
    for user_id in user_id_set:
        if SpinUpcache.get_segment_for_user(user_id, input['cache_segments']) == seg:
            dump_user(seg, user_id, None, 'source', write_zipfd, nosql_table, nosql_deltas_only, ignore_users, mod_users, input['progress'], user_count, user_total, userdb_driver, input['time_now'])
            user_count += 1

    if input['progress']:
        sys.stderr.write('\nuncached pass done seg %d\n' % seg)

    if write_zipfd:
        write_zipfd.flush()
        write_zipfd.close()
        write_process.communicate() # force gzip to finish
        write_atom.complete()
        if input['to_s3_bucket']:
            SpinS3.S3(input['to_s3_keyfile'], verbose = False).put_file(input['to_s3_bucket'], os.path.basename(input['filename']), input['filename'])


if __name__ == "__main__":
    if '--slave' in sys.argv:
        SpinParallel.slave(do_slave)
        sys.exit(0)

    opts, args = getopt.gnu_getopt(sys.argv[1:], '', ['cache-only', 's3-userdb', 'from-s3-keyfile=', 'to-s3-keyfile=',
                                                      'from-s3-bucket=', 'to-s3-bucket=', 'to-mongodb=', 'nosql-deltas-only',
                                                      'cache-read=', 'cache-write=', 'cache-segments=', 'parallel=',
                                                      'cache-update-time=',
                                                      'use-dbserver=',
                                                      'include-developers', 'progress'])

    include_developers = False
    progress = False
    from_s3_bucket = None
    to_s3_bucket = None
    to_mongodb_config = None
    nosql_deltas_only = False
    s3_userdb = False
    to_s3_keyfile = from_s3_keyfile = SpinConfig.aws_key_file()
    use_dbserver = True
    cache_read = None
    cache_write = None
    cache_segments = 1
    cache_update_time = -1
    parallel = 1
    time_now = int(time.time())

    for key, val in opts:
        if key == '--include-developers':
            include_developers = True
        elif key == '--progress':
            progress = True
        elif key == '--s3-userdb':
            s3_userdb = True
        elif key == '--from-s3-keyfile':
            from_s3_keyfile = val
        elif key == '--to-s3-keyfile':
            to_s3_keyfile = val
        elif key == '--from-s3-bucket':
            from_s3_bucket = val
        elif key == '--to-s3-bucket':
            to_s3_bucket = val
        elif key == '--to-mongodb':
            to_mongodb_config = SpinConfig.get_mongodb_config(val)
            to_mongodb_config['tablename'] = to_mongodb_config['table_prefix']+val
        elif key == '--nosql-deltas-only':
            nosql_deltas_only = True
        elif key == '--use-dbserver':
            use_dbserver = bool(int(val))
        elif key == '--cache-read':
            cache_read = val
        elif key == '--cache-write':
            cache_write = val
        elif key == '--cache-segments':
            cache_segments = int(val)
        elif key == '--cache-update-time':
            cache_update_time = int(val)
        elif key == '--parallel':
            parallel = int(val)

    if include_developers:
        ignore_users = []
    else:
        ignore_users = SpinConfig.config.get('developer_user_id_list', [])

    with SpinSingletonProcess.SingletonProcess('dump_userdb-%s' % SpinConfig.config['game_id']):

        cache = open_cache(cache_read, cache_segments, from_s3_bucket, from_s3_keyfile, progress)

        if cache and cache_update_time < 0:
            cache_update_time = cache.update_time()

        if cache:
            if progress:
                sys.stderr.write('will read cache %s (%d segs, updated %d)\n' % (cache_read, cache_segments, cache_update_time))

        # connect to dbserver to ask it for the ID range and list of recent logins
        nosql_client = None
        if use_dbserver:
            db_client = SpinNoSQL.NoSQLClient(SpinConfig.get_mongodb_config(SpinConfig.config['game_id']))

        if db_client:
            if progress: sys.stderr.write('successfully connected to database...\n')

        # master set of all user_ids that need updating
        if db_client:
            if progress: sys.stderr.write('getting all user_ids from live database...\n')
            user_id_range = db_client.get_user_id_range()
        else:
            if progress: sys.stderr.write('getting all user_ids using local file read...\n')
            user_id_range = SpinUserDB.driver.get_user_id_range()

        if progress:
            sys.stderr.write('user_id range %s...\n' % repr(user_id_range))

        # try to get the minimal set of user_ids that were updated since last upcache run
        mod_users = None
        if cache and cache_update_time > 0:
            if db_client:
                if progress: sys.stderr.write('getting recent login list using database...\n')
                mod_users = db_client.get_users_modified_since(cache_update_time)
            else:
                if progress: sys.stderr.write('getting recent login list using sessions.json...\n')
                mod_users = SpinUserDB.get_users_modified_since(cache_update_time, time_now)

        if mod_users is not None:
            if progress:
                sys.stderr.write('got accurate modification list! Will only update %d users!\n' % len(mod_users))

        task_list = [{'seg':seg,
                      'ignore_users': ignore_users,
                      'mod_users': mod_users,
                      's3_userdb': s3_userdb,
                      'from_s3_keyfile': from_s3_keyfile,
                      'from_s3_bucket': from_s3_bucket,
                      'to_s3_keyfile': to_s3_keyfile,
                      'to_s3_bucket': to_s3_bucket,
                      'to_mongodb_config': to_mongodb_config,
                      'nosql_deltas_only': nosql_deltas_only,
                      'user_id_range': user_id_range,
                      'progress': progress,
                      'time_now': time_now,
                      'cache_segments': cache_segments,
                      'cache_read': cache_read,
                      'filename': (cache_write+SpinUpcache.segment_name(seg, cache_segments)+'.sjson.gz') if cache_write else None,
                      } for seg in xrange(cache_segments)]

        # dump all segments
        if parallel <= 1:
            for task in task_list:
                do_slave(task)
        else:
            SpinParallel.go(task_list, [sys.argv[0], '--slave'], on_error = 'break', nprocs=parallel, verbose = False)

        # write info file
        if cache_write:
            info_filename = cache_write + '-info.json'
            props = {'update_time':time_now,
                     'segments': [task['filename'] for task in task_list]}
            fd = open(info_filename, 'w')
            SpinJSON.dump(props, fd, pretty = True, newline = True)
            fd.close()

            if to_s3_bucket:
                SpinS3.S3(to_s3_keyfile, verbose = progress).put_file(to_s3_bucket, os.path.basename(info_filename), info_filename)
