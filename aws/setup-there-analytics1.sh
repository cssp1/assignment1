#!/bin/sh

. ./setup-there-common.sh

YUMPACKAGES="nscd xfsprogs subversion"
YUMPACKAGES+=" python-twisted python-simplejson strace"
YUMPACKAGES+=" python-imaging python-imaging-devel numpy"
YUMPACKAGES+=" libxml2 libxml2-devel gcc"
YUMPACKAGES+=" sendmail-cf patch fail2ban screen"
YUMPACKAGES+=" mysql MySQL-python" # note: MySQL server + client + python libs
YUMPACKAGES+=" postgresql python-psycopg2" # note: Postgres client + python libs only

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

sudo chkconfig --add nscd
sudo chkconfig nscd on
sudo /etc/init.d/nscd start
sudo chkconfig fail2ban on
sudo /etc/init.d/fail2ban start

sudo chkconfig mysqld on

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && gunzip -c /home/ec2-user/overlay-analytics1.cpio.gz | sudo cpio -iuvd -R root:root)

echo "SETUP(remote): Installing mongodb from mongodb.org repo..."
sudo yum -y -q install mongodb-org mongodb-org-server mongodb-org-shell mongodb-org-tools # note: MongoDB server + client + python libs (below)

sudo groupadd -g 1013 -f iantien
sudo useradd -g 1013 -u 1013 iantien
sudo passwd -l iantien

sudo groupadd -g 1016 -f sean
sudo useradd -g 1016 -u 1016 sean
sudo passwd -l sean

sudo groupadd -g 1021 -f lindsay
sudo useradd -g 1021 -u 1021 lindsay
sudo usermod -a -G proj lindsay
sudo passwd -l lindsay

sudo groupadd -g 1023 -f doohwanoh
sudo useradd -g 1023 -u 1023 doohwanoh
sudo usermod -a -G proj doohwanoh
sudo passwd -l doohwanoh

sudo groupadd -g 1029 -f eric
sudo useradd -g 1029 -u 1029 eric
sudo usermod -a -G proj eric
sudo passwd -l eric

sudo groupadd -g 1035 -f josh
sudo useradd -g 1035 -u 1035 josh
sudo usermod -a -G proj josh
sudo passwd -l josh

sudo groupadd -g 1036 -f manny
sudo useradd -g 1036 -u 1036 manny
sudo usermod -a -G proj manny
sudo passwd -l manny

sudo groupadd -g 1041 -f harrison
sudo useradd -g 1041 -u 1041 harrison
sudo usermod -a -G proj harrison
sudo passwd -l harrison

sudo groupadd -g 1045 -f jason
sudo useradd -g 1045 -u 1045 jason
sudo usermod -a -G proj jason
sudo passwd -l jason

sudo groupadd -g 1051 -f conrad
sudo useradd -g 1051 -u 1051 conrad
sudo usermod -a -G proj conrad
sudo passwd -l conrad

# fix permissions
sudo chown -R root:root /etc
sudo chmod 0755 / /etc /etc/mail /etc/ssh /etc/security /etc/sysconfig
sudo chmod 0664 /etc/sysctl.conf
sudo chmod 0644 /etc/security/limits.conf
sudo chmod 0775 /etc/rc.d/rc.local
sudo chmod 0440 /etc/sudoers
sudo chmod 0644 /etc/ssh/*
sudo chmod 0600 /etc/ssh/sshd_config /etc/ssh/*_key
sudo chmod 0700 /home/*
sudo chmod 0644 /etc/mf.cnf
sudo sh -c 'chown -R ec2-user:ec2-user /home/ec2-user'
sudo sh -c 'chmod 0700 /home/ec2-user/.ssh'
sudo sh -c 'chmod 0600 /home/ec2-user/.ssh/*'
sudo newaliases

echo "SETUP(remote): Mounting all volumes..."
sudo mount -a

echo "SETUP(remote): Fixing mail configuration..."
sudo ./fix-ec2-mail.py

echo "SETUP(remote): analytics1 setup done!"

echo "MISSING: /etc/fstab, /etc/sysconfig/network hostname"
echo "MISSING: /etc/cron.spinpunch.mysql-daily/99-report-slow-queries.sh email"
echo "MISSING: compile/install ujson library"
echo "MISSING: /home/ec2-user/.ssh/spsvnaccess.pem for svn up (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: /home/ec2-user/.ssh/hipchat.token for reminders"
echo "MISSING: /home/ec2-user/.ssh/slack.token (with incoming webhook for analytics channel) for automated messages"
echo "MISSING: /home/ec2-user/.ssh/host-awssecret"
echo "MISSING: set up scratch space in /media/aux/tmp for backup script"
echo "MISSING: set up swap space"
echo "MISSING: mysql config for analytics (use /usr/bin/mysql_secure_installation to set root password)"
# NOTE! be sure to set new databases to utf8 collate utf8_general_ci !
# my.cnf settings: see aws/analytics1/etc/my.cnf
echo "MISSING: easy_install pymongo - then see setup-there-prod.sh for MongoDB setup instructions"
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias"
