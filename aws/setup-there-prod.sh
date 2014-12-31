#!/bin/sh

GAME_ID=$1
GAME_ID_LONG=$2

. ./setup-there-common.sh

YUMPACKAGES="xfsprogs telnet subversion nscd munin-node git"
YUMPACKAGES+=" python-twisted python-simplejson emacs strace"
YUMPACKAGES+=" python-imaging python-imaging-devel numpy"
YUMPACKAGES+=" libxml2 libxml2-devel"
YUMPACKAGES+=" sendmail-cf patch fail2ban screen pinentry"
YUMPACKAGES+=" gcc git autoconf automake libtool"
YUMPACKAGES+=" postgresql postgresql-devel python-psycopg2" # note: client only
YUMPACKAGES+=" mongodb-org-shell mongodb-org-tools" # note: client only

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

sudo chkconfig munin-node on
#sudo chkconfig mysqld on
sudo chkconfig --add nscd
sudo chkconfig nscd on
sudo /etc/init.d/nscd start
sudo chkconfig fail2ban on
sudo /etc/init.d/fail2ban start

echo "SETUP(remote): Creating /etc/spinpunch config file..."
echo "GAME_ID=${GAME_ID}" > /tmp/spinpunch
echo "GAME_ID_LONG=${GAME_ID_LONG}" >> /tmp/spinpunch
echo "GAME_DIR=/home/ec2-user/${GAME_ID_LONG}" >> /tmp/spinpunch
echo "GAME_MAIL_FROM=Alina" >> /tmp/spinpunch
echo "GAME_MAIL_TO= # '[{\"name\":\"asdf\",\"email\":\"asdf@example.com\"},...]'" >> /tmp/spinpunch
sudo mv /tmp/spinpunch /etc/spinpunch
sudo chmod 0644 /etc/spinpunch

echo "SETUP(remote): Adjusting users, groups, and permissions..."

#echo "SETUP(remote): Creating EBS volume mount points.."
#sudo mkdir -p /storage/${GAME_ID}prod-logs1

#sudo mkdir -p /media/ephemeral{0,1,2,3}
#sudo mkdir -p /media/ephemeral0/mysql
#sudo chown mysql:mysql /media/ephemeral0/mysql

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && gunzip -c /home/ec2-user/overlay-prod.cpio.gz | sudo cpio -iuvd -R root:root)

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
sudo chmod 0644 /etc/fail2ban/jail.*
sudo chmod 0700 /home/*
sudo sh -c 'chown -R ec2-user:ec2-user /home/ec2-user'
sudo sh -c 'chmod 0700 /home/ec2-user/.ssh'
sudo sh -c 'chmod 0600 /home/ec2-user/.ssh/*'
sudo mkdir -p /var/lib/munin/plugin-state
sudo touch /var/lib/munin/plugin-state/iostat-ios.state
sudo chown -R munin:munin /var/lib/munin/plugin-state
sudo chmod -R 0770 /var/lib/munin/plugin-state

sudo newaliases

echo "SETUP(remote): Mounting data EBS volume..."
sudo mount -a

echo "SETUP(remote): (Re)starting munin-node..."
sudo /etc/init.d/munin-node restart

# allow Python to bind to lower ports (dangerous?)
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python2.6

echo "SETUP(remote): ${GAME_ID}prod setup done!"

echo "MISSING:"
echo "fstab"
echo "/etc/sysconfig/network hostname and sudo hostname <HOSTNAME>"
echo "fix-ec2-mail.py (requires hostname to be correct)"
echo "set up swap space"
echo "/etc/spinpunch - edit anything that needs changing."
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias"
echo "SSL certs, from s3://spinpunch-config/ssl-spinpunch.com.tar.gz.gpg."

echo "easy_install pymongo requests" # note: this overrides python-requests package with a newer version of Requests
echo "easy_install psycopg2 txpostgres" # note: this overrides system psycopg2 with newer version necessary for txpostgres
echo "easy_install geoip2 - but, install libmaxminddb first for C acceleration from https://github.com/maxmind/libmaxminddb"

echo "MISSING: SVN: /home/ec2-user/.ssh/spsvnaccess.pem (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: GIT: /home/ec2-user/.ssh/${GAME_ID}prod.pem (also .ssh/config with Host/User/IdentityFile)"
echo "MISSING: GIT: git config --global user.name " # 'SpinPunch Deploy'
echo "MISSING: GIT: git config --global user.email " # 'awstech@spinpunch.com'

echo "game code checkout. symlink gameserver/logs to an ephemeral storage location."

echo "get keys from spinpunch-config bucket! (use aws to download and gpg to decrypt)"
echo "SSH key /home/ec2-user/.ssh/analytics1.pem for ANALYTICS2 queries."
echo "AWS key /home/ec2-user/.ssh/host-awssecret"
echo "SSL key /home/ec2-user/.ssh/spinpunch.com.key for SSL service."
echo "    key /home/ec2-user/.ssh/hipchat.token for automated messages"
echo "    key /home/ec2-user/.ssh/slack.token (with incoming webhook for game channel) for automated messages"

echo "build/install ujson, blist, and lz4 libraries. (python setup.py build; sudo python setup.py install)"
echo "Twisted update:"
echo  " download from http://twistedmatrix.com/trac/wiki/Downloads and untar"
echo  " mkdir -p /home/ec2-user/twisted-13.2.0/lib64/python"
echo  " PYTHONPATH=/home/ec2-user/twisted-13.2.0/lib64/python python setup.py install --home=/home/ec2-user/twisted-13.2.0"
echo "copy http.py.twistedX to twisted/web wherever it is installed"
echo 'export PYTHONPATH="$PYTHONPATH:/home/ec2-user/twisted-13.2.0/lib64/python" in ~/.bash_profile'
echo "note: might require manual installation of newer version of zope.interface"

echo "apply private patches"

echo "set up config.json"
echo "enable /etc/cron.spinpunch* scripts."

echo "Postgres setup: create user xxprod with password 'PASSWORD'; grant all privileges on schema public to xxprod;"
