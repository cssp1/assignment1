#!/bin/bash

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

GAME_ID=""

while getopts "g:" flag
do
    case $flag in
       g)
        GAME_ID="$OPTARG"
        ;;
    esac
done

if [ ! $GAME_ID ]; then
    echo "Pass -g game_id."
    exit 1
fi

export PYTHONPATH="${PWD}:${PWD}/../gameserver"

POTFILE="${GAME_ID}/localize/${GAME_ID}.pot"
BUILT_GAMEDATA="${GAME_ID}/built/gamedata-${GAME_ID}.json"

echo "Updating master file ${POTFILE} from ${BUILT_GAMEDATA}..."
./localize.py --mode extract --quiet ${BUILT_GAMEDATA} ${POTFILE}
if [[ $? != 0 ]]; then
    exit 1
fi

for MYLOC in `find ${GAME_ID}/localize -name '*.po' | cut -d- -f2 | cut -d. -f1`; do
    POFILE="${GAME_ID}/localize/${GAME_ID}-${MYLOC}.po"
    echo "Updating localization ${POFILE}..."
    msgmerge -v --no-wrap --no-fuzzy-matching ${POFILE} ${POTFILE} > ${POFILE}.new
    if [[ $? != 0 ]]; then
    rm -f ${POFILE}.new
    exit 1
    fi
    mv ${POFILE}.new ${POFILE}
done

echo "done"
