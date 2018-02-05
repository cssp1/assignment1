resource "aws_iam_role" "game_haproxy" {
  name = "${var.sitename}-game-haproxy-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{"Action": "sts:AssumeRole", "Principal": {"Service": "ec2.amazonaws.com"}, "Effect": "Allow", "Sid": "" }]
}
EOF
}

resource "aws_iam_role_policy" "game_haproxy" {
    name = "${var.sitename}-game-haproxy-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
    role = "${aws_iam_role.game_haproxy.id}"
    policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": ["${var.cron_mail_sns_topic}"]
    },
    { "Effect": "Allow",
      "Action": ["ec2:DescribeTags"],
      "Resource": ["*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:ListAllMyBuckets"],
      "Resource": ["*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:GetObject","s3:HeadObject"],
      "Resource": ["arn:aws:s3:::${var.puppet_s3_bucket}*"]
    },
    { "Effect": "Allow",
      "Action": ["cloudfront:ListDistributions"],
      "Resource": ["*"]
    }
  ]
}
EOF
}

resource "aws_iam_instance_profile" "game_haproxy" {
    name = "${var.sitename}-game-haproxy-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
    role = "${aws_iam_role.game_haproxy.name}"
}

# EC2 instance

resource "aws_instance" "game_haproxy" {
  count = "${var.n_instances}"
  ami = "${var.ami}"
  instance_type = "${var.instance_type}"
  associate_public_ip_address = true
  iam_instance_profile = "${aws_iam_instance_profile.game_haproxy.name}"
  subnet_id = "${element(split(",", var.subnet_ids), count.index)}"
  vpc_security_group_ids = ["${var.security_group_id_list}"]
  key_name = "${var.key_pair_name}"
  depends_on = ["aws_iam_role_policy.game_haproxy"]
  tags = { 
    Name = "${var.sitename}-game-haproxy-${count.index}"
    spin_role = "prod-haproxy"
    Terraform = "true"
    game_id = "ALL"
  }

  lifecycle = {
    ignore_changes = ["ami", "user_data", "tags"] # must manually taint for these changes
  }

  user_data = <<EOF
${var.cloud_config_boilerplate_rendered}
 - echo "spin_hostname=${var.sitename}-game-haproxy-${count.index}" >> /etc/facter/facts.d/terraform.txt
 - echo "spin_game_id_list=mf,tr,mf2,bfm,sg,dv,fs" >> /etc/facter/facts.d/terraform.txt
 - echo "spin_maint_hour=${count.index}" >> /etc/facter/facts.d/terraform.txt
 - echo "spin_maint_weekday=7" >> /etc/facter/facts.d/terraform.txt
 - echo "haproxy_compile=1" >> /etc/facter/facts.d/terraform.txt
 - echo "include spin_game_haproxy" >> /etc/puppet/main.pp
 - puppet apply /etc/puppet/main.pp --parser=future
EOF
}

