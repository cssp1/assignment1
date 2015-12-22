# common set-up for all EC2 instances
# does the same thing as the old setup-there-common.sh script

include rpmkey

class spin_ec2 {
  Package { allow_virtual => true }

  # fix some permissions
  file {
    '/etc/ssh/ssh_host_key': mode => 0600;
    '/etc/ssh/ssh_host_rsa_key': mode => 0600;
    '/etc/ssh/ssh_host_dsa_key': mode => 0600;
    '/etc/ssh/ssh_host_ecdsa_key': mode => 0600;
    '/etc/ssh/ssh_host_ed25519_key': mode => 0600;
  }

  # install fail2ban to stop SSH brute-force attacks
  package { 'fail2ban': ensure => 'installed' }
  file { '/etc/fail2ban/jail.local':
    content => '[DEFAULT]
bantime = 3600
[ssh-iptables]
action = iptables[name=SSH, port=ssh, protocol=tcp]',
    mode => 0644 }
  service { 'fail2ban': enable=> true, ensure => 'running' }

  # update all packages (???)
  # exec { 'yum_update': command => '/usr/bin/yum update -y' }

  # create "proj" group and add the ec2-user account to it
  group { 'proj': ensure => present, gid => 1007 }
  user { 'ec2-user': groups => ['proj'] }

  # import CentOS 5 public key (in case we need to install non-Amazon RPMs)
  rpmkey { 'E8562897':
    ensure => present,
    source => 'http://mirror.centos.org/centos/RPM-GPG-KEY-CentOS-5' }

  # add mongodb repo address
  rpmkey { '7F0CEB10':
    ensure => present,
    source => 'https://docs.mongodb.org/10gen-gpg-key.asc' }
  yumrepo { 'mongodb.org':
    baseurl => 'http://downloads-distro.mongodb.org/repo/redhat/os/x86_64/',
    enabled => 1,
    gpgcheck => 1,
  }

  # set up ~/.aws/credentials with host's IAM key proper default region
  file { '/root/.aws': ensure=>'directory', owner=>'root', group=>'root', mode=>0700}
  file { '/home/ec2-user/.aws': ensure=>'directory', owner=>'ec2-user', group=>'ec2-user', mode=>0700}
  file { '/root/.aws/credentials': owner=>'root', group=>'root', mode => 0600,
    content => inline_template("[default]
region = <%= scope['::ec2_region'] %>
") }
  file { '/home/ec2-user/.aws/credentials': owner=>'ec2-user', group=>'ec2-user', mode => 0600,
    content => inline_template("[default]
region = <%= scope['::ec2_region'] %>
") }

  # set up cron-to-sns gateway
  package { 'python-boto': ensure => 'installed' }
  file { '/usr/local/bin/cron-mail-to-sns.py': mode => 755, owner=>'root', group=>'root',
    content => file('spin_ec2/cron-mail-to-sns.py')
  }
  file { '/etc/sysconfig/crond': owner=>'root', group=>'root', mode=>0600,
    content => "# send cron errors via SNS instead of system mail
CRONDARGS=\" -m '/usr/local/bin/cron-mail-to-sns.py arn:aws:sns:us-east-1:147976285850:spinpunch-technical'\"
" }
  # install memory-metrics reporting script (may not be enabled, see cron setup)
  file { '/usr/local/bin/ec2-send-memory-metrics.py':  owner=>'root', group=>'root', mode=>0755,
    content => file('spin_ec2/ec2-send-memory-metrics.py') }
}
