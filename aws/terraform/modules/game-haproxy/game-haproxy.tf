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
    ${var.aws_ec2_iam_role_fragment}
  ]
}
EOF
}

resource "aws_iam_instance_profile" "game_haproxy" {
    name = "${var.sitename}-game-haproxy-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
    role = "${aws_iam_role.game_haproxy.name}"
}

# EC2 instance

data "template_file" "my_cloud_init" {
  count = "${var.n_instances}"
  template = "${file("${path.module}/cloud-config.yaml")}"
  vars = {
    spin_maint_hour = "${count.index}"
    spin_maint_weekday = "7"
    spin_game_id_list = "mf,tr,mf2,bfm,sg,dv,fs"
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
    create_before_destroy = true
    ignore_changes = ["ami", "user_data", "tags", "key_name"] # must manually taint for these changes
  }

  user_data = "${data.template_cloudinit_config.conf.*.rendered[count.index]}"
}
