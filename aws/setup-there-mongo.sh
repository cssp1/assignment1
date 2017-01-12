#!/bin/sh

YUMPACKAGES="git xfsprogs telnet subversion nscd munin-node strace sendmail-cf patch screen python-boto"

echo "SETUP(remote): Installing additional packages..."
sudo yum -y -q install $YUMPACKAGES

sudo chkconfig munin-node on
sudo chkconfig --add nscd
sudo chkconfig nscd on

echo "SETUP(remote): Unpacking filesystem overlay..."
(cd / && sudo tar zxvf /home/ec2-user/overlay-mongo.tar.gz)

sudo chmod 0777 /etc/init.d
sudo chmod 0755 /etc/init.d/disable-transparent-hugepages
sudo chkconfig --add disable-transparent-hugepages
sudo /etc/init.d/disable-transparent-hugepages start

echo "SETUP(remote): Installing mongodb from mongodb.org repo..."
sudo yum -y -q install mongodb-org mongodb-org-server mongodb-org-shell mongodb-org-tools

# NOW disable automatic updates for mongodb, to avoid unexpected restarts
if ! grep -q '^exclude' /etc/yum.conf ; then
    sudo sh -c "echo 'exclude=mongodb*' >> /etc/yum.conf"
fi

# fix permissions
sudo chown -R root:root /etc
sudo chmod 0755 / /etc /etc/mail /etc/ssh /etc/security /etc/sysconfig
sudo chmod 0644 /etc/security/limits.conf /etc/aliases /etc/sysctl.conf
sudo chmod 0775 /etc/rc.d/rc.local
sudo chmod 0440 /etc/sudoers
#sudo chmod 0600 /etc/pki/tls/private/*
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

sudo usermod -a -G mongod ec2-user # so that ec2-user backup script has permission to delete the log files

sudo newaliases

echo "SETUP(remote): (Re)starting services..."
sudo /etc/init.d/nscd start
sudo /etc/init.d/munin-node restart

echo "SETUP(remote): Fixing mail configuration..."
sudo ./fix-ec2-mail.py

echo "SETUP(remote): mongo setup done!"

echo "MISSING:"
echo "/etc/sysconfig/network hostname."
echo "SWAP SPACE - always necessary."
echo "mongodb setup:"
echo "    Partition mongodb filesystems - leave 10% space unpartitioned if SSD"
echo "    REFORMAT mongodb filesystems to ext4"
echo "    create mongodb data directory and chown to mongod:mongod, chmod 2775"
echo "    create temp directory (for backup script) and chmod 777"
echo "    set readahead to 16kb on mongodb filesystems in /etc/udev/rules.d/85-ebs.rules"
# echo 'ACTION=="add", KERNEL=="xvdb", ATTR{bdi/read_ahead_kb}="16"' | sudo tee -a /etc/udev/rules.d/85-ebs.rules
# sudo blockdev --setra 32 /dev/xvdb # yes, 32 blocks means 16kb
echo "    check /etc/mongod.conf and start server (use --quiet)"
# MongoDB 2.4: db.addUser(), MongoDB 2.6: createUser()
echo "    use admin; db.createUser({user:'root',pwd:'PASSWORD',roles:['root','dbAdminAnyDatabase','userAdminAnyDatabase','readWriteAnyDatabase','clusterAdmin']});"
echo "after mongodb is set up: set --quiet flag in /etc/init.d/mongod OPTIONS; sudo chkconfig mongod on"
echo "check fstab"
echo "keys: /home/ec2-user/.ssh"
echo "                     xxprod-mongo-awssecret (backups)"
echo "                     xxprod-mongo-root-password (backups)"
echo "configure /etc/cron.spinpunch.daily/mongo-backup.py backup script (check that SCRATCH_DIR exists!)"
echo "MISSING: /etc/aliases: add 'root: awstech@example.com' mail alias; newaliases"
