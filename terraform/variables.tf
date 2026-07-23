variable "project_id" {
  description = "Google Cloud project that owns the ReconOS demo resources."
  type        = string
  default     = "hack-team-cortexaugmentors"
}

variable "region" {
  description = "Google Cloud region for Artifact Registry and Cloud Run."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "reconos-api"
}

variable "repository_id" {
  description = "Artifact Registry Docker repository name."
  type        = string
  default     = "reconos"
}

variable "image_tag" {
  description = "Immutable container image tag already pushed to Artifact Registry."
  type        = string
  default     = "v1"
}

variable "jwt_secret" {
  description = "Strong JWT signing secret for the demo. Store only in an untracked terraform.tfvars file."
  type        = string
  sensitive   = true
}
