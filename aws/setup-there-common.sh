#!/bin/sh

# script that runs on the cloud node

echo "SETUP(remote): Getting latest package updates..."
sudo yum -y update

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
sudo sh -c '/bin/cat > /etc/yum.repos.d/mongodb.repo' <<EOF
[mongodb]
name=MongoDB Repository
baseurl=http://downloads-distro.mongodb.org/repo/redhat/os/x86_64/
gpgcheck=0
enabled=1
EOF
