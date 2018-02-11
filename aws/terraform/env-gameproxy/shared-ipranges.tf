
module "ipranges" {
  source = "./modules/ipranges"
  vpc_id = "${var.vpc_id}"
  sitename = "${var.sitename}"
}
