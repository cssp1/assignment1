#!/bin/bash

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# utility for wrangling different SCM systems (SVN and Git, where for
# Git we're putting each game title's gamedata in its own repository).

function usage {
    echo "Usage: $0 <command>"
    echo "Commands include:"
    echo "  help or any other wrong command - print this list"
    echo ""
    echo "  up - get updates from origin"
    echo "  force-up - get updates from origin, resolving merge conflicts by force (for automated tools only)"
    echo "  stat - show modified file list"
    echo "  diff - show differences"
    echo "  commit [MESSAGE] - make a commit"
    echo "  push - (Git only) send commits to origin"
    return 1
}

ROOT=`dirname "${BASH_SOURCE[0]}"`
if [ -e "$ROOT/.git" ]; then
    SCM=git
    GIT_DIRS="$ROOT "
    GIT_DIRS+=`find "$ROOT/gamedata" -type l`
    if [ -e "$ROOT/spinpunch-private" ]; then
        GIT_DIRS+=" $ROOT/spinpunch-private"
    fi
elif [ -e "$ROOT/.svn" ]; then
    SCM=svn
else
    echo "cannot detect SCM system in use"
    exit 1
fi

function do_up_svn {
    (cd "$ROOT" && svn up)
}
function do_force_up_svn {
    (cd "$ROOT" && svn up --force --accept theirs-full)
}
function do_stat_svn {
    (cd "$ROOT" && svn stat)
}
function do_diff_svn {
    (cd "$ROOT" && diff)
}
function do_commit_svn {
    (cd "$ROOT" && svn ci -m "$2")
}

function do_up_git {
    for dir in $GIT_DIRS; do
        echo "pulling game-${dir}..."
        (cd $dir && git pull -q)
    done
}
function do_force_up_git {
    for dir in $GIT_DIRS; do
        (cd $dir && git pull -q) # --ff-only ?
    done
}
function do_stat_git {
    for dir in $GIT_DIRS; do
        (cd $dir && git status -s | sed "s|^|$dir |")
    done
}
function do_diff_git {
    for dir in $GIT_DIRS; do
        # rewrite the +++/--- part of the diff to have the right relative paths
        (cd $dir && git diff | sed "s|--- a/|--- $dir/|" | sed "s|+++ b/|+++ $dir/|")
    done
}
function do_commit_git {
    for dir in $GIT_DIRS; do
        echo "committing game-${dir}..."
        (cd $dir && git commit -a -m "$2")
    done
}
function do_push_git {
    for dir in $GIT_DIRS; do
        echo "pushing game-${dir}..."
        (cd $dir && git push -q)
    done
}

if [ $# == 0 ] || [ "$1" == "help" ] ; then
    usage
else
    if [ $SCM == git ]; then
        case "$1" in
            up)
                do_up_git
                ;;
            force-up)
                do_force_up_git
                ;;
            stat)
                do_stat_git
                ;;
            diff)
                do_diff_git
                ;;
            commit)
                do_commit_git
                ;;
            push)
                do_push_git
                ;;
            *)
                usage
                ;;
        esac
    elif [ $SCM == svn ]; then
        case "$1" in
            up)
                do_up_svn
                ;;
            force-up)
                do_force_up_svn
                ;;
            stat)
                do_stat_svn
                ;;
            diff)
                do_diff_svn
                ;;
            commit)
                do_commit_svn
                ;;
            *)
                usage
                ;;
        esac
    fi
fi

exit $?
