## BOILERPLATE ##

terraform {
  backend "s3" {
    bucket = "spinpunch-terraform-state"
    key    = "gametest.tfstate"
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
variable "sitename" { default = "gametest" }
variable "sitedomain" { default = "spinpunch.com" }
variable "enable_backups" { default = "0" }
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

## END BOILERPLATE ##

module "game_server" {
  source = "../modules/game-server"

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
  security_group_id_list = [
    "${data.terraform_remote_state.corp.spinpunch_prod_backend_security_group_id}",
#    "${module.ipranges.cloudfront_ingress_security_group_id}",
    "${data.terraform_remote_state.corp.spinpunch_ssh_access_security_group_id}"
  ]
  tournament_winners_sns_topic = "${data.terraform_remote_state.corp.tournament_winners_sns_topic}"

  # specific to each game
  game_id = "sg"
  game_id_long = "summonersgate"
  game_mail_from = "Allandra"
  tournament_continents = "fb ag"
  zone_index = 2 # us-east-1d
  instance_type = "m5.large"
}
