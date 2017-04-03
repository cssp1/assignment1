variable "mongodb_root_password" {}
variable "vpc_id" {}
variable "availability_zones" {}
variable "subnet_ids" {}
variable "ssh_access_security_group_id" {}
variable "mongodb_security_group_id" {}
variable "n_instances" {}
variable "backups_bucket" {}

module "mongodb" {
  source = "../modules/mongodb"

  vpc_id = "${var.vpc_id}"
  subnet_ids = "${var.subnet_ids}"
  availability_zones = "${var.availability_zones}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  backups_bucket = "${var.backups_bucket}"
  extra_backups_bucket = "${var.extra_backups_bucket}"
  region = "${var.region}"
  key_pair_name = "${var.key_pair_name}"
  cloud_config_boilerplate_rendered = "${module.cloud_config.boilerplate_rendered}"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  puppet_s3_bucket = "${var.puppet_s3_bucket}"
  ssh_access_security_group_id = "${var.ssh_access_security_group_id}"
  n_instances = "${var.n_instances}"
  mongodb_root_password = "${var.mongodb_root_password}"
  mongodb_security_group_id = "${var.mongodb_security_group_id}"
}
