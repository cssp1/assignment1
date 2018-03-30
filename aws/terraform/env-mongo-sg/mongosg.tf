terraform {
  backend "s3" {
    bucket = "spinpunch-terraform-state"
    key    = "mongo-sg.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}

# pull in company-wide resources
data "terraform_remote_state" "corp" {
  backend = "s3"
  config {
    bucket = "spinpunch-terraform-state"
    key    = "static.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}


variable "region" { default = "us-east-1" }
variable "sitename" { default = "sgprod-mongo" }
variable "sitedomain" { default = "spinpunch.com" }
variable "enable_backups" { default = "1" }
variable "backups_bucket" { default = "spinpunch-mongolith-backups" }
variable "extra_backups_bucket" { default = "spinpunch-backups" }
variable "mongodb_instance_type" { default = "i3.large" }
variable "n_instances" { default =  1 }
variable "envkey" {}

# note: different from BH stack
locals {
  key_pair_name = "sgprod"
  private_key_file = "sgprod.pem"
}

data "external" "management_secrets" {
  program = ["envkey-fetch", "${data.terraform_remote_state.corp.management_envkey}", "--cache"]
}

provider "aws" {
  region = "${var.region}"
  version = "~> 1.8"
}
provider "cloudflare" {
  email = "${data.external.management_secrets.result["CLOUDFLARE_EMAIL"]}"
  token = "${data.external.management_secrets.result["CLOUDFLARE_TOKEN"]}"
  version = "~> 0.1"
}
module "aws_cloud_init" {
  source = "./modules/aws-cloud-init"
  cron_mail_sns_topic = "${data.terraform_remote_state.corp.cron_mail_sns_topic}"
  region = "${var.region}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  enable_backups = "${var.enable_backups}"
  envkey = "${var.envkey}"
  secrets_bucket = "${data.terraform_remote_state.corp.secrets_bucket}"
}

module "mongodb" {
  source = "../modules/mongodb"

  vpc_id = "${data.terraform_remote_state.corp.spinpunch_vpc_id}"
  # for historical reasons, this server was launched with a different subnet choice
  #subnet_ids = "${data.terraform_remote_state.corp.spinpunch_prod_subnet_ids}"
  subnet_ids = "subnet-b3f645c5"
  #availability_zones = "${data.terraform_remote_state.corp.spinpunch_prod_availability_zones}"
  availability_zones = "us-east-1d"
  ami = "${module.aws_cloud_init.current_amazon_linux_ami_id}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  backups_bucket = "${var.backups_bucket}"
  extra_backups_bucket = "${var.extra_backups_bucket}"
  region = "${var.region}"
  key_pair_name = "${local.key_pair_name}" # data.external.management_secrets.result["SSH_KEYPAIR_NAME"]}"
  aws_cloud_config_head = "${module.aws_cloud_init.cloud_config_head}"
  aws_cloud_config_tail = "${module.aws_cloud_init.cloud_config_tail}"
  aws_ec2_iam_role_fragment = "${module.aws_cloud_init.ec2_iam_role_fragment}"
  cron_mail_sns_topic = "${data.terraform_remote_state.corp.cron_mail_sns_topic}"
  ssh_access_security_group_id = "${data.terraform_remote_state.corp.spinpunch_ssh_access_security_group_id}"
  mongodb_instance_type = "${var.mongodb_instance_type}"
  n_instances = "${var.n_instances}"
  mongodb_security_group_id = "${data.terraform_remote_state.corp.spinpunch_prod_mongodb_security_group_id}"
}
