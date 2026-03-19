import os, json, re, pymysql

def get_conn():
    return pymysql.connect(
        host=os.getenv("DB_HOST","127.0.0.1"),
        user=os.getenv("DB_USER","root"),
        password=os.getenv("DB_PASSWORD",""),
        database=os.getenv("DB_NAME","jobpulse"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def upsert_job(cur, j):
    """
    Accepts an Octoparse item 'j' (dataList element) and upserts into jobs.
    We normalize common Octoparse fields into our schema.
    """
    sql = """
    INSERT INTO jobs (job_title, job_link, company, company_link, job_location, post_time,
                      applicant_count, job_description, industry, employment_type, valid_through,
                      seniority_level, job_function, hiring_person, min_pay, max_pay)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
      job_title=VALUES(job_title),
      company=VALUES(company),
      job_location=VALUES(job_location),
      post_time=VALUES(post_time),
      applicant_count=VALUES(applicant_count),
      job_description=VALUES(job_description),
      industry=VALUES(industry),
      employment_type=VALUES(employment_type),
      seniority_level=VALUES(seniority_level),
      job_function=VALUES(job_function),
      min_pay=VALUES(min_pay),
      max_pay=VALUES(max_pay)
    """
    cur.execute(sql, (
        j.get("title") or j.get("jobTitle") or j.get("JobTitle"),
        j.get("jobUrl") or j.get("job_link"),
        j.get("companyName") or j.get("company"),
        j.get("companyUrl") or j.get("company_link"),
        j.get("location") or j.get("job_location"),
        # NOTE: 'publishedAt' is often relative text (e.g., "2 weeks ago"). If you have
        # a parsed timestamp (like 'publishedAt_ts'), map it here; otherwise leave NULL.
        j.get("post_time") or j.get("publishedAt_ts") or None,
        j.get("ApplicationsCount") or j.get("applicant_count"),
        j.get("description") or j.get("job_description"),
        j.get("industry"),
        j.get("employment_type") or j.get("contractType"),
        j.get("valid_through"),
        j.get("seniority_level") or j.get("experienceLevel"),
        j.get("job_function"),
        j.get("posterFullName") or j.get("hiring_person"),
        j.get("min_pay"),
        j.get("max_pay"),
    ))

def _parse_int(val):
    if val is None:
        return None
    if isinstance(val, int):
        return val
    m = re.search(r'\d+', str(val))
    return int(m.group()) if m else None


def upsert_login_template_data(cur, j, scrape_date):
    sql = """
    INSERT INTO login_template_data (
        scrape_date, Input_URL, Keyword, Result_count_for_reference_only,
        Location, Current_Page, Current_Page_URL, Title, Title_URL,
        Image, Company, Date, About_the_job, Posted_time, Salary,
        People_applied, Job_preference_1, Job_preference_2,
        Job_preference_3, Job_preference_4, Company_URL,
        Company_follower, Company_size, Count_of_employee_onLinkedIn,
        Company_Intro
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    cur.execute(sql, (
        scrape_date,
        j.get("Input_URL"),
        j.get("Keyword"),
        _parse_int(j.get("Result_count_for_reference_only")),
        j.get("Location"),
        _parse_int(j.get("Current_Page")),
        j.get("Current_Page_URL"),
        j.get("Title"),
        j.get("Title_URL"),
        j.get("Image"),
        j.get("Company"),
        j.get("Date"),
        j.get("About_the_job"),
        j.get("Posted_time"),
        j.get("Salary"),
        j.get("People_applied"),
        j.get("Job_preference_1"),
        j.get("Job_preference_2"),
        j.get("Job_preference_3"),
        j.get("Job_preference_4"),
        j.get("Company_URL"),
        j.get("Company_follower"),
        j.get("Company_size"),
        j.get("Count_of_employee_onLinkedIn"),
        j.get("Company_Intro"),
    ))

def create_export_job(cur, task_group_id, selected_task_ids, task_group_name=None, task_names=None):
    # Insert a new export job row and return its id, `selected_task_ids` and `task_names` should be lists, Json is stored as text
    ids_json = json.dumps(selected_task_ids or [])
    names_json = json.dumps(task_names or []) if task_names is not None else None
    sql = """
    INSERT INTO exports (task_group_id, task_group_name, selected_task_ids, task_names, status)
    VALUES (%s, %s, %s, %s, 'queued')
    """
    cur.execute(sql, (task_group_id, task_group_name or None, ids_json, names_json))
    return cur.lastrowid


def update_export_job_status(cur, job_id, status=None, progress=None,
                             error=None, file_name=None, file_path=None):
    # Partial update of an export job row
    fields = []
    args = []
    if status is not None:
        fields.append("status=%s")
        args.append(status)
    if progress is not None:
        fields.append("progress=%s")
        args.append(progress)
    if error is not None:
        fields.append("error=%s")
        args.append(error)
    if file_name is not None:
        fields.append("file_name=%s")
        args.append(file_name)
    if file_path is not None:
        fields.append("file_path=%s")
        args.append(file_path)
    if not fields:
        return
    sql = f"UPDATE exports SET {', '.join(fields)} WHERE id=%s"
    args.append(job_id)
    cur.execute(sql, args)


def get_export_job(cur, job_id):
    cur.execute("SELECT * FROM exports WHERE id=%s", (job_id,))
    return cur.fetchone()


def list_export_jobs(cur, limit=100):
    # Return most recent export jobs (global view)
    cur.execute(
        "SELECT * FROM exports ORDER BY created_at DESC LIMIT %s",
        (int(limit),),
    )
    return cur.fetchall()


def get_local_backup_task_ids(cur):
    # """Return set of task_id strings for tasks that are local backup only
    cur.execute("SELECT task_id FROM local_backup_tasks")
    rows = cur.fetchall()
    return {str(r["task_id"]) for r in rows} if rows else set()


def add_local_backup_task_id(cur, task_id):
    # Add a task ID to local_backup_tasks
    cur.execute(
        "INSERT IGNORE INTO local_backup_tasks (task_id) VALUES (%s)",
        (str(task_id),),
    )
