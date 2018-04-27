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
    ${var.aws_ec2_iam_role_fragment},
    { "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::spinpunch-config/analytics1.pem",
                   "arn:aws:s3:::spinpunch-config/spinpunch-auth-users.json",
                   "arn:aws:s3:::spinpunch-config/spinpunch-alert-recipients.json"]
    },
    { "Effect": "Allow",
      "Action": ["sns:Publish"],
      "Resource": ["${var.tournament_winners_sns_topic}"]
    },
    { "Effect": "Allow",
      "Action": ["s3:ListBucket","s3:DeleteObject","s3:GetObject","s3:PutObject"],
      "Resource": ["arn:aws:s3:::spinpunch-prod-userdb*",
                   "arn:aws:s3:::spinpunch-${var.game_id}prod-*",
                   "arn:aws:s3:::spinpunch-logs*",
                   "arn:aws:s3:::spinpunch-upcache*",
                   "arn:aws:s3:::spinpunch-screen-recordings*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": ["arn:aws:s3:::spinpunch-backups/*",
                   "arn:aws:s3:::battlehouse-newsfeed/${var.game_id}-*"]
    },
    { "Effect": "Allow",
      "Action": ["s3:PutObject","s3:GetObject"],
      "Resource": ["arn:aws:s3:::spinpunch-config/config-${var.game_id_long}.json"]
    }
  ]
}
EOF
}

resource "aws_iam_instance_profile" "game_server" {
    name = "${var.sitename}-game-server-${var.game_id}-terraform" # -terraform suffix to distinguish from manual legacy IAM entity
    role = "${aws_iam_role.game_server.name}"
}

# create an IAM user with permanent credentials
# TEMPORARY - until we implement role-based token renewal
# (all we really need is a cron script to download awssecret and SpinS3.reload_key_file())

resource "aws_iam_user" "game_server" {
    name = "${var.sitename}-game-server-${var.game_id}-terraform"
}
resource "aws_iam_access_key" "game_server" {
    user = "${aws_iam_user.game_server.name}"
}
resource "aws_iam_user_policy" "game_server" {
    name = "${var.sitename}-game-server-${var.game_id}-terraform-user"
    user = "${aws_iam_user.game_server.name}"
    # same permissions as the role
    policy = "${aws_iam_role_policy.game_server.policy}"
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
    game_server_snam = "${var.game_server_snam}"
    game_mail_from = "${var.game_mail_from}"
    game_repo = "${var.game_repo}"
    game_branch = "${var.game_branch}"
    tournament_winners_sns_topic = "${var.tournament_winners_sns_topic}"
    tournament_continents = "${var.tournament_continents}"
    pglith_pgsql_endpoint = "${var.pglith_pgsql_endpoint}"
    analytics_mysql_endpoint = "${var.analytics_mysql_endpoint}"
    skynet_mongo_endpoint = "${var.skynet_mongo_endpoint}"
    cgianalytics_hosts = "${var.cgianalytics_hosts}"
    swap_device = "/dev/xvds"
    logs_device = "/dev/xvdl"
    game_server_iam_key_id = "${aws_iam_access_key.game_server.id}"
    game_server_iam_key_secret = "${aws_iam_access_key.game_server.secret}"
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

# CloudWatch alarms
resource "aws_cloudwatch_metric_alarm" "game_server_swap" {
  count = "${var.enable_swap_alarm ? 1 : 0}"
  alarm_name = "${var.sitename}-game-server-${var.game_id}-high-swap" # later -${count.index}
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods = "3"
  metric_name = "SwapUsage"
  namespace = "EC2/Memory"
  dimensions = {
    InstanceId = "${aws_instance.game_server.*.id[count.index]}"
  }
  period = "300"
  statistic = "Average"
  threshold = "10"
  alarm_description = "${var.sitename}-game-server-${var.game_id} High Swap Usage"
  alarm_actions = ["${var.emergency_sns_topic}"]
}
