#!/bin/bash

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# print populations of all map regions

for REGION in $((for f in $(./get_region_names.py); do echo $f; done) | sort -n); do
        ./maptool.py $REGION ALL count
done
