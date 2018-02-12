#!/bin/bash

# crude mutex - this is not atomic, but should protect against the occasional double-run
LOCKFILE=/tmp/staging-servers.sh.lock
if [ -e ${LOCKFILE} ] && kill -0 `cat ${LOCKFILE}`; then
    echo "another instance of staging-server.sh is already running. Check for stuck processes!"
    exit 1
fi

# make sure the lockfile is removed when we exit and then claim it
trap "rm -f ${LOCKFILE}; exit" INT TERM EXIT
echo $$ > ${LOCKFILE}

declare -A test_regions
test_regions[ransomerrift]=test256
test_regions[thudrunner]=sector201
test_regions[piratewarmers]=kasei101
test_regions[flavorysoda]=sector200
test_regions[tablettransform]=sector200
test_regions[rummagestones]=map101
test_regions[refitskier]=sector200

for GAMEDIR in ransomerrift thudrunner piratewarmers tablettransform rummagestones flavorysoda refitskier; do
    # update to latest code
    (cd /home/ec2-user/$GAMEDIR/gameserver && \
        ../scmtool.sh force-up > /dev/null && \
        ./stopserver.sh > /dev/null && \
        rm -f *.pid)

    # not possible to suppress make-compile-client's routine stderr output, but check completion status
    if ! (cd /home/ec2-user/$GAMEDIR/gameserver && ./make-compiled-client.sh > /dev/null 2>&1); then
    echo "make-compiled-client.sh failed with exit code $?"
    continue
    fi

    (cd /home/ec2-user/$GAMEDIR/gameserver && ./runserver.sh > /dev/null )

    # global database maintenance
    (cd /home/ec2-user/$GAMEDIR/gameserver && ./SpinNoSQL.py --maint > /dev/null )

    # region maintenance
    if [ ${test_regions[$GAMEDIR]} ]; then
        (cd /home/ec2-user/$GAMEDIR/gameserver && ./maptool.py ${test_regions[$GAMEDIR]} ALL maint --quiet > /dev/null )
    fi

done

rm -f ${LOCKFILE}
