variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "legal-contract-analyzer"
}

variable "image_tag" {
  description = "Container image tag"
  type        = string
  default     = "latest"
}

variable "vpc_id" {
  description = "Existing VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnet IDs for ALB"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS and RDS"
  type        = list(string)
}

variable "db_username" {
  description = "RDS database username"
  type        = string
  default     = "legal_admin"
}

variable "db_password" {
  description = "RDS database password"
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
}

variable "tavily_api_key" {
  description = "Tavily API key"
  type        = string
  sensitive   = true
}

variable "api_auth_token" {
  description = "Optional API auth token for x-api-key middleware"
  type        = string
  sensitive   = true
  default     = ""
}

variable "hf_token" {
  description = "Hugging Face token for Router/Inference APIs"
  type        = string
  sensitive   = true
  default     = ""
}

variable "hf_model" {
  description = "Default Hugging Face model for API runtime"
  type        = string
  default     = "Qwen/Qwen2.5-7B-Instruct"
}

variable "hf_base_url" {
  description = "Hugging Face router base URL"
  type        = string
  default     = "https://router.huggingface.co/v1"
}

variable "db_skip_final_snapshot" {
  description = "Whether to skip final snapshot when deleting RDS"
  type        = bool
  default     = false
}

variable "db_final_snapshot_identifier" {
  description = "Identifier used for final RDS snapshot when deletion occurs"
  type        = string
  default     = "legal-contract-analyzer-postgres-final"
}

variable "db_backup_retention_days" {
  description = "Number of days to retain RDS automated backups"
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Enable deletion protection on RDS"
  type        = bool
  default     = true
}

variable "db_storage_encrypted" {
  description = "Enable storage encryption on RDS"
  type        = bool
  default     = true
}

variable "acm_certificate_arn" {
  description = "Optional ACM certificate ARN to enable HTTPS listener on the ALB"
  type        = string
  default     = ""
}

variable "registry_backend" {
  description = "Backend mode for chat/contract registries: auto, db, or file"
  type        = string
  default     = "auto"
}

variable "artifact_store_backend" {
  description = "Backend mode for uploaded artifact storage: auto, db, or file"
  type        = string
  default     = "auto"
}

variable "vector_artifact_sync_interval_seconds" {
  description = "Refresh interval for syncing local vector state from shared artifact storage"
  type        = number
  default     = 30
}
