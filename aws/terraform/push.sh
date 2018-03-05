#!/bin/bash

TERRAFORM_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
TARFILE="spinpunch-terraform-state.tar.gz"
BUCKET="spinpunch-config"

(cd $TERRAFORM_DIR && \
COPYFILE_DISABLE=1 tar -zcvf "/tmp/${TARFILE}"  --exclude '*.git*' env-*/terraform.{tfstate,tfvars} env-*/envkey.env ) && \
aws s3 cp "/tmp/${TARFILE}" "s3://${BUCKET}/${TARFILE}"
rm -f "/tmp/${TARFILE}"
