# JobPulse — Octoparse Task Runner

JobPulse connects to **Octoparse** to list **Task Groups** and **Tasks**, lets you **run all or selected tasks**, and produces **Excel (.xlsx)** exports with **one worksheet per task**. It persists scraped data in **MySQL**, runs exports in the background via **Celery**, and automatically ingests new data on a fixed schedule using **Celery Beat** and an **AWS EC2** instance.

---

## Demo Video

Watch the end‑to‑end demo here:  
**[https://drive.google.com/file/d/1EhJnizsDaYKmttWUfLa2IUb7MlRlENwt/view?usp=drive_link](https://drive.google.com/file/d/1EhJnizsDaYKmttWUfLa2IUb7MlRlENwt/view?usp=drive_link)**

---

## Table of Contents

- [Architecture Flowchart](#architecture-flowchart)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Getting Started](#getting-started)
  - [Option A — Docker Local (recommended)](#option-a--docker-local-recommended)
  - [Option B — Docker Production](#option-b--docker-production)
- [Using the App](#using-the-app)
- [How Exports Work](#how-exports-work)
- [Scheduled ETL Pipeline](#scheduled-etl-pipeline)
- [Common Workflows](#common-workflows)



- [Project Structure](#project-structure)

---

## Architecture Flowchart

<img width="3904" height="2723" alt="image" src="https://github.com/user-attachments/assets/ec2fd976-7210-441c-9551-e15ed7ee450c" />

The diagram above shows the two main parts of the system:

- **Backend** — The user opens the web UI, picks which Octoparse tasks to run, and clicks **Run**. The request goes to the **Job Runner Service** running on an AWS EC2 instance. The service puts the work on a **Task Queue**, tells Octoparse to start scraping, waits for results, and sends back an **Excel file** for download.
- **Scheduled Tasks** — A separate process on the same EC2 instance runs Octoparse tasks automatically on a **fixed schedule**. Once new data is available, **Celery Beat** picks it up, pulls it from Octoparse, and writes it straight into the database — no manual action needed.

---

## Features

- **Octoparse login** (token cached and auto-refreshed on the server)
- **Browse Task Groups → Tasks**
- **Run all / Run selected** tasks
- **Background Excel exports** via Celery — export jobs are queued, tracked, and downloadable from the UI
- **Export job management** — view status, progress, and download history in a dedicated table
- **Scheduled ETL** — Celery Beat triggers automatic data ingestion on a fixed schedule
- **Login Template Data** — browse, filter by date, and export scraped data as CSV
- **MySQL persistence** — all scraped data, export jobs, and task metadata stored in a relational database
- **Bulk selection**: **Select all** / **Deselect all**
- **Local backup tasks** — tasks running on the EC2 schedule are tracked separately; the ETL pipeline fetches their non-exported data automatically

---

## Prerequisites

- **Octoparse account** with existing tasks
- **Docker Desktop** (WSL2 enabled on Windows)

> Docker Compose will provision MySQL, Redis, Celery Worker, and Celery Beat automatically—no manual install needed.

---

## Configuration

Copy the example env file and fill in your values:

```bash
cp jobpulse_d4/backend/.env.example jobpulse_d4/backend/.env
```

`backend/.env` should contain (do **not** commit real secrets):

```ini
# Octoparse API Credentials
OCTOPARSE_USERNAME=<your-octoparse-email>
OCTOPARSE_PASSWORD=<your-octoparse-password>

# Database Configuration
DB_HOST=db
DB_USER=jobuser
DB_PASSWORD=<secure-password>
DB_NAME=jobpulse

# MySQL Root Password (used by docker-compose-local.yml)
MYSQL_ROOT_PASSWORD=<secure-root-password>

# Flask Configuration (optional)
FLASK_ENV=production
```

> The `REDIS_URL` is set automatically by Docker Compose (`redis://redis:6379/0`). Override it in `.env` only if you use an external Redis instance.

---

## Getting Started

### Option A — Docker Local (recommended)

This spins up all five services including a local MySQL database:

```bash
cd jobpulse_d4
docker compose -f docker-compose-local.yml up --build
# then open:
http://localhost:5000
```

> If you changed the Flask port (e.g., `1834`), map and visit that port instead.

The `docker-compose-local.yml` file starts:


| Service           | Description                         |
| ----------------- | ----------------------------------- |
| **db**            | MySQL 8.0 (schema auto-initialized) |
| **web**           | Flask/Gunicorn on port 5000         |
| **redis**         | Redis 7 (Celery broker)             |
| **celery_worker** | Processes background export jobs    |
| **celery_beat**   | Triggers scheduled ETL ingestion    |


### Option B — Docker Production

If you have an **external MySQL** instance (e.g., RDS), use the production compose file. Set `DB_HOST`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` in `backend/.env` to point at your database, then:

```bash
cd jobpulse_d4
docker compose up --build
# then open:
http://localhost:5000
```

> This compose file does **not** include a MySQL service—make sure your external database is reachable and initialized with `backend/schema.sql`.

---

## Using the App

1. **Login**: Enter your Octoparse credentials and click **Login** → status shows **Logged in ✓** if successful.
2. **Pick a Task Group**: Choose a group from the dropdown; its tasks appear as checkboxes (pre-selected).
3. **Bulk select**: Use **Select all** / **Deselect all** to toggle quickly.
<!-- 4. **Options (optional)**:

   * **Offset** (default `0`): starting index for fetching
   * **Size** (default `100`): page size per request
   * **Wait (sec)** (default `15`): short best-effort wait after starting tasks -->

4. **Run & Export**:
  - **Run all tasks → Export Excel**: run every task in the group
  - **Run selected → Export Excel**: run only checked tasks
  - The export job is queued in the background — track its progress in the **Exports** table.
  - Once complete, click **Download** to get the **.xlsx** file.
5. **Login Template Data**: The data table can be used to browse scraped records. Filter by **date range** and **export as CSV**.

---

## How Exports Work

- When you click **Run**, a background **Celery task** is created. The server **starts** each selected Octoparse task, **waits** for them to finish, then **fetches data page by page** and builds an **Excel** workbook using `openpyxl`.
- If data is not immediately available after a task finishes, the worker retries with **exponential backoff** before giving up.
- **Sheet names** are sanitized (Excel-safe, ≤ 31 chars).
- **Headers** are derived from keys present in the returned items for each task.
- The finished file is saved to the `exports/` directory and recorded in the database. The UI polls the job status and enables download once it's done.

---

## Scheduled ETL Pipeline

Octoparse tasks run automatically on a **fixed schedule** on an AWS EC2 instance, scraping fresh job data on a fixed schedule.

Once new data is available, **Celery Beat** kicks off a background job that:

1. Looks up which Octoparse tasks to pull data from.
2. Downloads any **new, unprocessed records** from each task.
3. Saves them into the database and marks them as collected so they aren't pulled again.

This keeps the database continuously up to date without any manual work.

---

## Common Workflows

- **On-demand export**: Pick a task group, select tasks, click run — the background job handles the rest.
- **Scheduled ingestion**: Octoparse tasks run automatically on EC2; Celery Beat picks up the new data on a fixed schedule and writes it to MySQL.
- **Quick subset**: **Deselect all**, tick a few tasks, then **Run selected**.
- **Date-filtered CSV**: In the data table, set a date range, and click **Export CSV**.

---
<!-- ## Troubleshooting

**Login button does nothing**

* Hard-refresh (Ctrl/Cmd+Shift+R).
* Open **DevTools → Console**; verify `/static/taskrunner.js` loads without errors and IDs match (`loginBtn`, `groupSelect`, etc.).

**`/login` returns an error**

* Check envs inside the container:

  ```bash
  docker compose exec web env | grep OCTOPARSE
  ```

  If placeholders appear, ensure `env_file: ./backend/.env` is set or use `load_dotenv(override=True)`.

**Excel is empty/short**

* Increase **Wait (sec)** (e.g., 30) and/or **Size**.
* Confirm selected tasks actually produce results for the current offset.

**Network / corporate VPN**

* VPN or firewall rules can block container egress; try a different network or configure Docker proxy.

**Port mismatch**

* If you changed Flask’s port, update Compose mapping and the URL you open.

--- -->

## Project Structure

```
jobpulse_d4/
  docker-compose.yml            # Production (external DB)
  docker-compose-local.yml      # Local dev (includes MySQL)
  backend/
    app.py                      # Flask app + Celery tasks
    celery_app.py               # Celery factory + beat schedule
    db.py                       # Database helpers (PyMySQL)
    schema.sql                  # MySQL schema (auto-loaded by local compose)
    requirements.txt
    Dockerfile
    .env.example                # Template for backend/.env
    .env                        # Not committed — your secrets
    exports/                    # Generated Excel files (runtime)
    templates/
      index.html                # Main UI
    static/
      styles.css
      taskrunner.js
```

---

<!-- ## Security Notes

* Keep `.env` out of version control.
* Rotate Octoparse credentials if they were ever shared.
* For team use, prefer Docker + centralized secret management.

---

## Optional Extensions

* UI toggle: **Clear previous results before run** (default ON).
* Show per-task metrics after export (rows fetched, duration).
* **Invert selection** button; persist selections per group (localStorage).
* **Run & Save to DB** option for historical analytics.

---

## FAQ

**Do I need a database?**
No. The Task Runner works entirely against Octoparse and exports directly to Excel.

**Can I run only some tasks?**
Yes. Use **Deselect all**, check what you need, then **Run selected**.

**Why is my export missing rows?**
The run may still be populating. Increase **Wait (sec)**, bump **Size**, or re-run later.

---

## License

This project is for course use (Project 28). If you plan to reuse or publish, add an explicit license (e.g., MIT) and review Octoparse’s API terms. -->
