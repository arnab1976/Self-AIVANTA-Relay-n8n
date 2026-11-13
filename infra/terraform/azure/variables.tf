variable "location" {
  type    = string
  default = "centralindia"
}
variable "environment" {
  type    = string
  default = "staging"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging or prod"
  }
}
variable "apps_subnet_id" {
  type        = string
  description = "Subnet (/23 or larger) for the Container Apps environment"
}
variable "postgres_subnet_id" {
  type        = string
  description = "Subnet delegated to Microsoft.DBforPostgreSQL/flexibleServers"
}
variable "postgres_private_dns_zone_id" { type = string }
variable "redis_subnet_id" {
  type    = string
  default = null
}
variable "db_sku" {
  type    = string
  default = "GP_Standard_D2ds_v5"
}
variable "image_tag" {
  type    = string
  default = "1.0.0"
}
variable "n8n_version" {
  type    = string
  default = "2.45.7"
}
variable "n8n_workers_max" {
  type    = number
  default = 6
}
variable "n8n_editor_url" { type = string }
variable "n8n_api_key" {
  type      = string
  sensitive = true
  default   = "set-after-bootstrap"
}
variable "azure_openai_endpoint" { type = string }
variable "azure_openai_api_key" {
  type      = string
  sensitive = true
}
variable "web_origin" { type = string }
variable "oidc_issuer" { type = string }
variable "oidc_audience" { type = string }
variable "oidc_jwks_url" { type = string }
