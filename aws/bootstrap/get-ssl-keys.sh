#!/bin/bash

# Runs on the host, OUTSIDE the Docker container, to retrieve keys and put them in a volume the container can see
# requires AWS CLI tools

if [ ! "$1" ]; then
    echo "usage: $0 dir-to-store-the-keys"
    exit 1
fi

if [ ! $TMPDIR ]; then
    TMPDIR="/tmp"
fi

LOC="$1" # where to put the keys
BUCKET="spinpunch-config"
DOMAIN="spinpunch.com"
ARCHIVE="ssl-${DOMAIN}-latest.tar.gz"

mkdir -p "${LOC}" && \
    cd "${TMPDIR}" && \
    aws s3 cp "s3://${BUCKET}/${ARCHIVE}" . > /dev/null && \
    tar zxf ${ARCHIVE} && \
    cp "ssl-${DOMAIN}/private/${DOMAIN}.key" "${LOC}/server.key" && chmod 0600 "${LOC}/server.key" && \
    cp "ssl-${DOMAIN}/certs/${DOMAIN}_and_gd_bundle.crt" "${LOC}/server.crt" && chmod 0644 "${LOC}/server.crt" && \
rm -rf "${TMPDIR}/${ARCHIVE}" "${TMPDIR}/ssl-${DOMAIN}"
