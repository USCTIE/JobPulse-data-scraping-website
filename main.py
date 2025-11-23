import time
import os
import requests
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

app = Flask(__name__)

OCTOPARSE_API_TIER = "advanced"
BASE_URL = "https://advancedapi.octoparse.com"
USERNAME = os.getenv("OCTOPARSE_USERNAME")
PASSWORD = os.getenv("OCTOPARSE_PASSWORD")

# Manage login token
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
            return None, 400

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
    print("\n🔍 [DEBUG] Octoparse API response:")
    print(res)
    """Convert requests.Response into Flask JSON or error."""
    if res.status_code != 200:
        return jsonify({"error": res.text}), res.status_code
    try:
        return jsonify(res.json())
    except Exception:
        return res.text, res.status_code


# --- Routes ---
@app.route("/login", methods=["GET"])
def login():
    """Obtain and cache a new Octoparse access token."""
    err, status = token_mgr._fetch_with_password()
    if status != 200:
        return jsonify({"error": err}), status

    return jsonify({
        "access_token": token_mgr.access_token,
        "expires_at": token_mgr.expires_at
    })


@app.route("/task-groups", methods=["GET"])
def list_task_groups():
    res = requests.get(f"{BASE_URL}/api/TaskGroup", headers=token_mgr.headers(), timeout=30)
    return _handle_response(res)


@app.route("/tasks", methods=["GET"])
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


@app.route("/task/<task_id>/start", methods=["POST"])
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


@app.route("/task/<task_id>/stop", methods=["POST"])
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


@app.route("/tasks/status", methods=["POST"])
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


@app.route("/task/<task_id>/data/by-offset", methods=["GET"])
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


if __name__ == "__main__":
    app.run()
