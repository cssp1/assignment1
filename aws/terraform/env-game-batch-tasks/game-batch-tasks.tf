terraform {
  backend "s3" {
    bucket = "spinpunch-terraform-state"
    key    = "game-batch-tasks.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}

# pull in company-wide resources
data "terraform_remote_state" "corp" {
  backend = "s3"
  config = {
    bucket = "spinpunch-terraform-state"
    key    = "static.tfstate"
    region = "us-east-1"
    dynamodb_table = "spinpunch-terraform-state-lock"
  }
}

variable "region" { default = "us-east-1" }
variable "sitename" { default = "game-batch-tasks" }
# variable "envkey" {}

data "external" "management_secrets" {
  program = ["envkey-fetch", "${data.terraform_remote_state.corp.outputs.management_envkey}", "--cache"]
}

provider "aws" {
  region = var.region
  version = "~> 2"
}

# note: role for Fargate containers
# plus a service account user for third-party runners e.g. GitHub/CircleCI

resource "aws_iam_role" "game_batch_tasks" {
  name               =  var.sitename
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Effect": "Allow"
    }
  ]
}
EOF
}

resource "aws_iam_user" "game_batch_tasks" {
  name = var.sitename
}

resource "aws_iam_access_key" "game_batch_tasks" {
  user  = aws_iam_user.game_batch_tasks.name
}


# Allow batch tasks to:
# - write to S3

locals {
  game_batch_tasks_iam_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "s3:AbortMultipartUpload",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:ListObjects",
        "s3:ListObjectsV2",
        "s3:ListBucketMultipartUploads",
        "s3:PutObject"
      ],
      "Effect": "Allow",
      "Resource": [
        "arn:aws:s3:::spinpunch-puppet*"
      ]
    },
    {
      "Action": ["sns:Publish"],
      "Effect": "Allow",
      "Resource": [
        "${data.terraform_remote_state.corp.outputs.cron_mail_sns_topic}"
      ]
    },
    {
      "Action": [
        "cloudwatch:PutMetricData",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeInstanceAttribute",
        "ec2:DescribeReservedInstances",
        "ec2:DescribeReservedInstancesListings",
        "ec2:DescribeReservedInstancesOfferings",
        "rds:DescribeDBInstances",
        "rds:DescribeReservedDBInstances",
        "rds:DescribeReservedDBInstancesOfferings"
      ],
      "Effect": "Allow",
      "Resource": "*"
    }
  ]
}
EOF
}

resource "aws_iam_role_policy" "game_batch_tasks" {
  name = var.sitename
  role = aws_iam_role.game_batch_tasks.id
  policy = local.game_batch_tasks_iam_policy
}
resource "aws_iam_user_policy" "game_batch_tasks" {
  name = var.sitename
  user = aws_iam_user.game_batch_tasks.name
  policy = local.game_batch_tasks_iam_policy
}

output "batch_tasks_aws_key_id" { value = aws_iam_access_key.game_batch_tasks.id }
output "batch_tasks_aws_key_secret" { value = aws_iam_access_key.game_batch_tasks.secret }
