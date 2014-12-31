#!/bin/sh

sudo sed -i 's/PermitRootLogin forced-commands-only/PermitRootLogin yes/' /etc/ssh/sshd_config && \
sudo sed -i 's/PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config && \
sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
sudo install -g root -o root /home/ec2-user/.ssh/authorized_keys /root/.ssh/authorized_keys && \
sudo chmod 0700 /root/.ssh && \
sudo sh -c 'chmod 0600 /root/.ssh/*' && \
sudo /etc/init.d/sshd reload


