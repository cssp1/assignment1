#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# create all necessary databases and users listed in config.json/"mongodb_servers" on a particular host

import sys, getopt
import SpinConfig
import pymongo # 3.0+ OK
import bson.son

if __name__ == '__main__':
    opts, args = getopt.gnu_getopt(sys.argv, 'u:p:', ['host=','dry-run'])
    username = 'root'
    password = ''
    host = None
    dry_run = False

    for key, val in opts:
        if key == '-u': username = val
        elif key == '-p': password = val
        elif key == '--host': host = val
        elif key == '--dry-run': dry_run = True

    if not host:
        print 'please specify --host='
        sys.exit(1)

    nosql_con = None

    # figure out parent/child relationships and implied databases
    parents = {}
    implicit = set()
    for name, data in SpinConfig.config['mongodb_servers'].iteritems():
        if 'delegate_tables' in data:
            for expr, sub_name in data['delegate_tables'].iteritems():
                parents[sub_name] = data
                if sub_name not in SpinConfig.config['mongodb_servers']:
                    implicit.add(sub_name)

    for name in sorted(list(set(SpinConfig.config['mongodb_servers'].keys()).union(implicit))):
        raw_config = SpinConfig.config['mongodb_servers'].get(name, {})
        raw_conf = SpinConfig.parse_mongodb_config(name, raw_config, parent = parents.get(name,None))

        # build mutated version of the config for "admin" access
        admin_config = raw_config.copy()
        admin_config['dbname'] = 'admin'
        admin_config['username'] = username
        admin_config['password'] = password
        admin_conf = SpinConfig.parse_mongodb_config(name, admin_config, parent = parents.get(name,None))

        if admin_conf['host'] != host: continue
        if not nosql_con:
            # note! connect to 'admin' database as root
            print 'Connecting to', host, 'admin...'
            nosql_con = pymongo.MongoClient(*admin_conf['connect_args'], **admin_conf['connect_kwargs'])

        dbname = raw_config.get('dbname', name)
        if dbname not in nosql_con.database_names():
            print 'Creating database', dbname, 'on', raw_conf['host'], '...'
            if dry_run: continue

        nosql_db = nosql_con[dbname]

        if 'system.roles' in nosql_con['admin'].collection_names():
            #print 'Using MongoDB 2.6+ user schema'
            result = nosql_db.command(bson.son.SON([('usersInfo', {'user': raw_conf['username'], 'db':dbname})]))
            if not result['users']:
                print 'Creating missing user', raw_conf['username'], 'in', dbname, 'on', raw_conf['host'], '...'
                if raw_config.get('read_only',0):
                    roles = ['read']
                else:
                    roles = ['dbAdmin','readWrite','userAdmin']
                if not dry_run:
                    nosql_db.add_user(raw_conf['username'], password=raw_conf['password'], roles=roles)
            elif (not raw_config.get('read_only',0)) and ({'role':'userAdmin','db':dbname} not in result['users'][0]['roles']):
                print name, 'User', raw_conf['username'], 'is missing userAdmin role, fixing...'
                if not dry_run:
                    nosql_db.command(bson.son.SON([('grantRolesToUser',raw_conf['username']), ('roles',['userAdmin'])]))

        else:
            #print 'Using MongoDB 2.4 user schema'
            user = nosql_db['system.users'].find_one({'user': raw_conf['username']})

            if not user:
                print 'Creating missing user', raw_conf['username'], 'in', dbname, 'on', raw_conf['host'], '...'
                if raw_config.get('read_only',0):
                    roles = ['read']
                else:
                    roles = ['dbAdmin','readWrite','userAdmin']
                if not dry_run:
                    nosql_db.add_user(raw_conf['username'], password=raw_conf['password'], roles=roles)
            elif (not raw_config.get('read_only',0)) and ('userAdmin' not in user['roles']):
                print name, 'User', raw_conf['username'], 'is missing userAdmin role, fixing...'
                if not dry_run:
                    nosql_db['system.users'].update({'user': raw_conf['username']}, {'$push':{'roles':'userAdmin'}})

        print 'db', name, 'user', raw_conf['username'], 'OK!'
