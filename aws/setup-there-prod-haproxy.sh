#!/bin/bash

YUMPACKAGES="nscd aws-cli git xfsprogs strace patch screen haproxy"

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

sudo chkconfig nscd on
sudo chkconfig haproxy on

echo "SETUP(remote): Getting instance tags..."

MY_INSTANCE_ID=`curl http://instance-data/latest/meta-data/instance-id`
GAME_ID=`aws ec2 describe-tags --filters "Name=resource-id,Values=${MY_INSTANCE_ID}" "Name=key,Values=game_id" --output=text | cut -f5`

aws configure set preview.cloudfront true
ART_CDN_HOST=`aws cloudfront list-distributions | python -c "
import json, sys
a = json.load(sys.stdin)
print next(x for x in a['DistributionList']['Items'] if any(org['DomainName'].startswith('${GAME_ID}prod') for org in x['Origins']['Items']))['DomainName']"`

echo "SETUP(remote): game_id ${GAME_ID} art_cdn_host ${ART_CDN_HOST}..."

echo "SETUP(remote): Adjusting users, groups, and permissions..."

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && sudo tar zxvf /home/ec2-user/overlay-prod-haproxy.tar.gz)

# fix permissions
sudo chown root:root /etc/sudoers
sudo chmod 0440 /etc/sudoers
sudo chmod 0700 /home/*
sudo chown -R root:root /etc/aliases /etc/mail /etc
sudo chown root:root /
sudo chmod 0755 / /etc /etc/mail
sudo chmod 4755 /usr/bin/sudo
sudo chmod 0600 /etc/pki/tls/private/*
sudo newaliases

sudo sh -c 'chown -R ec2-user:ec2-user /home/ec2-user'

echo "SETUP(remote): Mounting all volumes..."
sudo mount -a

# get latest SSL certs XXX share with aws/bootstrap/get-ssl-keys.sh
TMPDIR="/tmp"
BUCKET="spinpunch-config"
DOMAIN="spinpunch.com"
ARCHIVE="ssl-${DOMAIN}-latest.tar.gz"
cd "${TMPDIR}" && \
    aws s3 cp "s3://${BUCKET}/${ARCHIVE}" . > /dev/null && \
    tar zxf ${ARCHIVE} && \
    sudo install "ssl-${DOMAIN}/private/${DOMAIN}.key" "/etc/pki/tls/private/server.key" && sudo chmod 0600 "/etc/pki/tls/private/server.key" && \
    sudo install "ssl-${DOMAIN}/certs/${DOMAIN}_and_gd_bundle.crt" "/etc/pki/tls/certs/server.crt" && sudo chmod 0644 "/etc/pki/tls/certs/server.crt" && \
    sudo sh -c "cat ssl-${DOMAIN}/certs/${DOMAIN}_and_gd_bundle.crt ssl-${DOMAIN}/private/${DOMAIN}.key > /etc/pki/tls/private/server.pem" && \
    sudo chown haproxy:haproxy "/etc/pki/tls/private/server.pem" && sudo chmod 0600 "/etc/pki/tls/private/server.pem"
rm -rf "${TMPDIR}/${ARCHIVE}" "${TMPDIR}/ssl-${DOMAIN}"

echo "Editing haproxy.cfg..."

HAPROXY_GAME_PORT_ACLS=""
HAPROXY_GAME_BACKEND_SELECTORS=""
HAPROXY_GAME_BACKEND_SERVERS=""
for i in $(seq 0 100); do # set up ports 8001,8003,...,8200 forwarding to 8000,8002,...,8199
    SSL_PORT=$((8000 + $i*2 + 1))
    HTTP_PORT=$((8000 + $i*2))
    HAPROXY_GAME_PORT_ACLS+="    acl port${SSL_PORT} url_reg .+[?&]spin_game_server_port=${SSL_PORT}.*\n"
    HAPROXY_GAME_BACKEND_SELECTORS+="     use_backend game-${HTTP_PORT} if is_forwardable port${SSL_PORT}\n"
    HAPROXY_GAME_BACKEND_SELECTORS+="     use_backend game-ws${HTTP_PORT} if is_websocket port${SSL_PORT}\n"
    STRIPPER=""
#    STRIPPER+="\n    http-request del-header X-Forwarded-Proto"
#    STRIPPER+="\n    http-request add-header X-Forwarded-Proto https"
#    STRIPPER+="\n    http-request del-header X-Forwarded-For"
#    STRIPPER+="\n    option forwardfor       except 127.0.0.0\/8"
    STRIPPER+="\n    reqrep ^(.*?)spin_game_server_port=${SSL_PORT}&(.*) \\\1\\\2" # absorb the & in back if it's first
    STRIPPER+="\n    reqrep ^(.*)&spin_game_server_port=${SSL_PORT}(.*) \\\1\\\2" # strip the & if it's not first
    HAPROXY_GAME_BACKEND_SERVERS+="backend game-${HTTP_PORT}\n    ${STRIPPER}\n    server static ${GAME_ID}prod-raw.spinpunch.com:${HTTP_PORT}\n"
    HAPROXY_GAME_BACKEND_SERVERS+="backend game-ws${HTTP_PORT}\n    ${STRIPPER}\n    timeout server 300s\n    server static ${GAME_ID}prod-raw.spinpunch.com:${HTTP_PORT}\n"
done

sudo perl -pi -e "s/\\\$GAME_PORT_ACLS\\\$/${HAPROXY_GAME_PORT_ACLS}/; s/\\\$GAME_BACKEND_SELECTORS\\\$/${HAPROXY_GAME_BACKEND_SELECTORS}/; s/\\\$GAME_BACKEND_SERVERS\\\$/${HAPROXY_GAME_BACKEND_SERVERS}/; s/\\\$GAME_PROXYSERVER_HOST\\\$/${GAME_ID}prod-raw.spinpunch.com/g; s/\\\$GAME_API_HOST\\\$/${GAME_ID}prod-raw.spinpunch.com/g; s/\\\$ART_CDN_HOST\\\$/${ART_CDN_HOST}/g;" /etc/haproxy/haproxy.cfg

echo "SETUP(remote): (Re)starting services..."
sudo /etc/init.d/nscd restart
sudo /etc/init.d/haproxy restart

echo "MISSING: /etc/sysconfig/network hostname and sudo hostname <HOSTNAME>"
