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
      "Action": ["s3:ListBucket","s3:ListObjects","s3:GetObject","s3:HeadObject","s3:PutObject"],
      "Resource": ["arn:aws:s3:::${var.backups_bucket}*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:ListObjects","s3:GetObject","s3:HeadObject"],
      "Resource": ["arn:aws:s3:::${var.extra_backups_bucket}*"]
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
  count = "${var.n_instances}"

  # Amazon Linux AMI 2017.03
  # us-east-1 HVM (SSD) EBS-Backed 64-bit
  ami = "ami-c58c1dd3"
  # HVM Instance Store
  # ami = "ami-24e7f233"

  instance_type = "${var.mongodb_instance_type}"
  associate_public_ip_address = true
  iam_instance_profile = "${aws_iam_instance_profile.mongodb.name}"
  subnet_id = "${element(split(",", var.subnet_ids), count.index)}"
  vpc_security_group_ids = ["${var.mongodb_security_group_id}",
                            "${var.ssh_access_security_group_id}"]
  key_name = "${var.key_pair_name}"
  depends_on = ["aws_iam_role_policy.mongodb"]
  tags = { 
    Name = "${var.sitename}-mongodb-${count.index}"
    spin_role = "prod-mongo"
    Terraform = "true"
  }

  # note: data size BFM 4.4G, TR 66G

  # update mongodb_device below with device name!

  # for EBS (test) server
#  ebs_block_device = {
#    device_name = "/dev/sdx"
#    volume_type = "io1"
#    volume_size = 10
#    iops = 100
#  }

  # for i3 servers with NVMe ephemeral device
  # (not necessary - leave disabled?)
#  ephemeral_block_device {
#    device_name = "/dev/nvme0n1"
#    no_device = "true"
#    virtual_name = "ephemeral0"
#  }

  user_data = <<EOF
${var.cloud_config_boilerplate_rendered}
 - echo "spin_hostname=${var.sitename}-mongodb-${count.index}" >> /etc/facter/facts.d/terraform.txt
 - echo "mongodb_device=/dev/nvme0n1" >> /etc/facter/facts.d/terraform.txt
 - echo "mongodb_root_password=${var.mongodb_root_password}" >> /etc/facter/facts.d/terraform.txt
 - echo "mongodb_backups_bucket=${var.backups_bucket}" >> /etc/facter/facts.d/terraform.txt
 - echo "mongodb_replica_set_name=${var.sitename}" >> /etc/facter/facts.d/terraform.txt
 - echo "mongodb_replica_set_serial=${count.index}" >> /etc/facter/facts.d/terraform.txt
 - echo "include spin_mongodb" >> /etc/puppet/main.pp
 - puppet apply /etc/puppet/main.pp
EOF
}

resource "cloudflare_record" "cf_mongodb" {
  count = "${var.n_instances}"
  domain = "${var.sitedomain}"
  name = "${var.sitename}-${count.index}"
  value = "${element(aws_instance.mongodb.*.public_dns, count.index)}"
  type = "CNAME"
  proxied = false
}
