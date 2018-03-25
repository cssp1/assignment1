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
    ${var.aws_ec2_iam_role_fragment},
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:ListObjects","s3:GetObject","s3:PutObject"],
      "Resource": ["arn:aws:s3:::${var.backups_bucket}*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:ListObjects","s3:GetObject"],
      "Resource": ["arn:aws:s3:::${var.extra_backups_bucket}*"]
    }
  ]
}
EOF
}

resource "aws_iam_instance_profile" "mongodb" {
    name = "${var.sitename}-mongodb"
    role = "${aws_iam_role.mongodb.name}"
}

# EC2 instance

data "template_file" "my_cloud_init" {
  count = "${var.n_instances}"
  template = "${file("${path.module}/cloud-config.yaml")}"
  vars = {
    spin_maint_hour = "${count.index}"
    spin_maint_weekday= "7"
    # storage mountpoints vary by instance type. i3 instances need /dev/nvme0n1...
    mongodb_device = "${substr(var.mongodb_instance_type,0,1) == "i" ? "/dev/nvme0n1" : "/dev/sdx"}"
    mongodb_backups_bucket = "${var.backups_bucket}"
    mongodb_replica_set_name = "${var.sitename}"
    mongodb_replica_set_serial = "${count.index}"
  }
}

data "template_cloudinit_config" "conf" {
  count = "${var.n_instances}"
  gzip = false
  base64_encode = false
  part {
    content = "${var.aws_cloud_config_head}"
    content_type = "text/cloud-config"
    merge_type = "list(append)+dict(recurse_array)+str()"
  }
  part {
    content = "${data.template_file.my_cloud_init.*.rendered[count.index]}"
    content_type = "text/cloud-config"
    merge_type = "list(append)+dict(recurse_array)+str()"
  }
  part {
    content = "${var.aws_cloud_config_tail}"
    content_type = "text/cloud-config"
    merge_type = "list(append)+dict(recurse_array)+str()"
  }
}

resource "aws_instance" "mongodb" {
  count = "${var.n_instances}"

  # Amazon Linux AMI 2017.03
  # us-east-1 HVM (SSD) EBS-Backed 64-bit
  ami = "${var.ami}"
  # note: HVM Instance Store needs different AMI

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

  lifecycle = {
    ignore_changes = ["ami", "user_data", "tags"] # must manually taint for these changes
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

  user_data = "${data.template_cloudinit_config.conf.*.rendered[count.index]}"
}

resource "cloudflare_record" "cf_mongodb" {
  count = "${var.n_instances}"
  domain = "${var.sitedomain}"
  name = "${var.sitename}-${count.index}"
  value = "${element(aws_instance.mongodb.*.public_dns, count.index)}"
  type = "CNAME"
  proxied = false
}
