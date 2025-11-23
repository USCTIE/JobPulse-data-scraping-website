# JobPulse — Octoparse Task Runner

JobPulse connects to **Octoparse** to list **Task Groups** and **Tasks**, lets you **run all or selected tasks**, and downloads a single **Excel (.xlsx)** with **one worksheet per task**—no database required.

---

## Table of Contents

* [Features](#features)
* [Prerequisites](#prerequisites)
* [Configuration](#configuration)
* [Getting Started](#getting-started)

  * [Option A — Docker (recommended)](#option-a--docker-recommended)
  * [Option B — Local Python](#option-b--local-python)
* [Using the App](#using-the-app)
* [How Exports Work](#how-exports-work)
* [Common Workflows](#common-workflows)
* [Troubleshooting](#troubleshooting)
* [Project Structure](#project-structure)
* [Security Notes](#security-notes)
* [Optional Extensions](#optional-extensions)
* [FAQ](#faq)
* [License](#license)

---

## Features

* **Octoparse login** (token cached on the server)
* **Browse Task Groups → Tasks**
* **Run all / Run selected** tasks
* **Excel export**: one sheet per task, headers inferred from data
* **Bulk selection**: **Select all** / **Deselect all**
* **No DB dependency**: works entirely against Octoparse APIs

---

## Prerequisites

* **Octoparse account** with existing tasks
* **Docker Desktop** (WSL2 enabled on Windows)
  *(Optional)* **Python 3.11+** if running without Docker

---

## Configuration

Create `backend/.env` (do **not** commit real secrets):

```ini
OCTOPARSE_USERNAME=<your-octoparse-email>
OCTOPARSE_PASSWORD=<your-octoparse-password>
```

If you run via Docker Compose, ensure your `web` service loads this file:

```yaml
# docker-compose.yml (snippet)
services:
  web:
    build: ./backend
    env_file:
      - ./backend/.env
    ports:
      - "5000:5000"   # or your chosen port
```

If your compose file hard-codes placeholder envs, either remove them or allow `.env` to override in code:

```python
# backend/app.py (top of file)
from dotenv import load_dotenv
load_dotenv(override=True)
```

---

## Getting Started

### Option A — Docker (recommended)

```bash
docker compose up --build
# then open:
http://localhost:5000
```

> If you changed the Flask port (e.g., `1834`), map and visit that port instead.

### Option B — Local Python

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
. .venv/Scripts/Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

---

## Using the App

1. **Login**: Click **Login to Octoparse** → status shows **Logged in ✓** if successful.
2. **Pick a Task Group**: Choose a group; its tasks appear as checkboxes (pre-selected).
3. **Bulk select**: Use **Select all** / **Deselect all** to toggle quickly.
<!-- 4. **Options (optional)**:

   * **Offset** (default `0`): starting index for fetching
   * **Size** (default `100`): page size per request
   * **Wait (sec)** (default `15`): short best-effort wait after starting tasks -->
5. **Run & Export**:

   * **Run all tasks → Export Excel**: run every task in the group
   * **Run selected → Export Excel**: run only checked tasks
     An **.xlsx** downloads with one sheet per task.

---

## How Exports Work

* Server (best-effort) **clears old cloud data per task** (if enabled), **starts** each task, performs a short optional **wait**, then **fetches data by offset/size** from Octoparse and builds an **Excel** workbook using `openpyxl`.
* **Sheet names** are sanitized (Excel-safe, ≤ 31 chars).
* **Headers** are derived from keys present in the returned items for that task.

---

## Common Workflows

* **Fresh export only** (default): Click run; export contains only the newest results.
* **Large datasets**: Increase **Size** (e.g., 200–500) and/or re-run later to pick up additional rows.
* **Quick subset**: **Deselect all**, tick a few tasks, then **Run selected**.

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
jobpulse/
  docker-compose.yml
  backend/
    app.py
    requirements.txt
    .env                  # not committed
    templates/
      index.html          # Task Runner page
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
