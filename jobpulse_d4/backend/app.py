import time
import os
import csv
import io
import json
from datetime import datetime

from openpyxl import Workbook
from flask import send_file
import tempfile


import requests
from flask import Flask, request, jsonify, Response, render_template
from dotenv import load_dotenv
from flask_cors import CORS

from celery_app import celery
from celery import group
from db import (
    get_conn,
    create_export_job,
    update_export_job_status,
    get_export_job,
    list_export_jobs,
    get_local_backup_task_ids,
    add_local_backup_task_id,
)

# Load .env variables
load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app, resources={r"/*": {"origins": "*"}})

OCTOPARSE_API_TIER = "advanced"
BASE_URL = "https://advancedapi.octoparse.com"
# Default to env-based credentials
USERNAME = os.getenv("OCTOPARSE_USERNAME")
PASSWORD = os.getenv("OCTOPARSE_PASSWORD")
# Directory where background exports are stored.
EXPORTS_DIR = os.getenv("EXPORTS_DIR", "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)

# Manage login token (YOUR WORKING VERSION)
class TokenManager:
    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0

    def _store(self, payload: dict):
        self.access_token = payload.get("access_token")
        self.refresh_token = payload.get("refresh_token")
        # Subtract 60s as safety buffer
        self.expires_at = time.time() + int(payload.get("expires_in", 0)) - 60

    def _valid(self) -> bool:
        return self.access_token and time.time() < self.expires_at

    def _fetch_with_password(self):
        if not USERNAME or not PASSWORD:
            return "Missing OCTOPARSE_USERNAME/PASSWORD", 400

        res = requests.post(
            f"{BASE_URL}/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"username": USERNAME, "password": PASSWORD, "grant_type": "password"},
            timeout=30,
        )
        if res.status_code != 200:
            return res.text, res.status_code

        self._store(res.json())
        return None, 200

    def _refresh(self) -> bool:
        if not self.refresh_token:
            return False
        res = requests.post(
            f"{BASE_URL}/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"refresh_token": self.refresh_token, "grant_type": "refresh_token"},
            timeout=30,
        )
        if res.status_code != 200:
            return False
        self._store(res.json())
        return True

    def get_token(self) -> str:
        if self._valid():
            return self.access_token
        if not self._refresh():
            self._fetch_with_password()
        return self.access_token

    def headers(self) -> dict:
        return {"Authorization": f"bearer {self.get_token()}"}

token_mgr = TokenManager()

# --- Helpers ---
def _handle_response(res: requests.Response):
    """Convert requests.Response into Flask JSON or error."""
    if res.status_code != 200:
        return jsonify({"error": res.text}), res.status_code
    try:
        return jsonify(res.json())
    except Exception:
        return res.text, res.status_code

# --- UI ---
@app.get("/")
def home():
    return render_template("index.html")

@app.post("/login")
def login():
    """Obtain and cache a new Octoparse access token from request body."""
    body = request.get_json() or {}
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    # Temporarily set credentials for this login attempt
    global USERNAME, PASSWORD
    USERNAME = username
    PASSWORD = password

    err, status = token_mgr._fetch_with_password()
    if status != 200:
        return jsonify({"error": err}), status

    return jsonify({
        "access_token": token_mgr.access_token,
        "expires_at": token_mgr.expires_at
    })

@app.get("/task-groups")
def list_task_groups():
    res = requests.get(f"{BASE_URL}/api/TaskGroup", headers=token_mgr.headers(), timeout=30)
    return _handle_response(res)

@app.get("/tasks")
def list_tasks():
    task_group_id = request.args.get("taskGroupId")
    if not task_group_id:
        return jsonify({"error": "taskGroupId is required"}), 400

    res = requests.get(
        f"{BASE_URL}/api/Task",
        params={"taskGroupId": task_group_id},
        headers=token_mgr.headers(),
        timeout=30,
    )
    return _handle_response(res)

@app.post("/task/<task_id>/start")
def start_task(task_id):
    if OCTOPARSE_API_TIER != "advanced":
        return jsonify({"error": "StartTask requires Advanced API"}), 403

    res = requests.post(
        f"{BASE_URL}/api/task/StartTask",
        params={"taskId": task_id},
        headers=token_mgr.headers(),
        timeout=30,
    )
    return _handle_response(res)

@app.post("/task/<task_id>/stop")
def stop_task(task_id):
    if OCTOPARSE_API_TIER != "advanced":
        return jsonify({"error": "StopTask requires Advanced API"}), 403

    res = requests.post(
        f"{BASE_URL}/api/task/StopTask",
        params={"taskId": task_id},
        headers=token_mgr.headers(),
        timeout=30,
    )
    return _handle_response(res)

@app.post("/tasks/status")
def get_status():
    if OCTOPARSE_API_TIER != "advanced":
        return jsonify({"error": "GetTaskStatusByIdList requires Advanced API"}), 403

    body = request.get_json()
    if not body or "taskIdList" not in body:
        return jsonify({"error": "taskIdList is required"}), 400

    res = requests.post(
        f"{BASE_URL}/api/task/GetTaskStatusByIdList",
        json=body,
        headers=token_mgr.headers(),
        timeout=30,
    )
    return _handle_response(res)

@app.get("/task/<task_id>/data/by-offset")
def get_data_by_offset(task_id):
    offset = int(request.args.get("offset", 0))
    size = int(request.args.get("size", 100))

    res = requests.get(
        f"{BASE_URL}/api/alldata/GetDataOfTaskByOffset",
        params={"taskId": task_id, "offset": offset, "size": size},
        headers=token_mgr.headers(),
        timeout=60,
    )
    return _handle_response(res)

# --- NEW routes for D4 ---

# 1) Ingest from Octoparse into DB (upsert)
@app.post("/ingest/<task_id>")
def ingest_task(task_id):
    from db import get_conn, upsert_job
    offset = int(request.args.get("offset", 0))
    size = int(request.args.get("size", 100))

    res = requests.get(
        f"{BASE_URL}/api/alldata/GetDataOfTaskByOffset",
        params={"taskId": task_id, "offset": offset, "size": size},
        headers=token_mgr.headers(),
        timeout=60,
    )
    if res.status_code != 200:
        return _handle_response(res)

    data = res.json().get("data", {})
    items = data.get("dataList", [])
    inserted = 0

    conn = get_conn()
    with conn.cursor() as cur:
        for j in items:
            try:
                upsert_job(cur, j)
                inserted += 1
            except Exception as e:
                print("UPSERT ERROR:", e)

    return jsonify({"received": len(items), "upserted": inserted, "offset": offset, "size": size})

# 2) Search (filters, sort, pagination)
@app.get("/search")
def search_jobs():
    from db import get_conn

    q = request.args.get("q", "").strip()          # title contains
    geo = request.args.get("geo", "").strip()      # location contains
    emp = request.args.get("employment", "").strip()
    senior = request.args.get("seniority", "").strip()
    start = request.args.get("start", "").strip()  # ISO date
    end = request.args.get("end", "").strip()      # ISO date
    sort = request.args.get("sort", "post_time")   # post_time|title|company
    order = request.args.get("order", "desc")      # asc|desc
    page = int(request.args.get("page", 1))
    page_size = min(int(request.args.get("page_size", 25)), 100)
    offset = (page - 1) * page_size

    clauses, args = [], []

    if q:
        clauses.append("job_title LIKE %s")
        args.append(f"%{q}%")
    if geo:
        clauses.append("job_location LIKE %s")
        args.append(f"%{geo}%")
    if emp:
        clauses.append("employment_type = %s")
        args.append(emp)
    if senior:
        clauses.append("seniority_level = %s")
        args.append(senior)
    if start:
        clauses.append("post_time >= %s")
        args.append(start)
    if end:
        clauses.append("post_time < %s")
        args.append(end)

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sort_col = {"post_time":"post_time","title":"job_title","company":"company"}.get(sort,"post_time")
    order_sql = "DESC" if order.lower()=="desc" else "ASC"

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM jobs {where_sql}", args)
        total = cur.fetchone()["c"]

        cur.execute(
            f"""SELECT id, job_title, company, job_location, post_time, job_link
                FROM jobs {where_sql}
                ORDER BY {sort_col} {order_sql}
                LIMIT %s OFFSET %s""",
            args + [page_size, offset]
        )
        rows = cur.fetchall()

    return jsonify({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": rows
    })

# 3) Export current page (CSV or JSON)
@app.get("/export")
def export_jobs():
    fmt = request.args.get("format","csv").lower()

    # Reuse search logic by calling it internally
    with app.test_request_context(query_string=request.query_string):
        data_resp = search_jobs()
        if isinstance(data_resp, tuple):
            data = data_resp[0].json
        else:
            data = data_resp.json

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    rows = data.get("items", [])

    if fmt == "json":
        filename = f"jobpulse_export_{ts}.json"
        return Response(
            response=json.dumps(rows, default=str),
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    filename = f"jobpulse_export_{ts}.csv"
    output = io.StringIO()
    headers = rows[0].keys() if rows else ["id","job_title","company","job_location","post_time","job_link"]
    w = csv.DictWriter(output, fieldnames=headers)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return Response(
        response=output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/search-live")
def search_live():
    """
    Returns one page of Octoparse data directly (no DB required).
    Pass ?taskId=...&offset=0&size=50&save=true to also store in DB.
    """
    task_id = request.args.get("taskId")
    if not task_id:
        return jsonify({"error": "taskId is required"}), 400
    offset = int(request.args.get("offset", 0))
    size = int(request.args.get("size", 50))
    save = request.args.get("save", "false").lower() == "true"

    res = requests.get(
        f"{BASE_URL}/api/alldata/GetDataOfTaskByOffset",
        params={"taskId": task_id, "offset": offset, "size": size},
        headers=token_mgr.headers(),
        timeout=60,
    )
    if res.status_code != 200:
        return _handle_response(res)

    payload = res.json()
    data = (payload or {}).get("data", {})
    items = data.get("dataList", [])

    if save and items:
        from db import get_conn, upsert_job
        conn = get_conn()
        saved = 0
        with conn.cursor() as cur:
            for j in items:
                try:
                    upsert_job(cur, j)
                    saved += 1
                except Exception as e:
                    print("UPSERT ERROR:", e)
        return jsonify({"mode":"live", "received": len(items), "saved": saved, "items": items})

    return jsonify({"mode":"live", "received": len(items), "items": items})

def _octo_get(path, params=None):
    res = requests.get(f"{BASE_URL}{path}", params=params, headers=token_mgr.headers(), timeout=60)
    return res

def _octo_post(path, params=None, json_body=None):
    res = requests.post(f"{BASE_URL}{path}", params=params, json=json_body, headers=token_mgr.headers(), timeout=60)
    return res


@app.get("/octo/task-groups")
def octo_task_groups():
    # alias of /task-groups but namespaced; front-end will use this
    return list_task_groups()

@app.get("/octo/tasks")
def octo_tasks():
    # alias of /tasks but namespaced; front-end will use this
    return list_tasks()


def wait_for_tasks(task_ids):
    """
    Wait until all Octoparse tasks reach 'Finished', 'Stopped', or (for local-only
    tasks) 'Unexecuted' 3 times in a row. Tasks seen as Unexecuted 3 times are
    added to local_backup_tasks so next run skips start/wait.
    """
    import time, requests

    url = "https://openapi.octoparse.com/cloudextraction/statuses/v2"

    TERMINAL = {"Finished", "Stopped"}
    UNEXECUTED_THRESHOLD = 3
    seen_active = set()
    unexecuted_count = {}
    start_time = time.time()
    STALE_GUARD_TIMEOUT = 60

    while True:
        headers = {
            "Authorization": f"Bearer {token_mgr.get_token()}",
            "Content-Type": "application/json"
        }

        res = requests.post(url, json={"taskIds": task_ids}, headers=headers)
        if res.status_code != 200:
            print("Status check failed:", res.text)
            time.sleep(5)
            continue

        data = res.json().get("data", [])
        statuses = {str(d["taskId"]): d["status"] for d in data}
        print(statuses)

        elapsed = time.time() - start_time
        guard_expired = elapsed > STALE_GUARD_TIMEOUT

        for tid_str, status in statuses.items():
            if status not in TERMINAL:
                seen_active.add(tid_str)
            if status == "Unexecuted":
                unexecuted_count[tid_str] = unexecuted_count.get(tid_str, 0) + 1
                if unexecuted_count[tid_str] == UNEXECUTED_THRESHOLD:
                    conn = None
                    try:
                        conn = get_conn()
                        with conn.cursor() as cur:
                            add_local_backup_task_id(cur, tid_str)
                    except Exception as e:
                        print(f"Failed to add local_backup_task_id {tid_str}:", e)
                    finally:
                        if conn:
                            conn.close()
            else:
                unexecuted_count[tid_str] = 0

        all_done = True
        for tid in task_ids:
            tid_str = str(tid)
            status = statuses.get(tid_str)
            if status is None:
                all_done = False
                break
            if status in TERMINAL:
                if tid_str in seen_active or guard_expired:
                    continue
                else:
                    print(f"⚠️  Task {tid_str} reports '{status}' but hasn't been seen active yet — treating as stale")
                    all_done = False
                    break
            elif status == "Unexecuted" and unexecuted_count.get(tid_str, 0) >= UNEXECUTED_THRESHOLD:
                continue
            else:
                all_done = False
                break

        if all_done:
            print("✅ All tasks finished.")
            break

        time.sleep(5)


def build_octoparse_workbook(task_group_id, selected_task_ids=None, progress_cb=None):
    """
    Core orchestration for running Octoparse tasks and building an Excel workbook.

    Returns a tuple of (Workbook, tasks_list). Raises on errors so callers
    (Flask route or Celery task) can convert to appropriate responses.
    """
    offset = 0
    size = 1000
    # Normalize to strings so comparison works whether API returns taskId as str or int
    selected_ids_set = {str(x) for x in (selected_task_ids or [])}

    if progress_cb:
        progress_cb("Fetching tasks for group")

    # 1) fetch tasks in the group
    tasks_res = _octo_get("/api/Task", params={"taskGroupId": task_group_id})
    if tasks_res.status_code != 200:
        raise RuntimeError(f"Failed to fetch tasks: {tasks_res.text}")
    tasks = tasks_res.json().get("data", []) or []
    if selected_ids_set:
        tasks = [t for t in tasks if str(t.get("taskId") or "") in selected_ids_set]

    if not tasks:
        raise RuntimeError("No tasks found for this group (or selection).")

    task_ids = [t["taskId"] for t in tasks if t.get("taskId")]

    # Local-backup task IDs: skip start/wait, fetch by offset only
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            local_backup_ids = get_local_backup_task_ids(cur)
        conn.close()
    except Exception as e:
        print("Failed to load local_backup_task_ids:", e)
        local_backup_ids = set()

    # 2) start each task (skip tasks in local_backup_ids — they are run locally and backed up to cloud)
    wait_ids = [tid for tid in task_ids if str(tid) not in local_backup_ids]
    if progress_cb:
        progress_cb(f"Starting {len(wait_ids)} tasks")

    for tid in task_ids:
        if str(tid) in local_backup_ids:
            continue
        try:
            # _octo_post("/api/task/RemoveDataByTaskId", params={"taskId": tid})
            # time.sleep(2)  # Give Octoparse time to commit the clear
            _octo_post("/api/task/StartTask", params={"taskId": tid})
        except Exception as e:
            print("StartTask error:", tid, e)

    if progress_cb:
        progress_cb("Waiting for tasks to complete")

    if wait_ids:
        wait_for_tasks(wait_ids)

    # 3) fetch data per task by offset paging and build Excel
    # Exponential backoff constants for data-readiness retries
    MAX_DATA_READY_RETRIES = 8
    INITIAL_BACKOFF_SECS = 5
    MAX_BACKOFF_SECS = 60

    wb = Workbook()
    default_sheet_used = False
    total_tasks = len(tasks)
    failed_tasks = []

    for idx, t in enumerate(tasks):
        tid = t.get("taskId")
        tname = t.get("taskName") or f"Task_{idx+1}"
        safe_title = "".join(c for c in tname if c not in '[]:*?/\\').strip()
        if len(safe_title) == 0:
            safe_title = f"Task_{idx+1}"
        safe_title = safe_title[:31]

        all_rows = []
        ofs = offset
        backoff_secs = INITIAL_BACKOFF_SECS
        retries_left = MAX_DATA_READY_RETRIES

        while True:
            data_res = _octo_get(
                "/api/alldata/GetDataOfTaskByOffset",
                params={"taskId": tid, "offset": ofs, "size": size},
            )
            if data_res.status_code != 200:
                print(f"[GetData] taskId={tid} offset={ofs} status={data_res.status_code} body={data_res.text[:200]}")
                break
            payload = data_res.json() or {}
            if not payload:
                print(f"[GetData] taskId={tid} offset={ofs} empty JSON body")
                break
            # Advanced API can return 200 with error/error_Description in body
            if payload.get("error") and payload.get("error") != "success":
                print(f"[GetData] taskId={tid} offset={ofs} API error: {payload.get('error')} - {payload.get('error_Description', '')}")
                break
            data = payload.get("data")
            if data is None:
                data = payload
            if isinstance(data, list):
                items = data
            else:
                items = (data or {}).get("dataList") or (data or {}).get("list") or (data or {}).get("items") or []

            if not items:
                data_total = (data or {}).get("total") if isinstance(data, dict) else None
                data_rest = (data or {}).get("restTotal") if isinstance(data, dict) else None

                # First page empty → data likely not finalized yet; retry with exponential backoff
                if ofs == 0 and retries_left > 0:
                    retries_left -= 1
                    print(f"[GetData] taskId={tid} data not ready "
                          f"(total={data_total}, restTotal={data_rest}), "
                          f"retrying in {backoff_secs}s ({retries_left} retries left)")
                    if progress_cb:
                        progress_cb(f"Waiting for data — {tname} (retry in {backoff_secs}s, {retries_left} left)")
                    time.sleep(backoff_secs)
                    backoff_secs = min(backoff_secs * 2, MAX_BACKOFF_SECS)
                    continue

                # Exhausted retries or not the first page — give up on this task
                print(f"[GetData] taskId={tid} offset={ofs} — no data returned "
                      f"(total={data_total}, restTotal={data_rest})")
                if isinstance(data, dict):
                    print(f"[GetData] taskId={tid} data keys={list(data.keys())}")
                break

            # Data arrived — collect rows and paginate
            all_rows.extend(items)
            next_ofs = payload.get("offset")
            if next_ofs is None and isinstance(data, dict):
                next_ofs = data.get("offset")
            if next_ofs is not None and isinstance(next_ofs, (int, float)):
                ofs = int(next_ofs)
            else:
                ofs = ofs + len(items)
            if len(items) < size:
                break

        if not all_rows:
            print(f"Task {tid} ({tname}): no rows returned")
            failed_tasks.append(tname)
            continue

        # write to sheet
        if not default_sheet_used:
            ws = wb.active
            ws.title = safe_title
            default_sheet_used = True
        else:
            ws = wb.create_sheet(title=safe_title)

        # columns / headers: union of keys found (simple approach)
        headers = set()
        for r in all_rows:
            headers.update(r.keys() if isinstance(r, dict) else [])
        headers = list(headers) if headers else ["id", "title", "companyName", "location", "jobUrl"]
        ws.append(headers)

        for r in all_rows:
            if not isinstance(r, dict):
                continue
            ws.append([r.get(h, "") for h in headers])

        if progress_cb:
            progress_cb(f"Fetched data for {idx+1}/{total_tasks} tasks")

    if failed_tasks and len(failed_tasks) == total_tasks:
        raise RuntimeError(f"All tasks returned no data after retries: {', '.join(failed_tasks)}")

    return wb, tasks


@app.post("/octo/run-all")
def octo_run_all():
    """
    Synchronous variant kept for backward compatibility.
    Body JSON: { "taskGroupId": 12345, "selectedTaskIds": [..](optional) }
    """
    body = request.get_json() or {}
    task_group_id = body.get("taskGroupId")
    if not task_group_id:
        return jsonify({"error": "taskGroupId is required"}), 400

    selected_ids = body.get("selectedTaskIds")  # optional list

    try:
        wb, _ = build_octoparse_workbook(task_group_id, selected_ids)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # stream workbook as an .xlsx download
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        wb.save(tmp.name)
        tmp.flush()
        tmp.seek(0)
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"jobpulse_octoparse_tasks_{task_group_id}_{ts}.xlsx"
        return send_file(
            tmp.name,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        try:
            tmp.close()
        except Exception:
            pass


@celery.task(name="run_export_task")
def run_export_task(job_id, task_group_id, selected_task_ids):
    """
    Celery task that runs the Octoparse export and writes the Excel file
    into EXPORTS_DIR, updating the exports table as it goes.
    """
    conn = get_conn()

    def progress_cb(message):
        with conn.cursor() as cur:
            update_export_job_status(cur, job_id, progress=message, status="running")

    try:
        progress_cb("Starting export job")
        wb, _ = build_octoparse_workbook(task_group_id, selected_task_ids, progress_cb=progress_cb)

        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"jobpulse_octoparse_tasks_{task_group_id}_{job_id}_{ts}.xlsx"
        file_path = os.path.join(EXPORTS_DIR, filename)
        wb.save(file_path)

        with conn.cursor() as cur:
            update_export_job_status(
                cur,
                job_id,
                status="done",
                progress="Completed",
                file_name=filename,
                file_path=file_path,
            )
    except Exception as e:
        with conn.cursor() as cur:
            update_export_job_status(
                cur,
                job_id,
                status="failed",
                progress="Failed",
                error=str(e),
            )
        raise
    finally:
        conn.close()


@app.post("/jobs")
def create_job():
    """
    Create a new export job and enqueue the Celery task.
    Body: { "taskGroupId": 12345, "taskGroupName": "...", "selectedTaskIds": [...], "selectedTaskNames": [...] }
    """
    body = request.get_json() or {}
    task_group_id = body.get("taskGroupId")
    if not task_group_id:
        return jsonify({"error": "taskGroupId is required"}), 400

    selected_ids = body.get("selectedTaskIds") or []
    task_group_name = body.get("taskGroupName") or None
    selected_task_names = body.get("selectedTaskNames") or []

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            job_id = create_export_job(
                cur, task_group_id, selected_ids,
                task_group_name=task_group_name,
                task_names=selected_task_names if selected_task_names else None,
            )
        # enqueue background work
        run_export_task.delay(job_id, task_group_id, selected_ids)
    finally:
        conn.close()

    return jsonify({"jobId": int(job_id)})


@app.get("/jobs")
def list_jobs():
    """
    List recent export jobs for the global table.
    """
    limit = int(request.args.get("limit", 100))
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            jobs = list_export_jobs(cur, limit=limit)
    finally:
        conn.close()

    # Decode JSON fields for convenience
    for j in jobs:
        try:
            j["selected_task_ids"] = json.loads(j.get("selected_task_ids") or "[]")
        except Exception:
            j["selected_task_ids"] = []
        try:
            raw = j.get("task_names")
            j["task_names"] = json.loads(raw) if isinstance(raw, str) and raw else (raw or [])
        except Exception:
            j["task_names"] = []

    return jsonify({"items": jobs})


@app.get("/login-template-data")
def get_login_template_data():
    """
    List rows from login_template_data with pagination and optional date filtering.
    Query params: page, page_size, start_date (YYYY-MM-DD), end_date (YYYY-MM-DD)
    """
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("page_size", 50))))
    offset = (page - 1) * page_size
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    clauses, args = [], []
    if start_date:
        clauses.append("scrape_date >= %s")
        args.append(start_date)
    if end_date:
        clauses.append("scrape_date <= %s")
        args.append(end_date)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS c FROM login_template_data {where_sql}", args)
            total = cur.fetchone()["c"]
            cur.execute(
                f"""SELECT scrape_date, Title, Company, Location, Salary, Keyword, Date, Posted_time
                   FROM login_template_data {where_sql}
                   ORDER BY scrape_date DESC, id DESC
                   LIMIT %s OFFSET %s""",
                args + [page_size, offset],
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    def _serialize(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj

    items = [{k: _serialize(v) for k, v in row.items()} for row in rows]

    return jsonify({
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


@app.get("/login-template-data/export-csv")
def export_login_template_csv():
    """
    Export login_template_data as CSV filtered by date range.
    Query params: start_date, end_date (YYYY-MM-DD)
    """
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    clauses, args = [], []
    if start_date:
        clauses.append("scrape_date >= %s")
        args.append(start_date)
    if end_date:
        clauses.append("scrape_date <= %s")
        args.append(end_date)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT * FROM login_template_data {where_sql}
                   ORDER BY scrape_date DESC, id DESC""",
                args,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    def _serialize(obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return obj

    fieldnames = [k for k in rows[0].keys() if k != "id"] if rows else [
        "scrape_date", "Input_URL", "Keyword", "Result_count_for_reference_only",
        "Location", "Current_Page", "Current_Page_URL", "Title", "Title_URL", "Image",
        "Company", "Date", "About_the_job", "Posted_time", "Salary", "People_applied",
        "Job_preference_1", "Job_preference_2", "Job_preference_3", "Job_preference_4",
        "Company_URL", "Company_follower", "Company_size", "Count_of_employee_onLinkedIn",
        "Company_Intro", "created_at"
    ]
    output = io.StringIO()
    w = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    w.writeheader()
    for row in rows:
        w.writerow({k: _serialize(v) for k, v in row.items()})

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    label = f"{start_date or 'all'}_to_{end_date or 'all'}"
    filename = f"login_template_data_{label}_{ts}.csv"
    return Response(
        response=output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/jobs/<int:job_id>")
def get_job(job_id):
    """
    Fetch a single export job (for polling).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            job = get_export_job(cur, job_id)
    finally:
        conn.close()

    if not job:
        return jsonify({"error": "Job not found"}), 404

    try:
        job["selected_task_ids"] = json.loads(job.get("selected_task_ids") or "[]")
    except Exception:
        job["selected_task_ids"] = []
    try:
        raw = job.get("task_names")
        job["task_names"] = json.loads(raw) if isinstance(raw, str) and raw else (raw or [])
    except Exception:
        job["task_names"] = []

    return jsonify(job)


@app.get("/jobs/<int:job_id>/download")
def download_job(job_id):
    """
    Download the Excel file for a completed job.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            job = get_export_job(cur, job_id)
    finally:
        conn.close()

    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job.get("status") != "done":
        return jsonify({"error": f"Job status is {job.get('status')}, not done"}), 400

    file_path = job.get("file_path")
    file_name = job.get("file_name") or os.path.basename(file_path or "")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "Export file not found"}), 404

    return send_file(
        file_path,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=file_name,
    )


@celery.task(name="etl_coordinator")
def etl_coordinator():
    """Reads all task IDs from DB and dispatches each as an independent subtask."""
    from db import get_conn
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT task_id FROM local_backup_tasks")
            task_ids = [row["task_id"] for row in cur.fetchall()]
            print("tasks are",task_ids)
    finally:
        conn.close()
    if not task_ids:
        print("[ETL] No task IDs found in DB, nothing to do.")
        return
    # Dispatch all as parallel independent tasks
    job = group(etl_ingest_single.s(tid) for tid in task_ids)
    job.apply_async()
    print(f"[ETL] Dispatched {len(task_ids)} ingest tasks")

@celery.task(name="etl_ingest_single", bind=True, max_retries=3)
def etl_ingest_single(self, task_id):
    """Scheduled ETL: fetch non-exported data from Octoparse and upsert into login_template_data."""
    try:
        from db import get_conn, upsert_login_template_data
        from datetime import date

        size = 100
        total_upserted = 0
        scrape_date = date.today()

        conn = get_conn()
        try:
            while True:
                res = requests.get(
                    f"{BASE_URL}/api/notexportdata/gettop",
                    params={"taskId": task_id, "size": size},
                    headers=token_mgr.headers(),
                    timeout=60,
                )
                if res.status_code != 200:
                    print(f"[ETL] Failed to fetch data for task {task_id}: {res.text}")
                    break

                data = res.json().get("data", {})
                items = data.get("dataList", [])

                if not items:
                    print(f"[ETL] No more non-exported data for task {task_id}")
                    break

                with conn.cursor() as cur:
                    for j in items:
                        try:
                            upsert_login_template_data(cur, j, scrape_date)
                            total_upserted += 1
                        except Exception as e:
                            print(f"[ETL] Upsert error: {e}")

                update_res = requests.post(
                    f"{BASE_URL}/api/notexportdata/update",
                    params={"taskId": task_id},
                    headers=token_mgr.headers(),
                    timeout=60,
                )
                if update_res.status_code != 200:
                    print(f"[ETL] Failed to mark data as exported for task {task_id}: {update_res.text}")
                    break

                if len(items) < size:
                    break
        finally:
            conn.close()

        print(f"[ETL] Done. Upserted {total_upserted} rows into login_template_data for task {task_id}")
        return {"upserted": total_upserted, "task_id": task_id}
    except Exception as exc:
        print(f"[ETL] Task {task_id} failed: {exc}")
        raise self.retry(exc=exc, countdown=60)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1112)
