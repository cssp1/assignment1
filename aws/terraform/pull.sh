#!/bin/bash

TERRAFORM_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TARFILE="spinpunch-terraform-state.tar.gz"
BUCKET="spinpunch-config"

aws s3 cp "s3://${BUCKET}/${TARFILE}" "/tmp/${TARFILE}" && \
(cd $TERRAFORM_DIR && COPYFILE_DISABLE=1 tar -zxvf "/tmp/${TARFILE}") && \
rm -f "/tmp/${TARFILE}"
