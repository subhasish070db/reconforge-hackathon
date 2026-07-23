provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  frontend_bucket_name = "${var.project_id}-reconos-frontend"
  frontend_origin      = "https://storage.googleapis.com"
  image_url            = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}/reconos-api:${var.image_tag}"
}

# APIs are managed here so a fresh project does not need console setup.
resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "storage.googleapis.com",
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "backend" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  description   = "ReconOS Cloud Run images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "frontend" {
  project                     = var.project_id
  name                        = local.frontend_bucket_name
  location                    = "US"
  uniform_bucket_level_access = true
  force_destroy               = false

  website {
    main_page_suffix = "index.html"
    not_found_page   = "index.html"
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "frontend_public_read" {
  bucket = google_storage_bucket.frontend.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# Deliberately configured as a disposable demo: SQLite and uploads live in the
# Cloud Run instance filesystem. One instance and one request at a time avoid
# concurrent SQLite writers, but data is lost whenever that instance is replaced.
resource "google_cloud_run_v2_service" "backend" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    max_instance_request_concurrency = 1

    containers {
      image = local.image_url

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      env {
        name  = "DATABASE_URL"
        value = "sqlite+pysqlite:////tmp/reconforge.db"
      }

      env {
        name  = "UPLOAD_DIR"
        value = "/tmp/uploads"
      }

      env {
        name  = "FRONTEND_ORIGIN"
        value = local.frontend_origin
      }

      env {
        name  = "SECRET_KEY"
        value = var.jwt_secret
      }

      env {
        name  = "LLM_PROVIDER"
        value = "stub"
      }
    }
  }

  depends_on = [google_artifact_registry_repository.backend]
}

resource "google_cloud_run_v2_service_iam_member" "backend_public_invoker" {
  project  = google_cloud_run_v2_service.backend.project
  location = google_cloud_run_v2_service.backend.location
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
