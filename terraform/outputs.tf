output "backend_url" {
  description = "Public base URL of the Cloud Run API service."
  value       = google_cloud_run_v2_service.backend.urls[0]
}

output "backend_image_url" {
  description = "Artifact Registry image URL that must be built and pushed before the full apply."
  value       = local.image_url
}

output "frontend_bucket" {
  description = "Bucket receiving the Vite dist/ files."
  value       = google_storage_bucket.frontend.name
}

output "frontend_url" {
  description = "Public URL for the static entry point after dist/ is uploaded."
  value       = "https://storage.googleapis.com/${google_storage_bucket.frontend.name}/index.html"
}
