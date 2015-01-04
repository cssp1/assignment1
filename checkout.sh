#!/bin/bash

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Utility for setting up a checkout of the game.

function usage {
    echo "Usage: $0 [git|svn] [ROOT] [TITLES]"
    echo "  - initialize a checkout in $ROOT including game titles $TITLES (comma-separated list)"
    return 1
}

function do_init_svn {
    ROOT="$2"
    if [ ! -e "${ROOT}/.svn" ]; then
        (cd `dirname "$ROOT"` && svn co svn+ssh://gamemaster.spinpunch.com/var/svn/game/trunk `basename "$ROOT"`)
    else
        echo "checkout appears to be set up already: ${ROOT}"
    fi
}

function do_init_git {
    # For a git checkout, you'll get a set of parallel directories:
    # $ROOT (game checkout)
    # $ROOT-gamedata-$TITLE (per-title gamedata checkout)
    # $ROOT-spinpunch-private (private checkout)
    ROOT="$2"
    PREFIX=`basename "$ROOT"`
    TOPDIR=`dirname "$ROOT"` # parent directory for "sister" checkouts
    TITLES="$3" # e.g. 'mf,tr'
    if [ "$TITLES" == "ALL" ]; then
        TITLES="mf,tr,mf2,bfm,dv,sg,gg"
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
    usage
else
    SCM="$1"
    if [ "$SCM" == "git" ]; then
        do_init_git $@
    elif [ "$SCM" == "svn" ]; then
        do_init_svn $@
    fi
fi

exit $?
