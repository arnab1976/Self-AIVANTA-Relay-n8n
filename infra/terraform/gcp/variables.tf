variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "asia-south1"
}
variable "environment" {
  type    = string
  default = "staging"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod"
  }
}
variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}
variable "vpc_network" {
  type        = string
  description = "Self link of the VPC used for private Cloud SQL access"
}
variable "image_tag" {
  type    = string
  default = "latest"
}
variable "retention_days" {
  type    = number
  default = 730
}

variable "n8n_version" {
  type    = string
  default = "2.45.7"
}
variable "n8n_internal_url" {
  type        = string
  description = "Internal URL of the n8n main service (resume URLs and webhooks are built from it), e.g. https://aivanta-relay-prod-n8n-xxxx.a.run.app/"
}
variable "n8n_editor_url" {
  type        = string
  description = "URL of the n8n editor for the platform team (behind IAP)"
}
variable "n8n_workers_min" {
  type    = number
  default = 1
}
variable "n8n_workers_max" {
  type    = number
  default = 6
}
variable "api_internal_url" {
  type        = string
  description = "Internal URL n8n uses to call the AIVANTA bridge (/internal/n8n) and model gateway (/gateway/v1)"
}
