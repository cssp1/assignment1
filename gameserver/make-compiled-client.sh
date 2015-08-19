#!/bin/sh

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

(cd ../gameclient && make -f Makefile all)
exit $?
