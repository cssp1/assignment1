#!/bin/bash

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

HOST=`hostname | sed 's/.spinpunch.com//'`
TARFILE="${HOST}-keys.tar.gz"
ENCFILE="${TARFILE}.gpg"
DEST="s3://spinpunch-config/$ENCFILE"

cd ~
chmod 0700 .ssh && chmod 0600 .ssh/* && tar zcvf "$TARFILE" .ssh && gpg -c "$TARFILE" && \
aws s3 cp "$ENCFILE" "$DEST" && echo "uploaded $DEST"
rm -f "$TARFILE" "$ENCFILE"
