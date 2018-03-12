resource "aws_alb" "game_alb" {
  name = "${var.sitename}-game-alb"
  security_groups = ["${data.terraform_remote_state.corp.spinpunch_prod_fe_elb_security_group_id}"]
  subnets = ["${split(",", data.terraform_remote_state.corp.spinpunch_prod_subnet_ids)}"]
  idle_timeout = 600

  tags {
    Name = "${var.sitename}-game-alb"
    Terraform = "true"
    game_id = "ALL"
  }
}

resource "aws_alb_listener" "game_http" {
  load_balancer_arn = "${aws_alb.game_alb.arn}"
  port = "80" # to 80
  protocol = "HTTP"
  default_action {
    target_group_arn = "${aws_alb_target_group.game_haproxy.arn}"
    type = "forward"
  }
}
resource "aws_alb_listener" "game_https" {
  load_balancer_arn = "${aws_alb.game_alb.arn}"
  port = "443" # to 80
  protocol = "HTTPS"
  ssl_policy = "ELBSecurityPolicy-2016-08"
  certificate_arn = "${data.terraform_remote_state.corp.spinpunch_ssl_certificate_id}"
  default_action {
    target_group_arn = "${aws_alb_target_group.game_haproxy.arn}"
    type = "forward"
  }
}

resource "aws_alb_target_group" "game_haproxy" {
  name = "${var.sitename}-game-haproxy"
  port = 80
  protocol = "HTTP"
  vpc_id = "${data.terraform_remote_state.corp.spinpunch_vpc_id}"
  deregistration_delay = 600

  stickiness {
    type = "lb_cookie"
    cookie_duration = 600
    enabled = false
  }

  health_check {
    healthy_threshold = 2
    unhealthy_threshold = 2
    timeout = 5
    protocol = "HTTP"
    interval = 30
    path = "/PING"
  }

  tags {
    Name = "${var.sitename}-game-haproxy"
    Terraform = "True"
    game_id = "ALL"
  }
}

resource "aws_alb_target_group_attachment" "game_haproxy_to_game_alb" {
  count = "${var.game_haproxy_n_instances}"
  target_group_arn = "${aws_alb_target_group.game_haproxy.arn}"
  target_id = "${module.game_haproxy.instance_id_list[count.index]}"
  port = 80
  lifecycle {
    ignore_changes = ["target_id"] # manually taint to avoid destruction when count changes
  }
}
