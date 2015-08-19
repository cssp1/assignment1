#!/bin/bash

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

HOST=`hostname | sed 's/.spinpunch.com//'`
AWSSECRET=/home/ec2-user/.ssh/${HOST}-awssecret
TARFILE=${HOST}-keys.tar.gz
ENCFILE=${TARFILE}.gpg

if [ ! -e $AWSSECRET ]; then
    echo "AWS key file ${AWSSECRET} not found"
    exit 1
fi

(cd ~ && chmod 0700 .ssh && chmod 0600 .ssh/* && tar zcvf $TARFILE .ssh && gpg -c $TARFILE)
../aws/aws --secrets-file="${AWSSECRET}" put spinpunch-config/$ENCFILE ~/$ENCFILE && echo "uploaded spinpunch-config/${ENCFILE}"
rm -f ~/$TARFILE ~/$ENCFILE
