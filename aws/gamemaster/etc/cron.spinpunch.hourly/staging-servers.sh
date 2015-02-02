#!/bin/bash

declare -A test_regions
test_regions[ransomerrift]=test256
test_regions[thudrunner]=sector201
test_regions[piratewarmers]=kasei101
test_regions[flavorysoda]=sector200
test_regions[tablettransform]=sector200
# test_regions[rummagestones]=sector200 # no regions
export PYTHONPATH="/home/ec2-user/twisted-13.2.0/lib64/python:$PYTHONPATH"

# flavorysoda is off now
for GAMEDIR in ransomerrift thudrunner piratewarmers tablettransform rummagestones; do
        # update to latest code
        (cd /home/ec2-user/$GAMEDIR/gameserver && ../scmtool.sh force-up && ./stopserver.sh > /dev/null && rm -f *.pid && ./make-compiled-client.sh && ./runserver.sh > /dev/null )
        # global database maintenance
        (cd /home/ec2-user/$GAMEDIR/gameserver && ./SpinNoSQL.py --maint > /dev/null )
        # region maintenance
    if [ ${test_regions[$GAMEDIR]} ]; then
            (cd /home/ec2-user/$GAMEDIR/gameserver && ./maptool.py ${test_regions[$GAMEDIR]} ALL maint --quiet > /dev/null )
    fi
done
