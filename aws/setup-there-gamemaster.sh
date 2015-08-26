#!/bin/sh

. ./setup-there-common.sh

YUMPACKAGES="git munin-node nscd patch pinentry screen sendmail-cf strace subversion xfsprogs"
YUMPACKAGES+=" libffi libffi-devel libxml2 libxml2-devel"
YUMPACKAGES+=" gcc autoconf automake libtool"
YUMPACKAGES+=" postgresql postgresql-devel python-psycopg2" # note: Postgres client + python libs only
YUMPACKAGES+=" mongodb-org mongodb-org-server mongodb-org-shell mongodb-org-tools" # note: full MongoDB server
YUMPACKAGES+=" java-1.8.0-openjdk-headless" # Google Closure Compiler now requires at least Java 7
YUMPACKAGES+=" python27-devel python27-pip"
YUMPACKAGES+=" python27-boto python27-imaging python27-imaging-devel python27-numpy python27-simplejson"

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

# using Amazon SES to send outgoing email
# (used to) require a ton of dependencies that take forever to build
if false; then
    sudo yum -y -q install postfix
    sudo /usr/sbin/alternatives --set mta /usr/sbin/sendmail.postfix
    sudo chkconfig sendmail off
    sudo newaliases
    sudo chkconfig postfix on
    sudo /sbin/service sendmail stop
    sudo /sbin/service postfix restart

#    sudo yum install perl-CPAN
#    sudo yum groupinstall "Development Tools"
#    sudo yum install openssl-devel
#    export PERL_MM_USE_DEFAULT=1
#    sudo perl -MCPAN -e 'notest install Digest::SHA'
#    sudo perl -MCPAN -e 'notest install URI::Escape'
#    sudo perl -MCPAN -e 'notest install Bundle::LWP'
#    sudo perl -MCPAN -e 'notest install LWP::Protocol::https'
#    sudo perl -MCPAN -e 'notest install MIME::Base64'
#    sudo perl -MCPAN -e 'notest install Crypt::SSLeay'
#    sudo perl -MCPAN -e 'notest install XML::LibXML'

    sudo groupadd -g 1500 -f outgoing-smtp
    sudo useradd -g 1500 -u 1500 outgoing-smtp
    sudo passwd -l outgoing-smtp # this should be set manually
    sudo postmap /etc/postfix/canonical_senders
    sudo postmap /etc/postfix/canonical_recipients
fi

sudo chkconfig mysqld off
sudo chkconfig httpd off

echo "SETUP(remote): Adjusting users, groups, and permissions..."

# WEB
sudo groupadd -g 1502 -f httpwrite
sudo chmod 775 /var/www /var/www/html
sudo chgrp -R httpwrite /var/www/html
sudo chmod +s /var/www/html
sudo usermod -a -G httpwrite ec2-user

# See company Google Site for user account setup (UIDs/groups/etc)

# XXX temporary hack
sudo chmod 777 /var/lib/php/session

echo "SETUP(remote): Creating EBS volume mount points.."
sudo mkdir -p /storage/mfprod-logs /storage/mfprod-game

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && sudo tar zxvf /home/ec2-user/overlay-gamemaster.tar.gz)

# fix permissions
sudo chown root:root /etc/sudoers
sudo chmod 0440 /etc/sudoers
sudo chmod 0700 /home/*
sudo chown -R root:root /etc/postfix /etc/aliases /etc/mail /etc /
sudo chmod 0755 / /etc /etc/mail
sudo sh -c 'chown -R ec2-user:ec2-user /home/ec2-user'
sudo sh -c 'chown -R outgoing-smtp:outgoing-smtp /home/outgoing-smtp'
sudo sh -c 'chown -R spanalytics:spanalytics /home/spanalytics'
sudo chmod 0700 /home/spanalytics/.ssh
sudo sh -c 'chmod 0600 /home/spanalytics/.ssh/*'

echo "SETUP(remote): Mounting data EBS volume..."
sudo mount -a

# allow Python to bind to lower ports (dangerous?)
for P in /usr/bin/python2.6 /usr/bin/python26 /usr/bin/python2.7 /usr/bin/python27; do
    if [ -e $P ]; then
    sudo setcap 'cap_net_bind_service=+ep' $P
    fi
done

echo "SETUP(remote): Fixing mail configuration..."
sudo ./fix-ec2-mail.py

echo "SETUP(remote): gamemaster setup done!"

echo "MISSING:"
echo "fstab"
echo "/etc/sysconfig/network hostname and sudo hostname <HOSTNAME>"
echo "fix-ec2-mail.py (requires hostname to be correct)"
echo "set up swap space"

# PYTHON PACKAGES
echo "switch /etc/alternatives/python,pip,python-config to v2.7"
echo "pip install --upgrade pip" # upgrade the upgrader
echo "pip install --upgrade requests" # this overrides system python-requests package with a newer version of Requests
echo "pip install --upgrade pyOpenSSL service_identity certifi" # override system pyOpenSSL with newer version and add service_identity and certifi
echo "pip install --upgrade pymongo" # note: we now require post-3.0 API
echo "pip install --upgrade psycopg2 txpostgres" # replace system psycopg2 with newer version necessary for txpostgres
echo "pip install --upgrade pyxDamerauLevenshtein"

echo "MISSING: /etc/cron scripts for production. /var/tmp/swap setup. Home dirs in /media/aux"
echo "MISSING: SSL certs, from s3://spinpunch-config/ssl-spinpunch.com.tar.gz.gpg."
echo "MISSING: /home/outgoing-smtp/mailsender-awssecret"
echo "MISSING: (if using Postfix) echo OUTGOING-MAIL-PASSWORD | sudo passwd --stdin outgoing-smtp"
echo "MISSING: (if using Postfix) outgoing address in /etc/postfix/master.cf"
echo "MISSING: (if using Postfix) mail aliases in /etc/postfix/canonical_recipients"
echo "MISSING: /var/svn/slack.token for SVN commit messages"
echo "MISSING: /home/ec2-user/.ssh/spinpunch.com.key for SSL auth"
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias"

