#!/bin/bash

# Copyright (c) 2015 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Utility for wrangling different SCM systems (SVN and Git, where for
# Git we're putting gamedata for each game title in its own repository).

# This is meant to be run from the top-level "game" directory.

set -e

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
    (cd "$ROOT" && for p in *private/??*.patch; do patch -p1 < $p; done)
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
    (cd "$ROOT" && svn ci -m "$1")
}

# synchronize SVN repository with Git repository by pulling in deltas since last sync
# current sync status is recorded by saving the current Git commit checksum for each sub-repo in a file called "git-sync.txt"
function do_git_sync_svn {
    GITREPO="$2" # path to the root of the git repository we are syncing to
    COMMITMSG=""
    for SYNCFILE in `(cd "$ROOT" && find . -name "git-sync.txt" | sort)`; do
        SUBPATH=`dirname $SYNCFILE`
        OLDREV=`cat $SYNCFILE`
        NEWREV=`(cd "$GITREPO/$SUBPATH" && git rev-parse master)`

        if [ "$NEWREV" != "$OLDREV" ]; then
            echo -n "Old $OLDREV latest $NEWREV $SUBPATH ..."
            ((cd "$GITREPO/$SUBPATH" && git diff "$OLDREV..$NEWREV") | (cd "$ROOT/$SUBPATH" && patch -p1)) && \
                echo $NEWREV > "$SYNCFILE" && \
                echo " patched!"
            COMMITMSG+=`basename $SUBPATH`
            COMMITMSG+=" "
            COMMITMSG+=`(cd "$GITREPO/$SUBPATH" && git log master -n 1 --oneline)` # --no-abbrev-commit
            #COMMITMSG+=$'\n'
#        else
#            echo " no changes."
        fi
    done
    if [ "$COMMITMSG" != "" ]; then
        echo "Commits:"
        echo "$COMMITMSG"
    fi
    if [[ -n `(cd "$ROOT" && svn stat | egrep '^\?' )` ]]; then
        echo "New files added, manual intervention required!"
    else
        svn ci -m "$COMMITMSG"
    fi
}

function do_up_git {
    for dir in $GIT_DIRS; do
        if (cd $dir && git diff --exit-code --quiet); then
            # tree is clean - plain pull
            echo "pulling game-${dir}..."
            (cd $dir && git pull)
        else
            # local changes - try to reapply on top
            echo "fetching, stashing, merging, unstashing game-${dir}..."
            (cd $dir && git fetch && git stash && git merge origin/master --ff-only && git stash pop)
        fi
    done
}
function do_force_up_git {
    # same code as do_up_git, but tries to be silent
    for dir in $GIT_DIRS; do
        if (cd $dir && git diff --exit-code --quiet); then
            # tree is clean - plain pull
            (cd $dir && git pull -q)
        else
            # local changes - try to reapply on top
            (cd $dir && git fetch -q && git stash -q && git merge origin/master --ff-only -q && git stash pop -q)
        fi
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
        (cd $dir && git commit -am "$1")
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
                do_commit_git "$2"
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
                do_commit_svn "$2"
                ;;
            git-sync)
                do_git_sync_svn $@
                ;;
            *)
                usage
                ;;
        esac
    fi
fi

exit $?
