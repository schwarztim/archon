variable "azure_location" {
  description = "Azure region for all resources"
  type        = string
  default     = "eastus"
}

variable "environment" {
  description = "Deployment environment (dev, staging, production)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "production"], var.environment)
    error_message = "Environment must be dev, staging, or production."
  }
}

variable "cluster_name" {
  description = "Name of the AKS cluster"
  type        = string
  default     = "archon"
}

variable "kubernetes_version" {
  description = "Kubernetes version for AKS"
  type        = string
  default     = "1.30"
}

variable "vnet_address_space" {
  description = "Address space for the virtual network"
  type        = string
  default     = "10.0.0.0/16"
}

variable "aks_subnet_cidr" {
  description = "CIDR for AKS subnet"
  type        = string
  default     = "10.0.0.0/20"
}

variable "db_subnet_cidr" {
  description = "CIDR for database subnet"
  type        = string
  default     = "10.0.16.0/24"
}

variable "node_vm_size" {
  description = "VM size for AKS default node pool"
  type        = string
  default     = "Standard_D4s_v5"
}

variable "node_count" {
  description = "Initial node count"
  type        = number
  default     = 3
}

variable "node_min_count" {
  description = "Minimum node count for autoscaler"
  type        = number
  default     = 2
}

variable "node_max_count" {
  description = "Maximum node count for autoscaler"
  type        = number
  default     = 10
}

variable "db_password" {
  description = "Administrator password for PostgreSQL"
  type        = string
  sensitive   = true
}

variable "postgres_sku_name" {
  description = "SKU name for PostgreSQL Flexible Server"
  type        = string
  default     = "GP_Standard_D2s_v3"
}

variable "postgres_storage_mb" {
  description = "Storage in MB for PostgreSQL"
  type        = number
  default     = 65536
}

variable "redis_capacity" {
  description = "Redis cache capacity (0-6 for Basic/Standard, 1-5 for Premium)"
  type        = number
  default     = 1
}

variable "redis_family" {
  description = "Redis cache family (C for Basic/Standard, P for Premium)"
  type        = string
  default     = "C"
}

variable "redis_sku_name" {
  description = "Redis cache SKU (Basic, Standard, Premium)"
  type        = string
  default     = "Standard"
}

variable "api_server_authorized_ip_ranges" {
  description = "Authorized IP ranges for AKS API server access"
  type        = list(string)
  default     = []
}
