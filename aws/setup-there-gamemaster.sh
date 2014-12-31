#!/bin/sh

. ./setup-there-common.sh

YUMPACKAGES="xfsprogs telnet subversion MySQL-python"
YUMPACKAGES+=" python-twisted python-simplejson emacs strace"
YUMPACKAGES+=" python-imaging python-imaging-devel numpy"
YUMPACKAGES+=" libxml2 libxml2-devel"
YUMPACKAGES+=" sendmail-cf patch screen fail2ban"
YUMPACKAGES+=" postgresql python-psycopg2" # note: client only

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
sudo chkconfig fail2ban on

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

echo "SETUP(remote): (Re)starting services..."
sudo /etc/init.d/fail2ban restart

# allow Python to bind to lower ports (dangerous?)
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python2.6

echo "SETUP(remote): Fixing mail configuration..."
sudo ./fix-ec2-mail.py

echo "SETUP(remote): gamemaster setup done!"

echo "MISSING: hostname in /etc/sysconfig/network. /etc/cron scripts for production. /var/tmp/swap setup. Home dirs in /media/aux"
echo "MISSING: SSL certs, from s3://spinpunch-config/ssl-spinpunch.com.tar.gz.gpg."
echo "MISSING: /home/outgoing-smtp/mailsender-awssecret"
echo "MISSING: (if using Postfix) echo OUTGOING-MAIL-PASSWORD | sudo passwd --stdin outgoing-smtp"
echo "MISSING: (if using Postfix) outgoing address in /etc/postfix/master.cf"
echo "MISSING: (if using Postfix) mail aliases in /etc/postfix/canonical_recipients"
echo "MISSING: /var/svn/slack.token for SVN commit messages"
echo "MISSING: /home/ec2-user/.ssh/spinpunch.com.key for SSL auth"
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias"
echo "MongoDB and pymongo"
