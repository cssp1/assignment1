#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Wrapper for MySQLdb library implementations
# This allows use of either the standard MySQLdb package, or the pure-python pymysql package.

# Prefer MySQLdb if available, otherwise fall back to pymysql
try:
    from MySQLdb import connect, constants, cursors, Timestamp, OperationalError, IntegrityError, Warning
except ImportError:
    try:
        from pymysql import connect, constants, cursors, Timestamp, OperationalError, IntegrityError, Warning
    except ImportError:
        raise Exception('cannot find a MySQLdb or pymysql. At least one of these packages must be installed.')

# these are the only public properties that callers use:
__all__ = ['connect', 'constants', 'cursors', 'Timestamp',
           'OperationalError', 'IntegrityError', 'Warning']
