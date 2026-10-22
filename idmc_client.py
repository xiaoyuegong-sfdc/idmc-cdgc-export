"""Shared code for the IDMC / CDGC export scripts.

- Config:   load_config for idmc_config.properties (key=value, '#' comments)
- Secrets:  find_password (config, systemd credential, IDMC_PASSWORD, passwordFile, prompt); JWT cache file
- Auth:     login() = User Login API -> sessionId -> User JWT API -> JWT
- Network:  ApiSession applies the optional proxy and caBundle settings to every API call
- Cdgc:     authenticated sessions for the CDGC API (cdgc-api.<pod>) and the IICS v3 API
- Exports:  add_export_args / run_export = start a CDGC Bulk Export job, wait for it, download the file
"""
import base64
import getpass
import json
import os
import re
import stat
import sys
import time
from datetime import datetime, timezone

import requests

from run_log import RunLog

DEFAULT_BASE_URL = "https://dm-em.informaticacloud.com"
DEFAULT_BASE_API_URL_V3 = "https://emw1.dm-em.informaticacloud.com/saas"
DEFAULT_EXPORT_FOLDER = "export"  # relative to the current folder
DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "idmc_config.properties")
# Job statuses that mean the export is still in progress.
ACTIVE_STATUSES = {"CREATED", "QUEUED", "SUBMITTED", "PENDING", "STARTING", "RUNNING", "IN_PROGRESS"}
# Password sources besides the config file: systemd credential (LoadCredential[Encrypted]=idmc_password:...)
# and environment variable
PASSWORD_CREDENTIAL = "idmc_password"
PASSWORD_ENV = "IDMC_PASSWORD"


def die(msg):
    sys.exit(f"ERROR: {msg}")


def jwt_payload(token):
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def load_config(path):
    """Read key=value lines from a .properties file ('#' and '!' start comments)."""
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError as e:
        die(f"cannot read config file: {e}")
    cfg = {}
    for line in lines:
        line = line.strip()
        if line and line[0] not in "#!":
            key, sep, value = line.partition("=")
            if sep:
                cfg[key.strip()] = value.strip()
    cfg["baseUrl"] = (cfg.get("baseUrl") or DEFAULT_BASE_URL).rstrip("/")
    cfg["iics.baseApiUrl.v3"] = (cfg.get("iics.baseApiUrl.v3") or DEFAULT_BASE_API_URL_V3).rstrip("/")
    return cfg


def config_path(config_file, value):
    """Path setting from the config; relative paths are resolved from the config file's folder."""
    return os.path.join(os.path.dirname(os.path.abspath(config_file)), os.path.expanduser(value))


def read_secret(path, what):
    """Content of a secret file (password or JWT) without the trailing line break."""
    try:
        with open(path, encoding="utf-8-sig") as f:  # -sig: Windows PowerShell 5.1 writes UTF-8 with a BOM
            value = f.read().rstrip("\r\n")
    except OSError as e:
        die(f"cannot read {what}: {e}")
    if not value:
        die(f"{what} is empty: {path}")
    return value


def write_secret(path, value):
    """Write a secret file that only the current user can read (mode 600 on Linux).

    Written to a temp file and swapped in, so overlapping (e.g. scheduled) runs never see a half-written file.
    On Windows the file gets the permissions of its folder.
    """
    tmp = f"{path}.{os.getpid()}.tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        f.write(value + "\n")
    os.replace(tmp, path)


def warn_if_shared(path):
    if os.name == "posix" and os.stat(path).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"WARNING: {path} is accessible by other users; run: chmod 600 {path}")


def interactive():
    """True if someone can type a password: stdin is a terminal (on Windows a real console; NUL also counts as a tty)."""
    if not sys.stdin.isatty():
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt
    handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(ctypes.c_ulong())))


def find_password(cfg, config_file):
    """Password for the User Login API and a description of its source (for messages and logs).

    The first one set wins: password in the config file, systemd credential idmc_password, environment variable
    IDMC_PASSWORD, passwordFile, else a prompt when run from a terminal.
    """
    if cfg.get("password"):
        return cfg["password"], "config file"
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")  # set by systemd for LoadCredential[Encrypted]=
    if cred_dir and os.path.isfile(os.path.join(cred_dir, PASSWORD_CREDENTIAL)):
        return (read_secret(os.path.join(cred_dir, PASSWORD_CREDENTIAL), "systemd credential"),
                f"systemd credential {PASSWORD_CREDENTIAL}")
    if os.environ.get(PASSWORD_ENV):
        return os.environ[PASSWORD_ENV], f"environment variable {PASSWORD_ENV}"
    if cfg.get("passwordFile"):
        path = config_path(config_file, cfg["passwordFile"])
        password = read_secret(path, "passwordFile")
        warn_if_shared(path)
        return password, f"passwordFile {path}"
    if interactive():
        password = getpass.getpass(f"IDMC password for {cfg['username']}: ")
        if password:
            return password, "prompt"
    die(f"no password for {cfg['username']}: set passwordFile in {config_file}, the {PASSWORD_ENV} environment "
        f"variable or the systemd credential {PASSWORD_CREDENTIAL}, or run from a terminal to be prompted "
        "(leave username empty to use a JWT instead)")


def mask_url(url):
    """http://user:secret@proxy:8080 -> http://***@proxy:8080 (for logs and messages)."""
    return re.sub(r"//[^@/]+@", "//***@", url)


class ApiSession(requests.Session):
    """requests.Session that sends every call through the configured proxy and CA bundle.

    proxy:    http(s)://[user:password@]host:port for HTTP and HTTPS; empty = HTTPS_PROXY / HTTP_PROXY / NO_PROXY
              environment variables, if any
    caBundle: PEM file (or c_rehash'ed folder) of trusted CAs, e.g. a corporate TLS-inspection CA;
              empty = REQUESTS_CA_BUNDLE environment variable, else the CAs bundled with requests (certifi)
    The values are passed per request because requests lets environment variables override
    session-level proxies/verify; this way the config file always wins.
    """

    def __init__(self, cfg):
        super().__init__()
        self.net = {}
        if cfg.get("proxy"):
            self.net["proxies"] = {"http": cfg["proxy"], "https": cfg["proxy"]}
        if cfg.get("caBundle"):
            if not os.path.exists(cfg["caBundle"]):
                die(f"caBundle file not found: {cfg['caBundle']}")
            self.net["verify"] = cfg["caBundle"]

    def request(self, method, url, **kwargs):
        for key, value in self.net.items():
            kwargs.setdefault(key, value)
        try:
            return super().request(method, url, **kwargs)
        except requests.exceptions.SSLError as e:
            die(f"TLS certificate check failed for {url.split('?')[0]}: {e}. If a proxy inspects TLS, "
                "set caBundle in the config to its CA file (RHEL: /etc/pki/tls/certs/ca-bundle.crt)")
        except requests.exceptions.ProxyError as e:
            # still a ConnectionError, so Cdgc.wait() retries it; masked so proxy passwords never reach the log
            raise requests.ConnectionError(f"proxy error for {url.split('?')[0]}: {mask_url(str(e))}; "
                                           "check the proxy setting in the config") from None


def network_summary(cfg):
    proxy = mask_url(cfg["proxy"]) if cfg.get("proxy") else "none (environment)"
    return f"proxy {proxy}, CA bundle {cfg.get('caBundle') or 'default'}"


def login(session, base_url, username, password):
    """User Login API -> sessionId, then User JWT API -> JWT."""
    r = session.post(f"{base_url}/identity-service/api/v1/Login",
                      json={"username": username, "password": password},
                      headers={"Content-Type": "application/json", "Accept": "application/json"},
                      timeout=60)
    if not r.ok:
        die(f"User Login API failed ({r.status_code}): {r.text[:300]}")
    session_id = r.json().get("sessionId")
    if not session_id:
        die(f"User Login API response has no sessionId (keys: {', '.join(r.json())})")

    r = session.post(f"{base_url}/identity-service/api/v1/jwt/Token",
                      params={"client_id": "idmc_api", "nonce": "1234"},
                      headers={"cookie": f"USER_SESSION={session_id}", "IDS-SESSION-ID": session_id,
                               "Accept": "application/json"},
                      timeout=60)
    if not r.ok:
        die(f"User JWT API failed ({r.status_code}): {r.text[:300]}")
    body = r.json()
    jwt = next((body[k] for k in ("jwt_token", "jwt", "access_token", "token") if body.get(k)), None)
    if not jwt:
        die(f"User JWT API response has no token (keys: {', '.join(body)})")
    return jwt


class Cdgc:
    def __init__(self, config_file):
        cfg = load_config(config_file)
        base_url = cfg["baseUrl"]
        # the JWT of the last login goes to its own file (default idmc_config.jwt), so the config holds no secrets
        jwt_file = config_path(config_file, cfg.get("jwtFile") or
                               os.path.splitext(os.path.basename(config_file))[0] + ".jwt")
        if cfg.get("username"):
            password, source = find_password(cfg, config_file)
            print(f"Logging in to {base_url} as {cfg['username']} (password from {source})")
            cfg["jwt"] = login(ApiSession(cfg), base_url, cfg["username"], password)
            write_secret(jwt_file, cfg["jwt"])
            print(f"  new JWT saved to {jwt_file}")
            self.auth_mode = f"logged in as {cfg['username']} (password from {source}), new JWT saved to {jwt_file}"
        elif cfg.get("jwt"):
            self.auth_mode = f"using JWT from {config_file}"
        elif os.path.isfile(jwt_file):
            cfg["jwt"] = read_secret(jwt_file, "JWT file")
            self.auth_mode = f"using JWT from {jwt_file}"
        else:
            die(f"{config_file}: set username (password sources: see README), or jwt")

        payload = jwt_payload(cfg["jwt"])
        if payload["exp"] <= time.time():
            die(f"JWT ({self.auth_mode}) expired at "
                f"{datetime.fromtimestamp(payload['exp'], timezone.utc):%Y-%m-%d %H:%M:%S} UTC; "
                "paste a fresh JWT or set username")
        self.auth_mode += f"; {network_summary(cfg)}"
        self.export_folder = cfg.get("exportFolder") or DEFAULT_EXPORT_FOLDER
        self.org_id = payload.get("current_org_id") or payload["org_id"]
        self.org_name = payload.get("current_org_name") or payload.get("org_name", "")
        # https://dm-em.informaticacloud.com -> https://cdgc-api.dm-em.informaticacloud.com
        self.api = f"https://cdgc-api.{base_url.split('://', 1)[1]}"
        self.s = ApiSession(cfg)
        self.s.headers.update({"Authorization": f"Bearer {cfg['jwt']}",
                               "X-INFA-ORG-ID": self.org_id,
                               "Accept": "application/json"})
        # IICS v3 REST API (e.g. /public/core/v3/roles) accepts the same JWT as INFA-SESSION-ID / Bearer token
        self.v3_api = cfg["iics.baseApiUrl.v3"]
        self.v3 = ApiSession(cfg)
        self.v3.headers.update({"INFA-SESSION-ID": cfg["jwt"], "Authorization": f"Bearer {cfg['jwt']}",
                                "Content-Type": "application/json", "Accept": "application/json"})

    def _check(self, r, what):
        if r.status_code == 401:
            die(f"{what}: token rejected (401); refresh it and rerun")
        if not r.ok:
            die(f"{what} failed ({r.status_code}): {r.text[:300]}")
        return r

    def start_export(self, query, file_name, summary_views, size, file_type=None):
        params = {"knowledgeQuery": query, "segments": "all",
                  "fileName": file_name, "summaryViews": summary_views}
        if file_type:  # CSV or EXCEL; the API defaults to EXCEL
            params["fileType"] = file_type
        r = self.s.post(f"{self.api}/data360/search/export/v1/assets", params=params,
                        json={"size": size})  # size 0 (no "from") exports every match
        return self._check(r, "Export API").json()["jobId"]

    def job(self, job_id):
        r = self.s.get(f"{self.api}/data360/observable/v1/jobs/{job_id}",
                       params=[("expandChildren", "TASK-HIERARCHY"), ("expandChildren", "OUTPUT-PROPERTIES")])
        return self._check(r, "Job Monitoring API").json()

    def wait(self, job_id, interval, timeout, on_poll=None):
        """Poll until the job leaves the active statuses; on_poll(status, elapsed_seconds) is called after every poll."""
        start, last = time.time(), None
        while True:
            try:
                job = self.job(job_id)
            except (requests.ConnectionError, requests.Timeout) as e:
                # network blips (e.g. DNS failures) must not abort a long wait; the job keeps running server-side
                if time.time() - start > timeout:
                    raise
                print(f"  [{time.time() - start:5.0f}s] connection error, retrying: {type(e).__name__}")
                if on_poll:
                    on_poll(f"{last} (connection error, retrying)", time.time() - start)
                time.sleep(interval)
                continue
            status = job.get("status")
            if status != last:
                print(f"  [{time.time() - start:5.0f}s] {status}")
                last = status
            if on_poll:
                on_poll(status, time.time() - start)
            if status not in ACTIVE_STATUSES:
                return job
            if time.time() - start > timeout:
                die(f"job {job_id} still {status} after {timeout}s; check it in Metadata Command Center")
            time.sleep(interval)

    def download(self, job_id, key, folder):
        r = self.s.get(f"{self.api}/data360/observable/v1/jobs/{job_id}/outputProperties/files/{key}",
                       headers={"Accept": "*/*"}, stream=True)
        self._check(r, "Download File API")
        m = re.search(r'filename="?([^";]+)"?', r.headers.get("content-disposition", ""))
        path = os.path.join(folder, os.path.basename(m.group(1)) if m else f"{key}_{job_id}")
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        return path


def add_export_args(ap, file_name_help):
    """Options shared by the bulk export scripts."""
    ap.add_argument("--out", help="folder to download the export file to, created if missing "
                                  "(default: exportFolder from the config file, else ./export)")
    ap.add_argument("--file-type", default="EXCEL", type=str.upper, choices=["CSV", "EXCEL"],
                    help="export file format (default: EXCEL; CSV gives a zip of CSV files)")
    ap.add_argument("--file-name", help=f"export file name (default: {file_name_help})")
    ap.add_argument("--summary-views", default="all", help="additional summary sheets: all, technical, business")
    ap.add_argument("--size", type=int, default=0, help="max assets to export (default: 0 = all matching assets)")
    ap.add_argument("--poll-interval", type=int, default=10, help="seconds between job status checks")
    ap.add_argument("--timeout", type=int, default=7200, help="seconds to wait for the job to finish (default: 7200)")
    ap.add_argument("--job-id", help="resume an export job that was already started (skips starting a new one); "
                                     "pass its --file-name too so the log keeps the same name")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="config file (default: idmc_config.properties next to this script)")


def run_export(script, args, query, file_name):
    """Start (or resume) the export of query, wait for it and download the file; logs as logs/<file_name>.log."""
    with RunLog(script, args.config, file_name) as log:
        with log.task("Authenticate") as t:
            cdgc = Cdgc(args.config)
            print(f"Org: {cdgc.org_name} ({cdgc.org_id})")
            t["result"] = f"{cdgc.auth_mode}; org {cdgc.org_name} ({cdgc.org_id})"

        if args.job_id:
            job_id = args.job_id
            print(f"Resuming job {job_id}")
        else:
            with log.task("Start bulk export job") as t:
                print(f'Starting {args.file_type} export of "{query}" as {file_name}')
                job_id = cdgc.start_export(query, file_name, args.summary_views, args.size, args.file_type)
                print(f"  job {job_id}")
                t["result"] = f'query "{query}", type {args.file_type}, file {file_name}, job {job_id}'

        with log.task("Wait for job completion") as t:
            job = cdgc.wait(job_id, args.poll_interval, args.timeout,
                            on_poll=lambda status, elapsed: log.progress(f"job {job_id} {status}", elapsed))
            t["result"] = f"job status {job.get('status')}"
            if job.get("status") != "COMPLETED":
                failed = [f"{x.get('name')}: {x.get('status')}" for x in job.get("tasks", [])]
                die(f"job {job_id} ended with status {job.get('status')} ({'; '.join(failed)})")

        with log.task("Download export file") as t:
            files = [p["name"] for p in job.get("outputProperties", []) if p.get("type") == "FILE"]
            if not files:
                die(f"job {job_id} completed but has no output file")
            out = args.out or cdgc.export_folder
            os.makedirs(out, exist_ok=True)
            saved = []
            for key in files:
                path = os.path.abspath(cdgc.download(job_id, key, out))
                saved.append(f"{path} ({os.path.getsize(path):,} bytes)")
                print(f"Downloaded {path}")
            t["result"] = "; ".join(saved)
