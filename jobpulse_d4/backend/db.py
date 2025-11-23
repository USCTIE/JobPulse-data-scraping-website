import os, pymysql

def get_conn():
    return pymysql.connect(
        host=os.getenv("DB_HOST","127.0.0.1"),
        user=os.getenv("DB_USER","root"),
        password=os.getenv("DB_PASS",""),
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
