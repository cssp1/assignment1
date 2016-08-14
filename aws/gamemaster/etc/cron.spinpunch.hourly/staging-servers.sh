#!/bin/bash

declare -A test_regions
test_regions[ransomerrift]=test256
test_regions[thudrunner]=sector201
test_regions[piratewarmers]=kasei101
test_regions[flavorysoda]=sector200
test_regions[tablettransform]=sector200
test_regions[rummagestones]=map101
test_regions[refitskier]=sector200
export PYTHONPATH="/home/ec2-user/twisted-13.2.0/lib64/python:$PYTHONPATH"

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

