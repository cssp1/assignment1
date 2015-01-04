#!/bin/bash

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Utility for wrangling different SCM systems (SVN and Git, where for
# Git we're putting gamedata for each game title in its own repository).

# This is meant to be run from the top-level "game" directory.

function usage {
    echo "Usage: $0 <command>"
    echo "Commands include:"
    echo "  help or any other wrong command - print this list"
    echo ""
    echo "  up - get updates from origin"
    echo "  force-up - get updates from origin, resolving merge conflicts by force (for automated tools only)"
    echo "  revert - revert changes to origin (leaving new untracked files alone)"
    echo "  force-revert - revert changes to origin (deleting new untracked files)"
    echo "  site-patch - apply all patches in the *-private/ directory"
    echo "  version - get current version"
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
function do_revert_svn {
    (cd "$ROOT" && svn revert -R . )
}
function do_force_revert_svn {
    # this is a "forceful" revert that also gets rid of all unrecognized files
    (cd "$ROOT" && svn revert -R . && (svn stat | grep '^\?' | awk '{print $2}' | xargs rm -f) )
}
function do_site_patch {
    (cd "$ROOT" && for p in *private/??*.patch; do patch -p0 < $p; done)
}
function do_force_up_svn {
    (cd "$ROOT" && svn up --force --accept theirs-full)
}
function do_version_svn {
    (cd "$ROOT" && svn info | grep Revision | cut -d' ' -f 2)
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
        (cd $dir && git pull)
    done
}
function do_force_up_git {
    for dir in $GIT_DIRS; do
        (cd $dir && git pull -q) # --ff-only ?
    done
}
function do_revert_git {
    (cd "$ROOT" && git reset --hard HEAD)
}
function do_force_revert_git {
    # this is a "forceful" revert that also gets rid of all unrecognized files
    (cd "$ROOT" && git reset --hard HEAD && git clean -f -d)
}
function do_version_git {
    (cd "$ROOT" && git rev-parse HEAD)
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
        (cd $dir && git push)
    done
}

if [ $# == 0 ] || [ "$1" == "help" ] ; then
    usage
else
    if [ $SCM == git ]; then
        case "$1" in
            up)
                do_up_git $@
                ;;
            force-up)
                do_force_up_git $@
                ;;
            revert)
                do_revert_git $@
                ;;
            force-revert)
                do_force_revert_git $@
                ;;
            site-patch)
                do_site_patch $@
                ;;
            version)
                do_version_git $@
                ;;
            stat)
                do_stat_git $@
                ;;
            diff)
                do_diff_git $@
                ;;
            commit)
                do_commit_git $@
                ;;
            push)
                do_push_git $@
                ;;
            *)
                usage
                ;;
        esac
    elif [ $SCM == svn ]; then
        case "$1" in
            up)
                do_up_svn $@
                ;;
            force-up)
                do_force_up_svn $@
                ;;
            revert)
                do_revert_svn $@
                ;;
            force-revert)
                do_force_revert_svn $@
                ;;
            site-patch)
                do_site_patch $@
                ;;
            version)
                do_version_svn $@
                ;;
            stat)
                do_stat_svn $@
                ;;
            diff)
                do_diff_svn $@
                ;;
            commit)
                do_commit_svn $@
                ;;
            *)
                usage
                ;;
        esac
    fi
fi

exit $?
