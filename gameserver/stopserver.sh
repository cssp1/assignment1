#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

shopt -s nullglob

killit(){
    local PID="$1"
    kill "$PID" > /dev/null 2>&1
    while kill -0 "$PID" > /dev/null 2>&1; do
        sleep 0.5
    done
}

if [ -e "proxyserver.pid" ]; then
    echo "Stopping proxy server..."
    killit `cat proxyserver.pid`
fi


for PIDFILE in server_*.pid; do
    echo "Stopping game server $PIDFILE..."
    killit `cat $PIDFILE`
done

if [ -e "chatserver.pid" ]; then
    echo "Stopping chat server..."
    killit `cat chatserver.pid`
fi

# Kill database server last, and wait until server really exists
# before killing the database. Otherwise there is a chance it will
# enter an infinite exception loop as it tries and fails to log out
# the last users.

if [ -e "dbserver.pid" ]; then
    echo "Stopping database server..."
    killit `cat dbserver.pid`
fi

echo "Server stopped."
