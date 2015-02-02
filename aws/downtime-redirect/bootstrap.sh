#!/bin/bash

# full boostrap for EC2 instance to serve the downtime message

# get security updates
yum update -y

# protect SSH from brute-force
yum install -y fail2ban
cat > /etc/fail2ban/jail.local <<EOF
[DEFAULT]
bantime=3600
[ssh-iptables]
action = iptables[name=SSH, port=ssh, protocol=tcp]
EOF
service fail2ban start

# get SSL keys (requires aws-cli) XXX share with aws/bootstrap/get-ssl-keys.sh
TMPDIR="/tmp"
LOC="/ssl-keys"
ARCHIVE="ssl-spinpunch.com-latest.tar.gz"
mkdir -p "${LOC}" && \
    cd "${TMPDIR}" && \
    aws s3 cp "s3://spinpunch-config/${ARCHIVE}" . > /dev/null && \
    tar zxf ${ARCHIVE} && \
    cp "ssl-spinpunch.com/private/spinpunch.com.key" "${LOC}/server.key" && chmod 0600 "${LOC}/server.key" && \
    cp "ssl-spinpunch.com/certs/spinpunch.com_and_gd_bundle.crt" "${LOC}/server.crt" && chmod 0644 "${LOC}/server.crt" && \
rm -rf "${TMPDIR}/${ARCHIVE}" "${TMPDIR}/ssl-spinpunch.com"

# install docker
yum install -y docker curl
service docker start

# run docker registry (IAM role credentials)
docker run -d --name spinpunch-docker-registry \
       -e SETTINGS_FLAVOR=s3 \
       -e AWS_REGION=us-east-1 \
       -e AWS_BUCKET=spinpunch-docker \
       -e STORAGE_PATH=/registry \
       -p 5000:5000 \
       registry

# wait for registry to become responsive
timeout 60 sh -c 'while ! curl -s localhost:5000 > /dev/null; do sleep 1; done'

# run web service
docker run -d --name sg-server-maintenance-tr-promo \
       -p 80:80 -p 443:443 \
       -v /ssl-keys:/etc/nginx/ssl \
       localhost:5000/sg-server-maintenance-tr-promo
