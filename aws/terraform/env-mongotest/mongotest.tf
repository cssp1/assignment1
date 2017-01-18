variable "mongodb_root_password" {}
variable "vpc_id" {}
variable "subnet_id" {}
variable "availability_zone" {}
variable "ssh_access_security_group_id" {}
variable "mongodb_security_group_id" {}

module "mongodb" {
  source = "../modules/mongodb"

  vpc_id = "${var.vpc_id}"
  subnet_id = "${var.subnet_id}"
  availability_zone = "${var.availability_zone}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  region = "${var.region}"
  key_pair_name = "${var.key_pair_name}"
  cloud_config_boilerplate_rendered = "${module.cloud_config.boilerplate_rendered}"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  puppet_s3_bucket = "${var.puppet_s3_bucket}"
  ssh_access_security_group_id = "${var.ssh_access_security_group_id}"

  mongodb_root_password = "${var.mongodb_root_password}"
  mongodb_security_group_id = "${var.mongodb_security_group_id}"
}
