output "sitename" {
  value = "${var.sitename}"
}
output "raw_public_dns_list" {
  value = ["${aws_instance.game_haproxy.*.public_dns}"]
}
output "raw_private_dns_list" {
  value = ["${aws_instance.game_haproxy.*.private_dns}"]
}
output "n_instances" {
  value = "${var.n_instances}"
}
