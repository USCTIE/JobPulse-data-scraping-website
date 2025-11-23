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

# Load .env variables
load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app, resources={r"/*": {"origins": "*"}})

OCTOPARSE_API_TIER = "advanced"
BASE_URL = "https://advancedapi.octoparse.com"
USERNAME = os.getenv("OCTOPARSE_USERNAME")
PASSWORD = os.getenv("OCTOPARSE_PASSWORD")

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

# --- Your existing Octoparse routes (kept as-is) ---
@app.get("/login")
def login():
    """Obtain and cache a new Octoparse access token."""
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
    Wait until all Octoparse tasks reach 'Finished' or 'Stopped',
    using the /cloudextraction/statuses/v2 endpoint.
    """
    import time, requests

    url = "https://openapi.octoparse.com/cloudextraction/statuses/v2"

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
        statuses = {d["taskId"]: d["status"] for d in data}
        print(statuses)

        # Stop when all tasks are done
        if all(s in ("Finished", "Stopped") for s in statuses.values()):
            print("✅ All tasks finished.")
            break

        time.sleep(5)  # respect 1 request / 5 seconds limit


@app.post("/octo/run-all")
def octo_run_all():
    """
    Body JSON: { "taskGroupId": 12345, "offset": 0, "size": 100, "waitSeconds": 20, "selectedTaskIds": [..](optional) }
    Action: Start tasks, poll briefly (best-effort), retrieve data by offset, aggregate and return Excel.
    """
    body = request.get_json() or {}
    task_group_id = body.get("taskGroupId")
    if not task_group_id:
        return jsonify({"error": "taskGroupId is required"}), 400

    offset = 0
    size = 1000
    selected_ids = body.get("selectedTaskIds")  # optional list

    # 1) fetch tasks in the group
    tasks_res = _octo_get("/api/Task", params={"taskGroupId": task_group_id})
    if tasks_res.status_code != 200:
        return _handle_response(tasks_res)
    tasks = tasks_res.json().get("data", []) or []
    if selected_ids:
        tasks = [t for t in tasks if t.get("taskId") in set(selected_ids)]

    if not tasks:
        return jsonify({"error": "No tasks found for this group (or selection)."}), 404

    task_ids = [t["taskId"] for t in tasks if t.get("taskId")]

    # 2) start each task (best-effort; if already running/completed, Octoparse typically no-ops)
    for tid in task_ids:
        try:
            _octo_post("/api/task/RemoveDataByTaskId", params={"taskId": tid})
            time.sleep(2)  # Give Octoparse time to commit the clear
            _octo_post("/api/task/StartTask", params={"taskId": tid})
        except Exception as e:
            print("StartTask error:", tid, e)

    print("Polling until all tasks are complete...")
    wait_for_tasks(task_ids)

    # 4) fetch data per task by offset paging
    #    We'll build an Excel workbook with one sheet per taskName.
    wb = Workbook()
    # openpyxl creates a default sheet; we will reuse it for the first task
    default_sheet_used = False

    for idx, t in enumerate(tasks):
        tid = t.get("taskId")
        tname = t.get("taskName") or f"Task_{idx+1}"
        # ensure a safe sheet title (max 31 chars, no []:*?/ etc.)
        safe_title = "".join(c for c in tname if c not in '[]:*?/\\').strip()
        if len(safe_title) == 0:
            safe_title = f"Task_{idx+1}"
        safe_title = safe_title[:31]

        # accumulate rows (dicts) for this task
        all_rows = []
        ofs = offset
        while True:
            data_res = _octo_get("/api/alldata/GetDataOfTaskByOffset", params={"taskId": tid, "offset": ofs, "size": size})
            if data_res.status_code != 200:
                print("Data fetch error:", tid, data_res.text)
                break
            payload = data_res.json() or {}
            data = payload.get("data", {})
            items = data.get("dataList", []) or []
            if not items:
                break
            all_rows.extend(items)
            ofs += len(items)
            if len(items) < size:
                break  # reached the end

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
            headers.update(r.keys())
        headers = list(headers) if headers else ["id", "title", "companyName", "location", "jobUrl"]
        ws.append(headers)

        for r in all_rows:
            ws.append([r.get(h, "") for h in headers])

    # 5) stream workbook as an .xlsx download
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    try:
        wb.save(tmp.name)
        tmp.flush()
        tmp.seek(0)
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"jobpulse_octoparse_tasks_{task_group_id}_{ts}.xlsx"
        return send_file(tmp.name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True,
                         download_name=filename)
    finally:
        try:
            tmp.close()
        except:
            pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=1112)
