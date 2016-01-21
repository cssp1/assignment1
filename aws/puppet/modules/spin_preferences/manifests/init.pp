class spin_preferences {
  File {
    owner => 'ec2-user',
    group => 'ec2-user',
  }

  file  {
    '/home/ec2-user/.bashrc':
      content => file('spin_preferences/.bashrc');
    '/home/ec2-user/.bash_profile':
      content => file('spin_preferences/.bash_profile');
    '/home/ec2-user/.screenrc':
      content => file('spin_preferences/.screenrc');
    '/home/ec2-user/.dir_colors':
      content => file('spin_preferences/.dir_colors');
    '/home/ec2-user/.nanorc':
      content => file('spin_preferences/.nanorc');
    '/home/ec2-user/.nano':
      ensure => directory, recurse => true, purge => true,
      source => 'puppet:///modules/spin_preferences/.nano';
  }
}
