-- ===========================
-- JobPulse Schema (Deliverable 4)
-- ===========================

CREATE DATABASE IF NOT EXISTS jobpulse CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE jobpulse;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS local_backup_tasks;
DROP TABLE IF EXISTS jobs;
DROP TABLE IF EXISTS exports;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(320) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(200),
  role ENUM('viewer','analyst','admin') DEFAULT 'viewer',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_login DATETIME,
  is_active TINYINT(1) DEFAULT 1
);

CREATE TABLE sessions (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  session_token VARCHAR(255) NOT NULL UNIQUE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  expires_at DATETIME,
  last_seen DATETIME,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE jobs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  job_title VARCHAR(255) NOT NULL,
  job_link VARCHAR(500),
  company VARCHAR(255),
  company_link VARCHAR(500),
  job_location VARCHAR(255),
  post_time DATETIME,
  applicant_count VARCHAR(100),
  job_description TEXT,
  industry VARCHAR(255),
  employment_type VARCHAR(100),
  valid_through DATETIME,
  seniority_level VARCHAR(100),
  job_function VARCHAR(255),
  hiring_person VARCHAR(255),
  min_pay DECIMAL(15,2),
  max_pay DECIMAL(15,2),
  UNIQUE KEY uq_jobs_job_link (job_link)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Helpful indexes for search
CREATE INDEX idx_jobs_title ON jobs (job_title);
CREATE INDEX idx_jobs_location ON jobs (job_location);
CREATE INDEX idx_jobs_post_time ON jobs (post_time);
CREATE INDEX idx_jobs_company ON jobs (company);

CREATE TABLE exports (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  task_group_id BIGINT,
  task_group_name VARCHAR(255),
  selected_task_ids TEXT,
  task_names TEXT,
  status ENUM('queued','running','done','failed') NOT NULL DEFAULT 'queued',
  progress VARCHAR(255),
  error TEXT,
  file_name VARCHAR(255),
  file_path VARCHAR(500),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE local_backup_tasks (
  task_id VARCHAR(64) PRIMARY KEY,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

SET FOREIGN_KEY_CHECKS = 1;
