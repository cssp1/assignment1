#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

ART_SRC="https://s3.amazonaws.com/"
ART_SRC+=`python -c 'import SpinConfig; print SpinConfig.config["artmaster_s3_bucket"]'`
QUIET=0
FORCE_CLEAN=0

while getopts "qf" flag
do
    case $flag in
        q)
            QUIET=1
            ;;
        f)
            FORCE_CLEAN=1
            ;;
     esac
done

if [[ $QUIET == 0 ]]; then echo "Fetching latest art assets from $ART_SRC..."; fi

CURL_OPTIONS=""

if [ -e "../gameclient/art.tar.gz" ]; then
    # check for incomplete (<10MB) art pack downloads, and delete the corrupted file if found
    SIZE=$(wc -c "../gameclient/art.tar.gz" | awk '{print $1}')
    if [ $SIZE -ge 10000000 ]; then
        CURL_OPTIONS+=" -z art.tar.gz"
    else
        echo "art.tar.gz appears to be incomplete or corrupted, deleting..."
        rm -f "../gameclient/art.tar.gz"
    fi
fi

if [[ $QUIET == 1 ]]; then
    CURL_OPTIONS+=" --silent"
fi

(cd ../gameclient && curl $CURL_OPTIONS -O $ART_SRC/art.tar.gz)

if [[ $FORCE_CLEAN == 1 ]]; then
    if [[ $QUIET == 0 ]]; then echo "Clearing art assets..."; fi
    rm -rf ../gameclient/art
fi

if [[ $QUIET == 0 ]]; then echo "Unpacking art assets..."; fi
(cd ../gameclient && tar zxf art.tar.gz)
