#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# SpinUserDB.py
# routines for manipulating the live userdb/playerdb data

import SpinConfig
import SpinS3
import AtomicFileWrite
import os, glob, hashlib

class Driver (object):
    def __init__(self):
        pass
    def user_exists(self, id):
        return os.path.exists(self.get_user_path(id))

    # optimal number of concurrent I/O processes
    def optimal_io_channels(self): return 1
    # which I/O process is best to serve a given userdb/playerdb entry
    def io_channel_for_user(self, id): return 0
    def io_channel_for_player(self, id): return 0
    def io_channel_for_aistate(self): return 0
    def io_channel_for_base(self, id): return 0
    def get_filesystems(self): return []

class FileDriver (Driver):
    # synchronous methods, used by analytics tools (not main server)
    def sync_get_player_mtime(self, id): return os.path.getmtime(self.get_player_path(id))

    def sync_download_user(self, id): return open(self.get_user_path(id)).read()
    def sync_download_player(self, id): return open(self.get_player_path(id)).read()
    def sync_download_base(self, region, id): return open(self.get_base_path(region, id)).read()

    def _sync_write(self, filename, buf):
        atom = AtomicFileWrite.AtomicFileWrite(filename, 'w')
        atom.fd.write(buf)
        atom.complete()
    def _sync_delete(self, filename):
        try: os.unlink(filename)
        except: pass
    def sync_write_user(self, id, buf): self._sync_write(self.get_user_path(id), buf)
    def sync_write_player(self, id, buf): self._sync_write(self.get_player_path(id), buf)
    def sync_write_base(self, region, id, buf): self._sync_write(self.get_base_path(region, id), buf)
    def sync_delete_base(self, region, id): self._sync_delete(self.get_base_path(region, id))
    def get_aistate_path(self, user_id, game_id, ai_id):
        name = '%d_%s_%d.txt' % (user_id, game_id, ai_id)
        return os.path.join(SpinConfig.config['aistate_dir'], name)

    def collect_aistate_garbage(self, min_mtime):
        for filename in glob.glob(os.path.join(SpinConfig.config['aistate_dir'], '*.txt')):
            try:
                mtime = os.path.getmtime(filename)
                if mtime < min_mtime:
                    print 'aistate: deleting', filename
                    try:
                        os.unlink(filename)
                    except:
                        pass
            except:
                pass

# old flat userdb/playerdb driver
class FlatDirectoryDriver (FileDriver):
    def get_user_path(self, id):
        return os.path.join(SpinConfig.config['userdb_dir'], str(id)+'.txt')
    def get_player_path(self, id):
        return os.path.join(SpinConfig.config['playerdb_dir'], str(id)+'_'+SpinConfig.config['game_id']+'.txt')
    def get_base_path(self, region, id):
        return os.path.join(SpinConfig.config.get('basedb_dir','basedb'), str(region)+'_'+str(id)+'_'+SpinConfig.config['game_id']+'.txt')

    # return list of relevant filesystems (for checking free space)
    # relative to gameserver/
    def get_filesystems(self):
        return [SpinConfig.config['userdb_dir']+'/',
                SpinConfig.config['playerdb_dir']+'/',
                SpinConfig.config.get('aistate_dir', 'aistate')+'/',
                SpinConfig.config.get('basedb_dir', 'basedb')+'/']


class BucketedDirectoryDriver (FileDriver):
    def __init__(self):
        self.nbuckets = 100
        self.partitions = 5 # hard-coded for mfprod
    def user_id_bucket(self, id):
        return id % self.nbuckets
    def base_id_bucket(self, id):
        return int(id[-2:]) % self.nbuckets
    def get_user_dir_for_bucket(self, bucket):
        return 'user%02d' % bucket
    def get_player_dir_for_bucket(self, bucket):
        return 'player%02d' % bucket
    def get_base_dir_for_bucket(self, bucket):
        return 'base%02d' % bucket
    def get_user_path(self, id):
        bucket = self.user_id_bucket(id)
        return os.path.join(SpinConfig.config['userdb_dir'], self.get_user_dir_for_bucket(bucket), str(id)+'.txt')
    def get_player_path(self, id):
        bucket = self.user_id_bucket(id)
        return os.path.join(SpinConfig.config['playerdb_dir'], self.get_player_dir_for_bucket(bucket), str(id)+'_'+SpinConfig.config['game_id']+'.txt')
    def get_base_path(self, region, id):
        bucket = self.base_id_bucket(id)
        return os.path.join(SpinConfig.config.get('basedb_dir', 'basedb'), self.get_base_dir_for_bucket(bucket), str(region)+'_'+str(id)+'_'+SpinConfig.config['game_id']+'.txt')

    def optimal_io_channels(self):
        # one I/O channel per physical volume (one set of partitions each for userdb, playerdb, and one for aistate/bases)
        return 2*self.partitions+1

    # hard-coded for mfprod filesystem layout
    def io_channel_for_user(self, id):
        return id % self.partitions
    def io_channel_for_player(self, id):
        return (id % self.partitions) + self.partitions
    def io_channel_for_aistate(self):
        return 2*self.partitions
    def io_channel_for_base(self, id):
        return 2*self.partitions

    def get_filesystems(self):
        # ugly :(
        return glob.glob('/storage/mfprod-userA*') + glob.glob('/storage/mfprod-playerA*') + \
               [SpinConfig.config.get('aistate_dir', 'aistate')+'/',
                SpinConfig.config.get('basedb_dir', 'basedb')+'/']


class S3Driver (Driver):
    # the "bucket" terminology is unfortunate here.
    # There are only three S3 buckets, one for userdb, one for playerdb, and one for aistate
    # S3 objects are subdivided further into 100 folders, to spread the S3 key space more efficiently.

    def __init__(self, game_id = None, key_file = None, userdb_bucket = None, playerdb_bucket = None, aistate_bucket = None, basedb_bucket = None, verbose = False):
        self.nbuckets = 100
        if game_id is None: game_id = SpinConfig.config['game_id']
        self.game_id = game_id
        self.userdb_bucket = userdb_bucket if userdb_bucket else SpinConfig.config.get('userdb_s3_bucket', None)
        self.playerdb_bucket = playerdb_bucket if playerdb_bucket else SpinConfig.config.get('playerdb_s3_bucket', None)
        self.aistate_bucket = aistate_bucket if aistate_bucket else SpinConfig.config.get('aistate_s3_bucket', None)
        self.basedb_bucket = basedb_bucket if basedb_bucket else SpinConfig.config.get('basedb_s3_bucket', None)
        self.s3con = SpinS3.S3(key_file if key_file else SpinConfig.aws_key_file(), verbose=verbose, use_ssl=True)

    def user_id_bucket(self, id):
        return id % self.nbuckets
    def base_id_bucket(self, id):
        return int(id[-2:]) % self.nbuckets
    def get_user_prefix_for_bucket(self, bucket):
        return '%02d' % bucket
    def get_player_prefix_for_bucket(self, bucket):
        return '%02d' % bucket
    def get_base_prefix_for_bucket(self, bucket):
        return '%02d' % bucket

    # NOTE: get_*_path() in S3 driver returns a tuple of (S3 bucket, objname) instead of a filename
    def get_user_path(self, id):
        bucket = self.user_id_bucket(id)
        return (self.userdb_bucket, self.get_user_prefix_for_bucket(bucket) + '/'+ str(id) + '.txt')
    def get_player_path(self, id):
        bucket = self.user_id_bucket(id)
        return (self.playerdb_bucket, self.get_player_prefix_for_bucket(bucket) + '/' + str(id)+'_'+self.game_id+'.txt')
    def get_base_path(self, region, id):
        bucket = self.base_id_bucket(id)
        return (self.basedb_bucket, str(region)+'/'+self.get_base_prefix_for_bucket(bucket) + '/' + str(id)+'_'+self.game_id+'.txt')

    def get_aistate_path(self, user_id, game_id, ai_id):
        name = '%d_%s_%d.txt' % (user_id, game_id, ai_id)
        # prepend hash to spread keys around more evenly
        objname = hashlib.md5(name).hexdigest() + '-' + name
        return (self.aistate_bucket, objname)


    # synchronous operations

    def sync_get_player_mtime(self, id):
        bucket, objname = self.get_player_path(id)
        return self.s3con.exists(bucket, objname)

    def _sync_download(self, bucket, objname): return self.s3con.get_slurp(bucket, objname)
    def sync_download_user(self, id): return self._sync_download(*self.get_user_path(id))
    def sync_download_player(self, id): return self._sync_download(*self.get_player_path(id))
    def sync_download_base(self, region, id): return self._sync_download(*self.get_base_path(region, id))

    def _sync_write(self, bucket, objname, buf): self.s3con.put_buffer(bucket, objname, buf)
    def sync_write_user(self, id, buf): self._sync_write(*(self.get_user_path(id)+(buf,)))
    def sync_write_player(self, id, buf): self._sync_write(*(self.get_player_path(id)+(buf,)))
    def sync_write_base(self, region, id, buf): self._sync_write(*(self.get_base_path(region, id)+(buf,)))
    def sync_delete_base(self, region, id): self.s3con.delete(*self.get_base_path(region, id))
    def collect_aistate_garbage(self, min_time): pass # auto-collected by S3 lifecycle rule

DRIVERS = { 'flat': FlatDirectoryDriver,
            'bucketed': BucketedDirectoryDriver,
            's3': S3Driver }

driver = DRIVERS[SpinConfig.config.get('userdb_driver', 'flat')]()
