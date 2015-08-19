#!/bin/sh

. ./setup-there-common.sh

YUMPACKAGES="xfsprogs httpd mod_ssl telnet mysql-server php php-mysql subversion MySQL-python php-mbstring php-mcrypt"
YUMPACKAGES+=" python-twisted python-simplejson emacs strace"
YUMPACKAGES+=" python-imaging python-imaging-devel numpy"
YUMPACKAGES+=" libxml2 libxml2-devel"
YUMPACKAGES+=" sendmail-cf patch screen"

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

sudo chkconfig mysqld on
sudo chkconfig httpd on

echo "SETUP(remote): Adjusting users, groups, and permissions..."

# WEB
sudo groupadd -g 1502 -f httpwrite
sudo usermod -a -G httpwrite ec2-user
sudo chmod 775 /var/www /var/www/html
sudo chgrp -R httpwrite /var/www/html
sudo chmod +s /var/www/html

# XXX temporary hack
sudo chmod 777 /var/lib/php/session

echo "SETUP(remote): Creating EBS volume mount points.."
sudo mkdir -p /storage/forums

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && sudo tar zxvf /home/ec2-user/overlay-forums.tar.gz)

# fix permissions
sudo chown root:root /etc/sudoers
sudo chmod 0440 /etc/sudoers
sudo chmod 0700 /home/*
sudo chown -R root:root /etc/postfix /etc/aliases /etc/mail /etc /
sudo chmod 0755 / /etc /etc/mail
sudo chmod 0600 /etc/pki/tls/private/*
sudo newaliases

sudo sh -c 'chown -R ec2-user:ec2-user /home/ec2-user'

echo "SETUP(remote): Mounting all volumes..."
sudo mount -a

echo "SETUP(remote): (Re)starting services..."
sudo /etc/init.d/mysqld restart
sudo /etc/init.d/httpd restart

echo "SETUP(remote): Fixing mail configuration..."
sudo ./fix-ec2-mail.py

# allow Python to bind to lower ports (dangerous?)
#sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python2.6

echo "SETUP(remote): forums setup done!"
echo "MISSING: SSL certs, from s3://spinpunch-config/ssl-spinpunch.com.tar.gz.gpg."
echo "MISSING: /home/ec2-user/.ssh/forums-mysql-root-password for backups."
echo "MISSING: /home/ec2-user/.ssh/forums-awssecret for backups."
echo "MISSING: set MySQL passwords on root and forums accounts, and create forums database"
echo "MISSING: ensure public IP is added to SPF record for example.com"
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias"
