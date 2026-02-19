terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    bucket = "archon-terraform-state"
    prefix = "gcp/terraform.tfstate"
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
}

# ---------- Networking ----------

resource "google_compute_network" "main" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "nodes" {
  name          = "${var.cluster_name}-nodes"
  ip_cidr_range = var.nodes_subnet_cidr
  region        = var.gcp_region
  network       = google_compute_network.main.id

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }

  private_ip_google_access = true
}

resource "google_compute_router" "main" {
  name    = "${var.cluster_name}-router"
  region  = var.gcp_region
  network = google_compute_network.main.id
}

resource "google_compute_router_nat" "main" {
  name                               = "${var.cluster_name}-nat"
  router                             = google_compute_router.main.name
  region                             = var.gcp_region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# ---------- GKE Cluster ----------

resource "google_container_cluster" "main" {
  name     = var.cluster_name
  location = var.gcp_region

  network    = google_compute_network.main.id
  subnetwork = google_compute_subnetwork.nodes.id

  # Use separately managed node pool
  remove_default_node_pool = true
  initial_node_count       = 1

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = true
    master_ipv4_cidr_block  = var.master_cidr
  }

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.gcp_project_id}.svc.id.goog"
  }

  master_auth {
    client_certificate_config {
      issue_client_certificate = false
    }
  }

  pod_security_policy_config {
    enabled = true
  }

  deletion_protection = var.environment == "production"
}

resource "google_container_node_pool" "primary" {
  name       = "${var.cluster_name}-primary"
  location   = var.gcp_region
  cluster    = google_container_cluster.main.name
  node_count = var.node_count

  autoscaling {
    min_node_count = var.node_min_count
    max_node_count = var.node_max_count
  }

  node_config {
    machine_type = var.node_machine_type
    disk_size_gb = 50
    disk_type    = "pd-standard"

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    labels = {
      project     = "archon"
      environment = var.environment
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# ---------- Cloud SQL PostgreSQL ----------

resource "google_compute_global_address" "private_ip" {
  name          = "${var.cluster_name}-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.main.id
}

resource "google_service_networking_connection" "private_vpc" {
  network                 = google_compute_network.main.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip.name]
}

resource "google_sql_database_instance" "postgres" {
  name             = "${var.cluster_name}-postgres"
  database_version = "POSTGRES_16"
  region           = var.gcp_region

  depends_on = [google_service_networking_connection.private_vpc]

  settings {
    tier              = var.cloudsql_tier
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"
    disk_size         = var.cloudsql_disk_size
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.main.id
      enable_private_path_for_google_cloud_services = true
      require_ssl                                   = true
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = var.environment == "production"
      transaction_log_retention_days = 7
    }

    database_flags {
      name  = "max_connections"
      value = "200"
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
  }

  deletion_protection = var.environment == "production"
}

resource "google_sql_database" "archon" {
  name     = "archon"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "archon" {
  name     = "archon"
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}

# ---------- Memorystore Redis ----------

resource "google_redis_instance" "main" {
  name           = "${var.cluster_name}-redis"
  tier           = "STANDARD_HA"
  memory_size_gb = var.redis_memory_size_gb
  region         = var.gcp_region

  authorized_network = google_compute_network.main.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  auth_enabled  = true
  redis_version = "REDIS_7_0"
  display_name  = "Archon Redis"

  transit_encryption_mode = "SERVER_AUTHENTICATION"

  depends_on = [google_service_networking_connection.private_vpc]

  labels = {
    project     = "archon"
    environment = var.environment
  }
}

# ---------- Cloud Storage ----------

resource "google_storage_bucket" "storage" {
  name          = "${var.gcp_project_id}-archon-${var.environment}"
  location      = var.gcp_region
  force_destroy = var.environment != "production"

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  labels = {
    project     = "archon"
    environment = var.environment
  }
}

# ---------- Secret Manager ----------

resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.cluster_name}-db-password"

  replication {
    auto {}
  }

  labels = {
    project     = "archon"
    environment = var.environment
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = var.db_password
}
