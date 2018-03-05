output "sitename" {
  value = "${var.sitename}"
}
output "raw_public_dns_list" {
  value = ["${aws_instance.mongodb.*.public_dns}"]
}
output "raw_private_dns_list" {
  value = ["${aws_instance.mongodb.*.private_dns}"]
}
output "n_instances" {
  value = "${var.n_instances}"
}
