# references to manually-created assets
variable "vpc_id" {}
variable "availability_zones" {}
variable "subnet_ids" {}
variable "ssh_access_security_group_id" {}
variable "game_haproxy_security_group_id" {}
variable "cloudflare_security_group_id" {}
variable "cloudfront_security_group_id" {}
variable "incapsula_security_group_id" {}
variable "game_haproxy_n_instances" {}

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
  cloud_config_boilerplate_rendered = "${module.cloud_config.boilerplate_rendered}"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  puppet_s3_bucket = "${var.puppet_s3_bucket}"
  instance_type = "t2.micro"
  n_instances = "${var.game_haproxy_n_instances}"
  security_group_id_list = [
    "${var.game_haproxy_security_group_id}",
    "${var.cloudflare_security_group_id}",
    "${var.cloudfront_security_group_id}",
    "${var.incapsula_security_group_id}",
    "${var.ssh_access_security_group_id}"
  ]
}
