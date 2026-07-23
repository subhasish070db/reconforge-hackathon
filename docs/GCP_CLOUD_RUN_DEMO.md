# GCP Cloud Run demo deployment

This deployment targets project `hack-team-cortexaugmentors` in `us-central1`.
It is deliberately **demo-only**: Cloud Run is limited to one instance and one
request at a time, while SQLite and uploads live under `/tmp`. Cloud Run can
replace that instance at any time, so all application state may reset. Do not
use this configuration for production records, governance history, or client
uploads.

## Prerequisites

Install and authenticate the Google Cloud CLI, Terraform (1.5+), Docker, and
Node/npm. Select the project:

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project hack-team-cortexaugmentors
```

## 1. Create the Artifact Registry repository

Terraform needs the repository before a container can be pushed, while Cloud
Run needs that image before its service can be created. Bootstrap only the
repository first:

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform/terraform.tfvars and set a long, unique jwt_secret.
terraform -chdir=terraform init
terraform -chdir=terraform apply -target=google_artifact_registry_repository.backend
```

## 2. Build and push the backend image

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
docker build -t us-central1-docker.pkg.dev/hack-team-cortexaugmentors/reconos/reconos-api:v1 ./backend
docker push us-central1-docker.pkg.dev/hack-team-cortexaugmentors/reconos/reconos-api:v1
```

## 3. Create Cloud Run and the frontend bucket

Review the plan, then apply it:

```bash
terraform -chdir=terraform plan
terraform -chdir=terraform apply
```

The service listens on Cloud Run's injected `PORT`; locally it retains port
8000 for Docker Compose compatibility.

## 4. Build and upload the frontend

Build with the API URL Terraform created. Vite reads this variable at build
time; it is not a runtime setting in static files.

```bash
export VITE_API_BASE_URL="$(terraform -chdir=terraform output -raw backend_url)/api"
export VITE_PUBLIC_BASE_PATH="/$(terraform -chdir=terraform output -raw frontend_bucket)/"
npm --prefix frontend run build
gcloud storage rsync --recursive --delete-unmatched-destination-objects frontend/dist gs://"$(terraform -chdir=terraform output -raw frontend_bucket)"
```

Open the `frontend_url` Terraform output. The API is public for this demo and
allows requests originating from `https://storage.googleapis.com`.

## Important limitations

- Cloud Run's filesystem is temporary. Restarting, redeploying, or scaling down
  removes SQLite state and uploaded files.
- GCS static website hosting is intentionally minimal. For a custom HTTPS
  domain, cache controls, and a dedicated frontend origin, place an external
  HTTPS load balancer/CDN in front of the bucket.
- `terraform.tfvars` and all Terraform state are Git-ignored. Use a remote,
  access-controlled Terraform state backend before team or production use.
