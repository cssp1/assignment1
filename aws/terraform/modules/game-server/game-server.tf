resource "aws_iam_role" "game_server" {
  name = "${var.sitename}-game-server-${var.game_id}-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{"Action": "sts:AssumeRole", "Principal": {"Service": "ec2.amazonaws.com"}, "Effect": "Allow", "Sid": "" }]
}
EOF
}

resource "aws_iam_role_policy" "game_server" {
    name = "${var.sitename}-game-server-${var.game_id}-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
    role = "${aws_iam_role.game_server.id}"
    policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    ${var.aws_ec2_iam_role_fragment}
  ]
}
EOF
}

resource "aws_iam_instance_profile" "game_server" {
    name = "${var.sitename}-game-server-${var.game_id}-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
    role = "${aws_iam_role.game_server.name}"
}

# EC2 instance

data "template_file" "my_cloud_init" {
  count = "${var.n_instances}"
  template = "${file("${path.module}/cloud-config.yaml")}"
  vars = {
    spin_maint_hour = "${count.index}"
    spin_maint_weekday = "7"
    game_id = "${var.game_id}"
    game_id_long = "${var.game_id_long}"
    game_mail_from = "${var.game_mail_from}"
    game_repo = "${var.game_repo}"
    game_branch = "${var.game_branch}"
    tournament_winners_sns_topic = "${var.tournament_winners_sns_topic}"
    tournament_continents = "${var.tournament_continents}"
    swap_device = "/dev/xvds"
    logs_device = "/dev/xvdl"
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

resource "aws_instance" "game_server" {
  count = "${var.n_instances}"
  ami = "${var.ami}"
  instance_type = "${var.instance_type}"
  associate_public_ip_address = true
  iam_instance_profile = "${aws_iam_instance_profile.game_server.name}"
  subnet_id = "${element(split(",", var.subnet_ids), var.zone_index)}" # later: count.index
  vpc_security_group_ids = ["${var.security_group_id_list}"]
  key_name = "${var.key_pair_name}"
  depends_on = ["aws_iam_role_policy.game_server"]
  tags = { 
    Name = "${var.sitename}-game-server-${var.game_id}" # later: -${count.index}"
    spin_role = "prod"
    Terraform = "true"
    game_id = "${var.game_id}"
  }

  lifecycle = {
    create_before_destroy = true
    ignore_changes = ["ami", "user_data", "tags", "key_name"] # must manually taint for these changes
  }

  user_data = "${data.template_cloudinit_config.conf.*.rendered[count.index]}"
}

# EBS volume for logs
resource "aws_ebs_volume" "logs" {
  count = "${var.n_instances}"
  availability_zone =  "${element(split(",", var.availability_zones), var.zone_index)}" # later: count.index
  size = "${var.logs_size_gb}"
  iops = 100
  type = "gp2"
  tags = {
    Name = "${var.sitename}-game-server-${var.game_id}-logs" # later -${count.index}
    Terraform = "true"
    game_id = "${var.game_id}"
  }
}
resource "aws_volume_attachment" "logs" {
  count = "${var.n_instances}"
  volume_id = "${aws_ebs_volume.logs.*.id[count.index]}"
  instance_id = "${aws_instance.game_server.*.id[count.index]}"
  device_name = "/dev/xvdl"
}

# EBS volume for swap
resource "aws_ebs_volume" "swap" {
  count = "${var.n_instances}"
  availability_zone =  "${element(split(",", var.availability_zones), var.zone_index)}" # later: count.index
  size = "${var.swap_size_gb}"
  iops = 100
  type = "gp2"
  tags = {
    Name = "${var.sitename}-game-server-${var.game_id}-swap" # later -${count.index}
    Terraform = "true"
    game_id = "${var.game_id}"
  }
}
resource "aws_volume_attachment" "swap" {
  count = "${var.n_instances}"
  volume_id = "${aws_ebs_volume.swap.*.id[count.index]}"
  instance_id = "${aws_instance.game_server.*.id[count.index]}"
  device_name = "/dev/xvds"
}
