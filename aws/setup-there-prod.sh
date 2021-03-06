#!/bin/sh

GAME_ID=$1
GAME_ID_LONG=$2

YUMPACKAGES="git munin-node nscd patch pinentry screen sendmail-cf strace subversion xfsprogs"
YUMPACKAGES+=" libffi libffi-devel libxml2 libxml2-devel"
YUMPACKAGES+=" gcc gcc-c++ autoconf automake libtool"
YUMPACKAGES+=" postgresql postgresql-devel python-psycopg2" # note: Postgres client + python libs only
YUMPACKAGES+=" mongodb-org-shell mongodb-org-tools" # note: client only
YUMPACKAGES+=" java-1.8.0-openjdk-headless" # Google Closure Compiler now requires at least Java 7
YUMPACKAGES+=" python27-devel python27-pip"
YUMPACKAGES+=" python27-boto python27-imaging python27-imaging-devel python27-numpy python27-simplejson"
YUMPACKAGES+=" openssl-devel" # to compile some Python packages

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

sudo chkconfig munin-node on
#sudo chkconfig mysqld on
sudo chkconfig --add nscd
sudo chkconfig nscd on
sudo /etc/init.d/nscd start

echo "SETUP(remote): Creating /etc/spinpunch config file..."
echo "GAME_ID=${GAME_ID}" > /tmp/spinpunch
echo "GAME_ID_LONG=${GAME_ID_LONG}" >> /tmp/spinpunch
echo "GAME_DIR=/home/ec2-user/${GAME_ID_LONG}" >> /tmp/spinpunch
echo "GAME_MAIL_FROM=Alina" >> /tmp/spinpunch
sudo mv /tmp/spinpunch /etc/spinpunch
sudo chmod 0644 /etc/spinpunch

echo "SETUP(remote): Adjusting users, groups, and permissions..."

#echo "SETUP(remote): Creating EBS volume mount points.."
#sudo mkdir -p /storage/${GAME_ID}prod-logs1

#sudo mkdir -p /media/ephemeral{0,1,2,3}
#sudo mkdir -p /media/ephemeral0/mysql
#sudo chown mysql:mysql /media/ephemeral0/mysql

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && sudo tar zxvf /home/ec2-user/overlay-prod.tar.gz)

# fix permissions
sudo chown -R root:root /etc
sudo chmod 0755 / /etc /etc/mail /etc/ssh /etc/security /etc/sysconfig
sudo chmod 0644 /etc/security/limits.conf /etc/aliases /etc/sysctl.conf
sudo chmod 0775 /etc/rc.d/rc.local
sudo chmod 0440 /etc/sudoers
sudo mkdir -p /etc/pki/tls/private
sudo chmod 0600 /etc/pki/tls/private/*
sudo chmod 0644 /etc/ssh/*
sudo chmod 0600 /etc/ssh/sshd_config /etc/ssh/*_key
sudo chmod 0644 /etc/cron.d/spinpunch
sudo chmod 0755 /etc/cron.spinpunch.*/*

sudo chmod 0700 /home/*
sudo sh -c 'chown -R ec2-user:ec2-user /home/ec2-user'
sudo sh -c 'chmod 0700 /home/ec2-user/.ssh'
sudo sh -c 'chmod 0600 /home/ec2-user/.ssh/*'
sudo mkdir -p /var/lib/munin/plugin-state
sudo touch /var/lib/munin/plugin-state/iostat-ios.state
sudo chown -R munin:munin /var/lib/munin/plugin-state
sudo chmod -R 0770 /var/lib/munin/plugin-state

sudo newaliases

echo "SETUP(remote): Mounting data EBS volumes..."
sudo mount -a

echo "SETUP(remote): (Re)starting munin-node..."
sudo /etc/init.d/munin-node restart

# allow Python to bind to lower ports (dangerous?)
for P in /usr/bin/python2.6 /usr/bin/python26 /usr/bin/python2.7 /usr/bin/python27; do
    if [ -e $P ]; then
    sudo setcap 'cap_net_bind_service=+ep' $P
    fi
done

echo "SETUP(remote): ${GAME_ID}prod setup done!"

echo "MISSING:"
echo "fstab"
echo "/etc/sysconfig/network hostname and sudo hostname <HOSTNAME>"
echo "fix-ec2-mail.py (requires hostname to be correct)"
echo "set up swap space"
echo "/etc/spinpunch - edit anything that needs changing."
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias; newaliases"
echo "SSL certs, from s3://spinpunch-config/ssl-spinpunch.com-latest.tar.gz"

echo "MISSING: SVN: /home/ec2-user/.ssh/spsvnaccess.pem (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: GIT: /home/ec2-user/.ssh/${GAME_ID}prod.pem (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: GIT: git config --global user.name " # 'Example Deploy'
echo "MISSING: GIT: git config --global user.email " # 'awstech@example.com'

# PYTHON PACKAGES
echo "switch /etc/alternatives/python,pip,python-config to v2.7"
echo "pip install --upgrade pip" # upgrade the upgrader

# optional: install libmaxminddb first for C acceleration from https://github.com/maxmind/libmaxminddb

echo "pip install -r gameserver/requirements.txt"

# note: if this install fails, it might be because of a legacy setuptools configuration that
# uses HTTP instead of HTTPS to access pypi.python.org.

# To fix this, edit /root/.pydistutils.cfg to contain:
# [easy_install]
# index-url = https://pypi.python.org/simple/

# The below command might also help - "distribute" is a deprecated
# package that may impose bad default settings on pip:
# sudo pip uninstall distribute

# Finally, be aware that a Linux distro's python-zope and/or setuptools packages may cause conflicts.

echo "game code checkout. symlink gameserver/logs to an ephemeral storage location (consider using xfs for efficiency with 100k+ small files)."

echo "get keys from spinpunch-config bucket! (use aws to download and gpg to decrypt)"
echo "SSH key /home/ec2-user/.ssh/analytics1.pem for ANALYTICS2 queries."
echo "AWS key /home/ec2-user/.ssh/host-awssecret"
echo "SSL key /home/ec2-user/.ssh/spinpunch.com.key for SSL service."
echo "    key /home/ec2-user/.ssh/hipchat.token for automated messages"
echo "    key /home/ec2-user/.ssh/slack.token (with incoming webhook for game channel) for automated messages"
echo "    key /home/ec2-user/.ssh/mattermost-webhook-url for automated messages"
echo "    key /home/ec2-user/.ssh/dropbox-access-token for tournament winner list uploads"
echo "    key /home/ec2-user/.ssh/google-translate-api-key for PCHECK translation"

echo "apply private patches"

echo "set up config.json"
echo "enable /etc/cron.spinpunch* scripts."

echo "Postgres setup: create user xxprod with password 'PASSWORD'; grant all privileges on schema public to xxprod;"
