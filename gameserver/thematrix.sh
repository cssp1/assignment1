#!/bin/bash

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# command-line server log monitor
# obsoleted by cgipcheck
# run like this: . ./thematrix.sh 20130819

DATE=$1

CLIENT_FILTER=`python -c 'import SpinLog; print SpinLog.client_exception_filter'`
SERVER_FILTER=`python -c 'import SpinLog; print SpinLog.server_exception_filter'`

(tail -f logs/$DATE-metrics.json | grep --line-buffered 'client_exc' | egrep --line-buffered -v "${CLIENT_FILTER}") &
(tail -n 10000 -f logs/$DATE-exceptions.txt | egrep --line-buffered -v "${SERVER_FILTER}") &
