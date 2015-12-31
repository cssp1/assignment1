#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

if [ -e "server_default.pid" ]; then
    echo "Server seems to be running already, use ./stopserver.sh to stop it."
    echo "If you are still having problems, please follow the steps here:"
    echo "https://sites.google.com/a/spinpunch.com/developers/game-design/trouble-shooting"
    exit 1
fi

DO_ART=1
while getopts "n" flag
do
    case $flag in
        n)
            DO_ART=0
            ;;
     esac
done

if [[ "$DO_ART" == 1 ]]; then
        echo "Downloading latest art pack..."
        ./download-art.sh -q -f
fi

echo "Running SCM maintenance..."
../scmtool.sh clean

echo "Clearing gamedata build directories..."
rm -f ../gamedata/*/built/*

if [ -e ../gamedata/linebreak/Makefile ]; then
    echo "Building linebreak tool..."
    (cd ../gamedata/linebreak && make -s)
    if [[ $? != 0 ]]; then
        echo "error building linebreak tool, not starting server."
        exit 1
    fi
fi

echo "Calculating client JavaScript include dependencies..."
(cd ../gameclient && make -f Makefile dep)

echo "Compiling client JavaScript code..."
(cd ../gameclient && make -f Makefile all)

./make-gamedata.sh -u
if [[ $? != 0 ]]; then
    echo "gamedata error, not starting server."
    exit 1
fi

if [ -e ../.svn ]; then
    svnversion > version.txt
elif [ -e ../.git ]; then
    git rev-parse HEAD > version.txt
fi

if grep -q "chatserver" config.json; then
    if [ ! -e "chatserver.pid" ]; then
        echo "Running chat server..."
        ./chatserver.py
        if [[ $? != 0 ]]; then
            echo "chat server startup error!"
            exit 1
        fi
    fi
fi

echo "Running database maintenance..."
./SpinNoSQL.py --maint > /dev/null

echo "Running game server (default) version ${VERSION}..."
./server.py default
if [[ $? != 0 ]]; then
    echo "game server startup error!"
    exit 1
fi

if [ ! -e "proxyserver.pid" ]; then
    echo "Running proxy server..."
    ./proxyserver.py
    if [[ $? != 0 ]]; then
        echo "proxyserver startup error!"
        exit 1
    fi
fi
