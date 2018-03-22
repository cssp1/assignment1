#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

set -e

# Utility for setting up a checkout of the game.

function do_init_git {
    # For a git checkout, you'll get a set of parallel directories:
    # $ROOT (game checkout)
    # $ROOT-gamedata-$TITLE (per-title gamedata checkout)
    # $ROOT-spinpunch-private (private checkout)
    ROOT="$1"
    PREFIX=`basename "$ROOT"`
    TOPDIR=`dirname "$ROOT"` # parent directory for "sister" checkouts
    TITLES="$2" # e.g. 'mf,tr'
    if [ "$TITLES" == "ALL" ]; then
        TITLES="mf,tr,mf2,bfm,dv,sg,fs"
    fi

    #REPO="https://github.com/spinpunch" # requires interactive password input
    REPO="git@github.com:spinpunch" # note: requires ~/.ssh/config setup

    if [ ! -e "${TOPDIR}/${PREFIX}/.git" ]; then
        echo "Cloning game -> ${TOPDIR}/${PREFIX}..."
        (cd "$TOPDIR" && git clone "${REPO}/game.git" "$PREFIX")
    fi
    if [ ! -e "${TOPDIR}/${PREFIX}-spinpunch-private/.git" ]; then
        echo "Cloning game-spinpunch-private -> ${TOPDIR}/${PREFIX}-spinpunch-private..."
        (cd "$TOPDIR" && git clone "${REPO}/game-spinpunch-private.git" "${PREFIX}-spinpunch-private")
    fi
    # set up symlink
    if [ ! -e "${TOPDIR}/${PREFIX}/spinpunch-private" ]; then
        echo "Symlinking ${TOPDIR}/${PREFIX}-spinpunch-private -> ${TOPDIR}/${PREFIX}/spinpunch-private..."
        (cd "${TOPDIR}/${PREFIX}" && ln -s "../${PREFIX}-spinpunch-private" "spinpunch-private")
    fi
    # substitute comma for newline
    for TITLE in `echo $TITLES | tr , '\n' | grep -v gg`; do # gg is part of the main gamedata
        if [ ! -e "${TOPDIR}/${PREFIX}-gamedata-${TITLE}/.git" ]; then
            echo "Cloning game-gamedata-${TITLE} -> ${TOPDIR}/${PREFIX}-gamedata-${TITLE}..."
            (cd "$TOPDIR" && git clone "${REPO}/game-gamedata-${TITLE}.git" "${PREFIX}-gamedata-${TITLE}")
        fi
        if [ ! -e "${TOPDIR}/${PREFIX}/gamedata/${TITLE}" ]; then
            echo "Symliking ${TOPDIR}/${PREFIX}-gamedata-${TITLE} -> ${TOPDIR}/${PREFIX}/gamedata/${TITLE}..."
            (cd "${TOPDIR}/${PREFIX}/gamedata" && ln -s "../../${PREFIX}-gamedata-${TITLE}" "$TITLE")
        fi
    done
}

if [ $# != 3 ]; then
    # default settings
    SCM="git"
    ROOT="${PWD}/game"
    TITLES="ALL"
else
    SCM="$1"
    ROOT="$2"
    TITLES="$3" # e.g. "mf,tr,..."
fi

if [ "$SCM" == "git" ]; then
    do_init_git "$ROOT" "$TITLES"
else
    echo "only SCM=git is supported now"
    exit 1
fi

# set up dummy art_auto.json, for "headless" trees that don't need the art pack
if [ ! -e "${ROOT}/gameclient/art" ]; then
    mkdir -p "${ROOT}/gameclient/art"
fi
if [ ! -e "${ROOT}/gameclient/art/art_auto.json" ]; then
    echo '"asdf":"asdf"' > "${ROOT}/gameclient/art/art_auto.json"
fi

exit $?
