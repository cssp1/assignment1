# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Set up database connection and various tools for standard analytics work
# This is intended to be used from a Jupyter notebook using the command
# "from SpinJupyterEnvironment import *"

# requires Python modules:
# sshtunnel sqlalchemy ipython-sql
import sys, os
sys.path.append(os.path.join(os.getenv('HOME'), 'game', 'gameserver'))
sys.path.append(os.path.join(os.getenv('HOME'), 'cvs', 'game', 'gameserver'))

# make these libraries available to analytics notebooks
import SpinJSON, SpinConfig

config = SpinConfig.config['jupyter']

#"jupyter": {
#    "bastion_host": "....com",
#    "bastion_user": "...",
#    "sql_host": "....rds.amazonaws.com",
#    "sql_port": 3306,
#    "sql_user": "analytics1",
#    "sql_password": "...",
#    "sql_database": "..._upcache"
#    },



# connect to SQL data source via SSH tunnel to bastion host
import sshtunnel

bastion_tunnel = sshtunnel.SSHTunnelForwarder(
    (config['bastion_host'], 22),
    ssh_username = config['bastion_user'],
    remote_bind_address = (config['sql_host'], config['sql_port']),
    compression = True
    )
print 'Connecting to bastion host for SSH tunnel...',
bastion_tunnel.start()
print ' connected.'

print 'Connecting to SQL server...',
sql_connect_string = 'mysql://%s:%s@%s:%d/%s' % \
                     (config['sql_user'], config['sql_password'],
                      '127.0.0.1', bastion_tunnel.local_bind_port,
                      config['sql_database'])
if 1:
    get_ipython().magic('load_ext sql')
    get_ipython().magic('sql '+sql_connect_string)
if 1:
    import sqlalchemy
    db = sqlalchemy.create_engine(sql_connect_string).connect()
print ' connected.'

#import pylab as pylab
#import matplotlib as mpl
import matplotlib.pyplot as plt
#import numpy as np
