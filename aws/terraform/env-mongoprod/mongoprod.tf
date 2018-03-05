variable "vpc_id" {}
variable "availability_zones" {}
variable "subnet_ids" {}
variable "ssh_access_security_group_id" {}
variable "mongodb_security_group_id" {}
variable "mongodb_instance_type" {}
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
  ami = "${var.amis[var.region]}"
  key_pair_name = "${var.key_pair_name}"
  aws_cloud_config_head = "${module.aws_cloud_init.cloud_config_head}"
  aws_cloud_config_tail = "${module.aws_cloud_init.cloud_config_tail}"
  aws_ec2_iam_role_fragment = "${module.aws_cloud_init.ec2_iam_role_fragment}"
  cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
  ssh_access_security_group_id = "${var.ssh_access_security_group_id}"
  mongodb_instance_type = "${var.mongodb_instance_type}"
  n_instances = "${var.n_instances}"
  mongodb_security_group_id = "${var.mongodb_security_group_id}"
}
