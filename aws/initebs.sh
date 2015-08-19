#!/bin/sh

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

if [ ! "$#" -eq 2 ]; then
    echo "usage: initebs.sh /dev/xvdX LABEL"
    exit 1
fi
DRIVE=$1
LABEL=$2
echo "formatting $1 as $2..."
fdisk $DRIVE <<EOF
n
p
1


w
EOF

PART="${DRIVE}1"

mkfs.ext4 $PART -L $LABEL
tune2fs -c0 -i0 $PART
