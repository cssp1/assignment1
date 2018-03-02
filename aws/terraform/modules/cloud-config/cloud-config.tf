data "template_file" "cloud_config_boilerplate" {
  template = "${file("${path.module}/cloud-config.txt")}"
  vars = {
    terraform_cron_mail_sns_topic = "${var.cron_mail_sns_topic}"
    sitename = "${var.sitename}"
    sitedomain = "${var.sitedomain}"
    enable_backups = "${var.enable_backups}"
    puppet_s3_bucket = "${var.puppet_s3_bucket}"
    logdna_ingestion_key = "${var.logdna_ingestion_key}"
  }
}
