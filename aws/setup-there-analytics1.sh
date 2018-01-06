#!/bin/sh

YUMPACKAGES="git munin-node nscd patch pinentry screen strace subversion xfsprogs"
YUMPACKAGES+=" libffi libffi-devel libxml2 libxml2-devel openssl-devel"
YUMPACKAGES+=" gcc autoconf automake libtool"
YUMPACKAGES+=" postgresql postgresql-devel python-psycopg2" # note: Postgres client + python libs only
YUMPACKAGES+=" mysql MySQL-python27" # note: MySQL client + python libs only
YUMPACKAGES+=" mongodb-org mongodb-org-server mongodb-org-shell mongodb-org-tools" # note: full MongoDB server
YUMPACKAGES+=" java-1.8.0-openjdk-headless" # Google Closure Compiler now requires at least Java 7
YUMPACKAGES+=" python27-devel python27-pip"
YUMPACKAGES+=" python27-boto python27-imaging python27-imaging-devel python27-numpy python27-simplejson"
YUMPACKAGES+=" libstdc++48" # for TensorFlow

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && sudo tar zxvf /home/ec2-user/overlay-analytics1.tar.gz)

sudo chkconfig munin-node on
sudo chkconfig --add nscd
sudo chkconfig nscd on
sudo /etc/init.d/nscd start

sudo chmod 0777 /etc/init.d
sudo chmod 0755 /etc/init.d/disable-transparent-hugepages
sudo chkconfig --add disable-transparent-hugepages
sudo /etc/init.d/disable-transparent-hugepages start

sudo chkconfig mongod on
sudo chkconfig mysqld off # moved to RDS

# fix permissions
sudo chown -R root:root /etc
sudo chmod 0755 / /etc /etc/ssh /etc/security /etc/sysconfig
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

echo "SETUP(remote): analytics1 setup done!"

echo "/etc/fstab"
echo "/etc/sysconfig/network hostname and sudo hostname <HOSTNAME>"

# PYTHON PACKAGES
echo "follow Python package installation instructions in setup-there-prod.sh"

# optional:
echo "pip install --upgrade https://storage.googleapis.com/tensorflow/linux/cpu/tensorflow-0.5.0-cp27-none-linux_x86_64.whl"

echo "MISSING: SVN: /home/ec2-user/.ssh/spsvnaccess.pem (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: GIT: /home/ec2-user/.ssh/analytics1.pem (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: GIT: git config --global user.name " # 'Example Deploy'
echo "MISSING: GIT: git config --global user.email " # 'awstech@example.com'
echo "MISSING: /home/ec2-user/.ssh/slack.token (with incoming webhook for analytics channel) for automated messages"
echo "MISSING: /home/ec2-user/.ssh/host-awssecret"
echo "MISSING: set up scratch space in /media/aux/tmp for backup script"
echo "MISSING: set up swap space"
echo "MISSING: mysql config for analytics (or RDS - if local, use /usr/bin/mysql_secure_installation to set root password)"
# NOTE! be sure to set new databases to character set utf8 collate utf8_general_ci !
# my.cnf settings: see aws/analytics1/etc/my.cnf

# add analytics1 user:
# grant usage on *.* to 'analytics1'@'%' identified by 'password';
# grant all privileges on $GAME_upcache.* to 'analytics1'@'%';
# grant all privileges on skynet.* to 'analytics1'@'%';

# add chartio user:
# grant usage on *.* to 'chartio'@'%' identified by 'password' require ssl;
# grant select, execute, show view on $GAME_upcache.* to 'chartio'@'%';
# grant select, execute, show view on skynet.* to 'chartio'@'%';

# add ordinary user:
# grant usage on *.* to 'username'@'%' identified by 'password';
# grant select, insert, drop, alter, create temporary tables, lock tables, execute, create view, show view on $GAME_upcache.* to 'username'@'%';
# grant select, insert, drop, alter, create temporary tables, lock tables, execute, create view, show view on skynet.* to 'username'@'%';

echo "MISSING: see setup-there-mongo.sh for MongoDB setup instructions"
