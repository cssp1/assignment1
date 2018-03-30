module "ipranges" {
  source = "./modules/ipranges"
  vpc_id = "${data.terraform_remote_state.corp.spinpunch_vpc_id}"
  sitename = "${var.sitename}"
}
