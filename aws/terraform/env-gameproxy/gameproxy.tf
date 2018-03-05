# references to manually-created assets
variable "vpc_id" {}
variable "availability_zones" {}
variable "subnet_ids" {}
variable "ssh_access_security_group_id" {}
variable "game_haproxy_security_group_id" {}
variable "game_haproxy_n_instances" {}

# HAproxy instances between ELB/CloudFlare and game servers
module "game_haproxy" {
  source = "../modules/game-haproxy"

  vpc_id = "${var.vpc_id}"
  subnet_ids = "${var.subnet_ids}"
  availability_zones = "${var.availability_zones}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  region = "${var.region}"
  ami = "${var.amis[var.region]}"
  key_pair_name = "${var.key_pair_name}"
  aws_cloud_config_head = "${module.aws_cloud_init.cloud_config_head}"
  aws_cloud_config_tail = "${module.aws_cloud_init.cloud_config_tail}"
  aws_ec2_iam_role_fragment = "${module.aws_cloud_init.ec2_iam_role_fragment}"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  instance_type = "t2.micro"
  n_instances = "${var.game_haproxy_n_instances}"
  security_group_id_list = [
    "${var.game_haproxy_security_group_id}",
    "${module.ipranges.cloudflare_ingress_security_group_id}",
    "${module.ipranges.cloudfront_ingress_security_group_id}",
    "${var.ssh_access_security_group_id}"
  ]
}
