resource "aws_iam_role" "mongodb" {
  name = "${var.sitename}-mongodb"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{"Action": "sts:AssumeRole", "Principal": {"Service": "ec2.amazonaws.com"}, "Effect": "Allow", "Sid": "" }]
}
EOF
}

resource "aws_iam_role_policy" "mongodb" {
    name = "${var.sitename}-mongodb"
    role = "${aws_iam_role.mongodb.id}"
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
      "Action": ["s3:ListBucket","s3:GetObject","s3:HeadObject","s3:PutObject"],
      "Resource": ["arn:aws:s3:::${var.sitename}-mongodb-backups*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:GetObject","s3:HeadObject"],
      "Resource": ["arn:aws:s3:::${var.extra_sitename}-mongodb-backups*"]
    }
  ]
}
EOF
}

resource "aws_iam_instance_profile" "mongodb" {
    name = "${var.sitename}-mongodb"
    roles = ["${aws_iam_role.mongodb.name}"]
}

# EC2 instance

resource "aws_instance" "mongodb" {
  count = 1

  # Amazon Linux AMI 2016.09.1 
  # HVM EBS-Backed
  ami = "ami-9be6f38c"
  # HVM Instance Store
  # ami = "ami-24e7f233"

  # production: m4.large? t2.large?
  # testing: t2.medium?
  instance_type = "t2.medium"
  associate_public_ip_address = true
  iam_instance_profile = "${aws_iam_instance_profile.mongodb.name}"
  subnet_id = "${var.subnet_id}"
  vpc_security_group_ids = ["${var.mongodb_security_group_id}",
                            "${var.ssh_access_security_group_id}"]
  key_name = "${var.key_pair_name}"
  depends_on = ["aws_iam_role_policy.mongodb"]
  tags = { 
    Name = "${var.sitename}-mongodb-${count.index}"
    spin_role = "prod-mongo"
    Terraform = "true"
  }

  ebs_block_device = {
    device_name = "/dev/sdz"
    volume_type = "io1"
    # BFM 4.4G, TR 66G
    volume_size = 10
    iops = 100
  }

  user_data = <<EOF
${var.cloud_config_boilerplate_rendered}
 - echo "spin_hostname=${var.sitename}-mongodb-${count.index}" >> /etc/facter/facts.d/terraform.txt
 - echo "mongodb_root_password=${var.mongodb_root_password}" >> /etc/facter/facts.d/terraform.txt
 - echo "include spin_mongodb" >> /etc/puppet/main.pp
 - puppet apply /etc/puppet/main.pp
EOF
}