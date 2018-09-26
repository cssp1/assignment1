#!/bin/sh

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Gamedata build script

# This really just sets some environment variables and then invokes make on gamedata/$GAME_ID/Makefile
# (which includes gamedata/Makefile.common to do most of the work).

DO_SNAPSHOT=0
DO_COMPARE=0
DO_VERIFY=1
VERIFY_ARGS=""

PROCESSOR_ARGS=""

# -n flag: do not run verifier
while getopts "nuvrg:scp" flag
do
    case $flag in
        n) # skip the gamedata verifier - used for things like analytics servers
            DO_VERIFY=0
            ;;
        u) # do not report unused art/other files
            VERIFY_ARGS="${VERIFY_ARGS} -u"
            ;;
        v) # turn on verbose warnings in verify.py
            VERIFY_ARGS="${VERIFY_ARGS} -v"
            ;;
        g) # select a different game_id
            GAME_ID="$OPTARG"
            ;;
        r) # omit time-dependent fields from gamedata to make the build 100% repeatable, for testing new changes
            PROCESSOR_ARGS="${PROCESSOR_ARGS} --repeatable"
            ;;
        s) # create snapshot for diffing
            PROCESSOR_ARGS="${PROCESSOR_ARGS} --repeatable"
            DO_SNAPSHOT=1
            ;;
        c) # compare against last snapshot
            PROCESSOR_ARGS="${PROCESSOR_ARGS} --repeatable"
            DO_COMPARE=1
            ;;
        p) # enable profiling messages
            PROCESSOR_ARGS="${PROCESSOR_ARGS} --profile"
            VERIFY_ARGS="${VERIFY_ARGS} --profile"
            ;;
    esac
done

if [ ! $GAME_ID ]; then
    if [ -f config.json ]; then
        # read game_id from config.json
        GAME_ID=`grep '"game_id":' config.json | cut -d\" -f4 | sed 's/test//'`
    else
        echo "cannot determine $GAME_ID. Use -g flag or create config.json"
        exit 1
    fi
fi

PROCESSOR_ARGS="${PROCESSOR_ARGS} --game-id ${GAME_ID}"

export SPIN_GAMESERVER="${PWD}" # for SpinConfig to work correctly when invoked outside of gameserver/ dir
export SPIN_GAMEDATA="${PWD}/../gamedata" # for gamedata Makefiles to work correctly when invoked outside of gameserver/ dir
export SPIN_GAMECLIENT="${PWD}/../gameclient" # for gamedata Makefiles to work correctly when invoked outside of gameserver/ dir
export PYTHONPATH="${SPIN_GAMESERVER}:${SPIN_GAMEDATA}:${PYTHONPATH}" # so that gamedata/*.py can pick up gameserver libraries
export GAME_ID

# find linebreak tool, relative to gamedata directory
if [ -x "${SPIN_GAMEDATA}/linebreak/built/linebreak" ]; then
    LINEBREAK="./linebreak/built/linebreak"
elif (cd "${SPIN_GAMEDATA}/linebreak" && make); then
    echo "Fast linebreak tool built"
    LINEBREAK="./linebreak/built/linebreak"
else
    echo "Fast linebreak tool not found, falling back to linebreak.py."
    LINEBREAK="./linebreak.py"
fi
export LINEBREAK

# get list of localizations to create
PO_FILE_LIST=`find ${SPIN_GAMEDATA}/${GAME_ID}/localize -name '*.po' | sort`
MYTARGETS=""
for PO_FILE in $PO_FILE_LIST; do
    MYLOC=`basename ${PO_FILE} | sed "s/.po$//; s/^${GAME_ID}-//"`
    MYTARGETS="${MYTARGETS} ${GAME_ID}/built/gamedata-${GAME_ID}-${MYLOC}.js"
    MYTARGETS="${MYTARGETS} ${GAME_ID}/built/${GAME_ID}_strings_compiled-${MYLOC}.json"
    MYTARGETS="${MYTARGETS} ${GAME_ID}/built/${GAME_ID}_fb_notifications_compiled-${MYLOC}.json"
done

echo "Compiling gamedata-${GAME_ID}.json..."

# update make dependency info, if deps file is missing
if [ ! -e ${SPIN_GAMEDATA}/$GAME_ID/built/deps ]; then
    echo "    Calculating JSON file dependencies..."
    (cd $SPIN_GAMEDATA && make -f $GAME_ID/Makefile PROCESSOR_ARGS="$PROCESSOR_ARGS" VERIFY_ARGS="$VERIFY_ARGS" dep)
fi

# do everything in one make invocation!
(cd $SPIN_GAMEDATA && make -f $GAME_ID/Makefile PROCESSOR_ARGS="$PROCESSOR_ARGS" DO_VERIFY="$DO_VERIFY" VERIFY_ARGS="$VERIFY_ARGS" -j8 all $MYTARGETS)
if [[ $? != 0 ]]; then
    echo "Error in gamedata! Aborting build."
    exit 1
fi

# NOTE! gamedata.js is no longer exposed to players, instead one of the -locale.js files must be used!
# we generate gamedata.js from gamedata.json ONLY for debugging with ?locale_override=null
# (cd ${SPIN_GAMEDATA} && echo -n "var gamedata = " > "$GAME_ID/built/gamedata-${GAME_ID}.js" && cat "$GAME_ID/built/gamedata-${GAME_ID}.json" >> "$GAME_ID/built/gamedata-${GAME_ID}.js")

# for regression testing:
# make a snapshot comparison based on localized gamedata
SNAPSRC="$GAME_ID/built/gamedata-${GAME_ID}-en_US.json"
SNAPREF="$GAME_ID/built/gamedata-${GAME_ID}-en_US.json.good"
if [[ $DO_SNAPSHOT == 1 ]]; then
    (cd ${SPIN_GAMEDATA} && cp $SNAPSRC $SNAPREF)
    echo "Created snapshot $SNAPREF"
fi
if [[ $DO_COMPARE == 1 ]]; then
    echo "Comparing against snapshot:"
    if ! (cd ${SPIN_GAMEDATA} && diff -sq $SNAPSRC $SNAPREF); then
	(cd ${SPIN_GAMEDATA} && ./diff.py $SNAPSRC $SNAPREF)
    fi
fi
