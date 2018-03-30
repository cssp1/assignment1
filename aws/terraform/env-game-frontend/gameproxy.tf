terraform {
  backend "s3" {
    bucket = "spinpunch-terraform-state"
    key    = "game-frontend.tfstate"
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
variable "sitename" { default = "prod" }
variable "sitedomain" { default = "spinpunch.com" }
variable "enable_backups" { default = "0" }
variable "game_haproxy_n_instances" { default = 2 }
variable "envkey" {}


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
  puppet_branch = "master"
}

# HAproxy instances between ELB/CloudFlare and game servers
module "game_haproxy" {
  source = "../modules/game-haproxy"

  vpc_id = "${data.terraform_remote_state.corp.spinpunch_vpc_id}"
  subnet_ids = "${data.terraform_remote_state.corp.spinpunch_prod_subnet_ids}"
  availability_zones = "${data.terraform_remote_state.corp.spinpunch_prod_availability_zones}"
  sitename = "${var.sitename}"
  sitedomain = "${var.sitedomain}"
  region = "${var.region}"
  ami = "${module.aws_cloud_init.current_amazon_linux_ami_id}"
  key_pair_name = "${data.external.management_secrets.result["SSH_KEYPAIR_NAME"]}"
  aws_cloud_config_head = "${module.aws_cloud_init.cloud_config_head}"
  aws_cloud_config_tail = "${module.aws_cloud_init.cloud_config_tail}"
  aws_ec2_iam_role_fragment = "${module.aws_cloud_init.ec2_iam_role_fragment}"
  cron_mail_sns_topic = "${data.terraform_remote_state.corp.cron_mail_sns_topic}"
  instance_type = "t2.micro"
  n_instances = "${var.game_haproxy_n_instances}"
  security_group_id_list = [
    "${data.terraform_remote_state.corp.spinpunch_prod_game_haproxy_security_group_id}",
    "${module.ipranges.cloudflare_ingress_security_group_id}",
    "${module.ipranges.cloudfront_ingress_security_group_id}",
    "${data.terraform_remote_state.corp.spinpunch_ssh_access_security_group_id}"
  ]
}
