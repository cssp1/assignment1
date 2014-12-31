#!/bin/bash

# Copyright (c) 2014 SpinPunch. All rights reserved.
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

if [ -e ../.svn ]; then
    echo "Running SVN maintenance..."
    svn cleanup ..
fi

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
(cd ../gameclient && google/closure/bin/build/depswriter.py --root_with_prefix='clientcode ../../../clientcode' > generated-deps.js)
(cd ../gameclient && echo "goog.require('SPINPUNCHGAME');" >> generated-deps.js)

# Google Closure compilation is disabled by default, since it takes a long time. Will only be used for obfuscated releases.
# echo "compiling client JavaScript code..."
# (cd ../gameclient && ./make-compiled-client.sh)

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
