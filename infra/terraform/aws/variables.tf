variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "environment" {
  type    = string
  default = "staging"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod"
  }
}
variable "account_suffix" {
  type        = string
  description = "Short unique suffix for globally unique names (e.g. the last 6 digits of the account id)"
}
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids" { type = list(string) }
variable "certificate_arn" {
  type        = string
  description = "ACM certificate for the public ALB"
}
variable "web_origin" {
  type        = string
  description = "Public origin of the web app, e.g. https://relay.example.com"
}
variable "n8n_editor_url" {
  type        = string
  description = "Where the platform team reaches the n8n editor (VPN / Verified Access); never public"
}
variable "image_tag" {
  type    = string
  default = "1.0.0"
}
variable "n8n_version" {
  type    = string
  default = "2.45.7"
}
variable "n8n_workers" {
  type    = number
  default = 2
}
variable "db_instance_class" {
  type    = string
  default = "db.t4g.large"
}
variable "llm_provider" {
  type    = string
  default = "azure_openai"
}
variable "oidc_issuer" { type = string }
variable "oidc_audience" { type = string }
variable "oidc_jwks_url" { type = string }
