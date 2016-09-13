#!/bin/sh

# script that runs on the cloud node

# IAM key for this host, passed by setup-here-*.sh
AWSCRED_KEYID=$1
AWSCRED_SECRET=$2
AWS_CRON_SNS_TOPIC=$3

# stop SSH brute-force attacks
echo "SETUP(remote): Setting up fail2ban..."
sudo yum -y install fail2ban
sudo sh -c '/bin/cat > /etc/fail2ban/jail.local' <<EOF
[DEFAULT]
bantime = 3600
[ssh-iptables]
action = iptables[name=SSH, port=ssh, protocol=tcp]
EOF
sudo chmod 0644 /etc/fail2ban/jail.*
sudo chkconfig fail2ban on
sudo /etc/init.d/fail2ban restart

echo "SETUP(remote): Getting latest package updates..."

sudo yum -y install yum-updatesd
sudo yum -y update

# enable auto-updates
sudo sed -i 's/do_update\s*=\s*no/do_update = yes/' /etc/yum/yum-updatesd.conf
sudo chkconfig yum-updatesd on
sudo /etc/init.d/yum-updatesd restart

echo "SETUP(remote): Setting up common options..."

# create "proj" group and add the ec2-user account to it
sudo groupadd -g 1007 -f proj
sudo usermod -a -G proj ec2-user

# import CentOS 5 public key (in case we need to install non-Amazon RPMs)
sudo rpm --import http://mirror.centos.org/centos/RPM-GPG-KEY-CentOS-5

# import s3cmd tools repo key
sudo rpm --import http://s3tools.org/repo/RHEL_6/repodata/repomd.xml.key

# add s3cmd repo address
sudo sh -c '/bin/cat > /etc/yum.repos.d/s3tools.repo' <<EOF
[s3tools]
name=Tools for managing Amazon S3 - Simple Storage Service (RHEL_6)
type=rpm-md
baseurl=http://s3tools.org/repo/RHEL_6/
gpgcheck=1
gpgkey=http://s3tools.org/repo/RHEL_6/repodata/repomd.xml.key
enabled=1
EOF

# add mongodb repo address
sudo sh -c '/bin/cat > /etc/yum.repos.d/mongodb-org-3.2.repo' <<EOF
[mongodb-org-3.2]
name=MongoDB Repository (3.2)
baseurl=https://repo.mongodb.org/yum/amazon/2013.03/mongodb-org/3.2/x86_64/
gpgcheck=0
enabled=1
EOF

# set up ~/.aws/credentials with host's IAM key proper default region
CUR_REGION=`curl -s http://instance-data/latest/dynamic/instance-identity/document | grep region | awk -F\" '{print $4}'`
for homedir in /root /home/ec2-user; do
    sudo mkdir -p "${homedir}/.aws"
    sudo sh -c "/bin/cat > ${homedir}/.aws/credentials" <<EOF
[default]
region = ${CUR_REGION}
EOF
    if [ ${AWSCRED_KEYID} != "none" ]; then
        sudo sh -c "/bin/cat >> ${homedir}/.aws/credentials" <<EOF
aws_access_key_id = ${AWSCRED_KEYID}
aws_secret_access_key = ${AWSCRED_SECRET}
EOF
    fi
    sudo sh -c "chmod 0700 ${homedir}/.aws"
    sudo sh -c "chmod 0600 ${homedir}/.aws/credentials"
done
sudo chown -R ec2-user:ec2-user /home/ec2-user/.aws

# set up cron-to-sns gateway
sudo yum -y install python27-boto
sudo install ./cron-mail-to-sns.py /usr/local/bin/cron-mail-to-sns.py
sudo sh -c "/bin/cat > /etc/sysconfig/crond" <<EOF
# send cron errors via SNS instead of system mail
CRONDARGS=" -m '/usr/local/bin/cron-mail-to-sns.py ${AWS_CRON_SNS_TOPIC}'"
EOF

# install memory-metrics reporting script (may not be enabled, see cron setup)
sudo install ./ec2-send-memory-metrics.py /usr/local/bin/ec2-send-memory-metrics.py


