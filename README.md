# IDMC / CDGC export scripts

Python scripts that export metadata from Informatica IDMC / Cloud Data Governance and Catalog (CDGC)
through the public REST APIs. Each run writes the exported file to an export folder and a log file
(tasks, results, status, execution time) to a log folder, both named after the run, e.g.
`export/Export_Business_Assets_1792505693.xlsx` and `logs/Export_Business_Assets_1792505693.log`.

| Script | Exports | API |
|---|---|---|
| `export_business_assets.py` | All business assets (with stakeholders and relationships) as Excel | CDGC Bulk Export (`knowledgeQuery=Business Assets`) |
| `export_technical_assets.py` | All technical assets as Excel (large orgs: a zip of several workbooks) | CDGC Bulk Export (`knowledgeQuery=Technical Assets`) |
| `export_technical_assets_for_single_catalog.py` | Technical assets of one catalog source | CDGC Bulk Export (`Technical Assets with catalog source name "<name>"`) |
| `export_all_catalog_sources.py` | All catalog sources as JSON | `GET /data360/catalog-source-management/v1/catalogsources` |
| `export_custom_roles_privileges.py` | Custom (non-system) roles with privileges as JSON; summary per role in the log | IICS v3 `GET /public/core/v3/roles` |

Shared code: `idmc_client.py` (config, authentication, API sessions, bulk export job flow) and
`run_log.py` (log files). `run_scheduled.sh` runs a script from cron or systemd on Linux
(see [Scheduling on Linux](#scheduling-on-linux)).

## Requirements

- Python 3.9 or newer (e.g. RHEL 9 `python3`, 3.9.x)
- `pip install -r requirements.txt` (only `requests`)
- Network access to the IDMC pod, e.g. `dm-em.informaticacloud.com`, `cdgc-api.dm-em.informaticacloud.com`
  and `emw1.dm-em.informaticacloud.com`
- An IDMC user with access to CDGC (Metadata Command Center / Data Governance and Catalog) and,
  for the roles export, permission to view roles in Administrator

## Configuration: `idmc_config.properties`

Copy `idmc_config.example.properties` to `idmc_config.properties` (the real file is not in version
control, as it can hold secrets). Plain `key=value` lines; `#` starts a comment; values are used as-is (no quotes).

| Key | Default | Meaning |
|---|---|---|
| `baseUrl` | `https://dm-em.informaticacloud.com` | IDMC pod login URL. The CDGC API host is derived from it: `https://cdgc-api.<host>` |
| `iics.baseApiUrl.v3` | `https://emw1.dm-em.informaticacloud.com/saas` | IICS v3 REST API base URL (roles export) |
| `proxy` | empty | HTTP(S) proxy for all API calls, e.g. `http://proxy.example.com:8080` or `http://user:password@proxy:8080`. Empty = `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY` environment variables, if set |
| `caBundle` | empty | CA certificate file (PEM) for verifying the API hosts' TLS certificates, e.g. when a proxy inspects TLS with a corporate CA. Empty = `REQUESTS_CA_BUNDLE` environment variable, else the CAs bundled with `requests` |
| `exportFolder` | `export` | Folder for exported files (relative to the current folder) |
| `logFolder` | `logs` | Folder for log files (relative to the current folder) |
| `username` | empty | If set, each run logs in (password: see [Password](#password)) and caches a fresh JWT in `jwtFile` |
| `password` | empty | Plain-text password; better leave empty and use one of the other password sources |
| `passwordFile` | empty | File containing only the password (relative paths: from the config file's folder) |
| `jwtFile` | `idmc_config.jwt` | Where the JWT of the last login is cached (relative paths: from the config file's folder); used for authentication when `username` is empty |

### Authentication

- **`username` set:** the script calls the User Login API
  (`POST {baseUrl}/identity-service/api/v1/Login`), exchanges the `sessionId` for a JWT via the User JWT
  API (`POST {baseUrl}/identity-service/api/v1/jwt/Token?client_id=idmc_api&nonce=1234`) and caches the
  JWT in `jwtFile` (default `idmc_config.jwt`, created with mode 600 on Linux). The config file itself is
  never written.
- **`username` empty:** the JWT in `jwtFile` is used, i.e. the one cached by an earlier login, or one you
  pasted into that file (only the token, on one line). The script stops with a clear message if it is
  missing or expired; set `username` or put a fresh JWT into the file.

The org ID and name are read from the JWT. The JWT is sent as `Authorization: Bearer` together with
`X-INFA-ORG-ID` (CDGC API) and as `INFA-SESSION-ID` (IICS v3 API).

### Proxy and certificates

`proxy` and `caBundle` in the config file take precedence over the environment variables. The log's
Authenticate task records which proxy (password masked) and CA bundle were used.

- Certificate error (`TLS certificate check failed ...`): the network replaces the server certificates,
  typically a TLS-inspecting proxy. Set `caBundle` to a PEM file containing that CA. On RHEL, add the
  corporate CA to the system trust store and point `caBundle` at it:
  ```bash
  sudo cp corporate-ca.pem /etc/pki/ca-trust/source/anchors/
  sudo update-ca-trust
  # idmc_config.properties: caBundle=/etc/pki/tls/certs/ca-bundle.crt
  ```
- Proxy errors while waiting for an export job are retried like other network errors until `--timeout`.

### Password

With `username` set, the password is taken from the first of these sources that is set. Logs and
console output name the source, never the password.

| # | Source | Use for |
|---|---|---|
| 1 | `password` in the config file | Avoid: plain text in a file that tends to get copied around |
| 2 | systemd credential `idmc_password` (`$CREDENTIALS_DIRECTORY/idmc_password`) | Linux + systemd timer: encrypted at rest, see [Step 4b](#step-4b-or-schedule-with-a-systemd-timer) |
| 3 | Environment variable `IDMC_PASSWORD` | Manual tests (see [Testing on Windows](#testing-on-windows)), systemd `EnvironmentFile=` |
| 4 | `passwordFile` | Linux + cron: a file readable only by the service user (`chmod 600`; a warning is printed otherwise) |
| 5 | Prompt (input hidden) | Manual runs in a terminal; never in cron, systemd or Task Scheduler |

Whatever the source, a script that runs unattended needs a password the server can read, so also: use a
dedicated IDMC user with only the roles the exports need, and keep the config, `jwtFile` and
`passwordFile` readable only by that user. A proxy password in `proxy` can be avoided the same way by
setting `HTTPS_PROXY` in the environment (cron/systemd) instead.

**Security:** log files never contain the password or JWT. The JWT cache file holds a token valid for a
few hours; keep it private like the password. `.gitignore` excludes `idmc_config.properties` and `*.jwt`.

## Usage

Run the scripts from the folder that should receive `export/` and `logs/`; the config file is
looked up next to the scripts unless `--config` is given. Every script supports `--help`.

```bash
python export_business_assets.py
python export_technical_assets.py                        # can take 30+ minutes
python export_technical_assets_for_single_catalog.py --catalog-source "xgong - Databricks Demo - Xgong - schema"
python export_all_catalog_sources.py [--filter ColumnName:Operator:Value] [--custom]
python export_custom_roles_privileges.py [--exclude-created-by USER ...]
```

Common options of the bulk export scripts (business / technical assets):

| Option | Default | Meaning |
|---|---|---|
| `--out` | `exportFolder` | Download folder |
| `--file-type` | `EXCEL` | `EXCEL` or `CSV` (CSV is delivered as a zip of CSV files) |
| `--file-name` | `Export_<...>_<unix timestamp>` | Export file name (also used for the log) |
| `--summary-views` | `all` | Summary sheets: `all`, `technical`, `business` |
| `--size` | `0` | Max assets; `0` exports every match |
| `--poll-interval` | `10` | Seconds between job status checks |
| `--timeout` | `7200` | Seconds to wait for the job |
| `--job-id` | | Resume an existing job instead of starting a new one (pass the same `--file-name`) |

`export_custom_roles_privileges.py` skips system roles (`systemRole: true`) and, by default, custom roles
created by `mdm-authorization` (provisioned by the MDM apps). `--exclude-created-by` with no value keeps
all custom roles.

## Logs

- `logs/<file name>.log`: written when the run ends, with status `SUCCESS` or `FAILED`, start/finish time,
  duration, each task with its result or error, and (roles export) a per-role summary.
- `logs/<file name>_in_progress.log`: while a bulk export job runs, rewritten every 2 minutes with the job
  status and timestamp; deleted once the final log is written. If it is still there, the run was killed;
  resume with `--job-id <job id from the log> --file-name <file name>`.

Network errors while waiting for a job are retried until `--timeout`; the job keeps running on the server.

## Testing in a new environment

1. Copy the folder (scripts, `requirements.txt`, `idmc_config.example.properties`), copy
   `idmc_config.example.properties` to `idmc_config.properties` and run `pip install -r requirements.txt`.
2. Edit `idmc_config.properties`: set `baseUrl` / `iics.baseApiUrl.v3` for your pod, then either
   `username` (password from one of the [password sources](#password), e.g. the prompt), or put a fresh JWT into
   `idmc_config.jwt`.
3. Smoke test with the fast scripts (a few seconds each):
   `python export_all_catalog_sources.py` and `python export_custom_roles_privileges.py`.
4. Then `python export_business_assets.py` (about 1.5 minutes) and, if needed, the technical asset exports.
5. Check `logs/` for `Status : SUCCESS` and `export/` for the files.

## Testing on Windows

The scripts run unchanged on Windows (Python 3.9+ from python.org or `winget install Python.Python.3.12`).
Use PowerShell, cmd or Windows Terminal; `run_scheduled.sh` is for Linux only.

```powershell
cd C:\path\to\idmc-cdgc-export
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item idmc_config.example.properties idmc_config.properties
notepad idmc_config.properties          # set username, leave password empty
```

Behind a TLS-inspecting corporate proxy, set `caBundle` to a PEM file of the corporate root CA (export it
from `certmgr.msc` as Base-64 X.509), e.g. `caBundle=C:\certs\corporate-ca.pem`. Paths in the config are used
as-is; backslashes are fine.

Pick one way to supply the password:

**A. Prompt (simplest):** just run a script and type the password; the input is hidden.

```powershell
.venv\Scripts\python export_all_catalog_sources.py
# IDMC password for <username>:
```

The prompt needs a console window. In Git Bash (mintty) the script stops with "no password" instead; use
PowerShell, or `winpty python ...`, or option B.

**B. Environment variable for the current window**, to run several scripts with one entry:

```powershell
$env:IDMC_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host 'IDMC password' -AsSecureString)).Password
.venv\Scripts\python export_custom_roles_privileges.py
.venv\Scripts\python export_business_assets.py
Remove-Item Env:IDMC_PASSWORD           # or close the window
```

**C. Password file readable only by you**, e.g. for Task Scheduler tests:

```powershell
$f = "$env:USERPROFILE\.idmc\password.txt"
New-Item -ItemType Directory -Force (Split-Path $f) | Out-Null
[Net.NetworkCredential]::new('', (Read-Host 'IDMC password' -AsSecureString)).Password |
    Set-Content -NoNewline -Encoding UTF8 $f
icacls $f /inheritance:r /grant:r "${env:USERNAME}:F"   # remove inherited access, keep only yours
# idmc_config.properties: passwordFile=C:\Users\<you>\.idmc\password.txt
```

The cached JWT (`idmc_config.jwt`) gets the permissions of the script folder, so keep the folder under your
user profile. After testing, delete the password file if you no longer need it.

## Scheduling on Linux

`run_scheduled.sh` wraps a script for unattended runs. It runs from the script folder, uses
`.venv/bin/python` if present, skips a run while the same script is still running (`flock`), appends
console output to `logs/scheduler.log` and returns the script's exit code (0 = success, 1 = failed).
Per-run details stay in `logs/<export name>.log` as usual.

### Step 1: Install the scripts

```bash
sudo useradd --system --create-home --shell /bin/bash idmc   # optional: dedicated service user
sudo unzip idmc-cdgc-export.zip -d /opt                        # creates /opt/idmc-cdgc-export
sudo chown -R idmc:idmc /opt/idmc-cdgc-export
sudo -iu idmc                                                  # continue as that user
cd /opt/idmc-cdgc-export
python3 -m venv .venv                                          # RHEL 9: built in; Debian/Ubuntu: apt install python3-venv
.venv/bin/pip install -r requirements.txt
chmod +x run_scheduled.sh
command -v flock || echo "install util-linux"                  # flock is part of util-linux
```

If you copied the files from Windows, convert line endings first: `sed -i 's/\r$//' run_scheduled.sh`.

### Step 2: Configure for unattended runs

A JWT expires after a few hours, so a scheduled job must log in itself. Copy
`idmc_config.example.properties` to `idmc_config.properties` and edit it:

```properties
baseUrl=https://dm-em.informaticacloud.com
iics.baseApiUrl.v3=https://emw1.dm-em.informaticacloud.com/saas
# absolute paths, so the location does not depend on the current folder
exportFolder=/opt/idmc-cdgc-export/export
logFolder=/opt/idmc-cdgc-export/logs
# only if the server needs them (see "Proxy and certificates")
proxy=http://proxy.example.com:8080
caBundle=/etc/pki/tls/certs/ca-bundle.crt
username=<IDMC service user>
password=
# cron: the password file below; systemd timer: leave empty and use the encrypted credential (Step 4b)
passwordFile=/home/idmc/.idmc/password
```

Keep the password out of the config. Create the password file as the `idmc` user; the input is hidden
and the file is readable only by `idmc`:

```bash
install -d -m 700 ~/.idmc
( umask 077; read -rsp "IDMC password: " p; echo; printf '%s' "$p" > ~/.idmc/password; unset p )
ls -l ~/.idmc/password                  # -rw------- idmc idmc
chmod 600 idmc_config.properties        # no secrets in it now, but it names the user and paths
```

Each login caches the JWT in `idmc_config.jwt` (mode 600) next to the config.

Use a dedicated IDMC user with only the roles the exports need, and a password that does not
expire (or a reminder to rotate it). Single sign-on (SAML) users cannot use the User Login API.

### Step 3: Test manually, exactly as the scheduler will run it

```bash
./run_scheduled.sh export_all_catalog_sources.py
echo "exit $?"                          # 0 = success
tail -n 20 logs/scheduler.log
grep -h '^Status' logs/Export_*.log     # SUCCESS
```

Cron runs with a minimal environment (no proxy variables, different PATH). Setting `proxy` and
`caBundle` in the config file avoids depending on environment variables. If the manual test only works
in your login shell, test with `env -i HOME="$HOME" PATH=/usr/bin:/bin ./run_scheduled.sh ...`.

On RHEL with SELinux enforcing, scheduled runs from `/opt` normally work. If a run works manually but
fails from cron or systemd, look for denials and restore default labels:

```bash
sudo ausearch -m avc -ts recent          # any denials for run_scheduled.sh / python?
sudo restorecon -Rv /opt/idmc-cdgc-export
```

### Step 4a: Schedule with cron

```bash
crontab -e     # as the idmc user
```

```cron
# m  h  dom mon dow  command
CRON_TZ=Europe/Berlin
MAILTO=""
# Every day: catalog sources 01:00, custom roles 01:10, business assets 01:20
0  1 * * *  /opt/idmc-cdgc-export/run_scheduled.sh export_all_catalog_sources.py
10 1 * * *  /opt/idmc-cdgc-export/run_scheduled.sh export_custom_roles_privileges.py
20 1 * * *  /opt/idmc-cdgc-export/run_scheduled.sh export_business_assets.py
# Sundays 02:00: all technical assets (can take 30+ minutes)
0  2 * * 0  /opt/idmc-cdgc-export/run_scheduled.sh export_technical_assets.py
# Every 6 hours: one catalog source (quote names with spaces)
0 */6 * * * /opt/idmc-cdgc-export/run_scheduled.sh export_technical_assets_for_single_catalog.py --catalog-source "xgong - Databricks Demo - Xgong - schema"
```

Notes:
- Stagger the start times; overlapping runs work, but each one logs in separately.
- `CRON_TZ` is supported by cronie (RHEL/Fedora) and recent Debian/Ubuntu cron; otherwise times are in
  the server time zone (`timedatectl`).
- `%` has a special meaning in crontab lines; escape it as `\%` if you add it to a command.
- Check that cron runs the jobs: `grep CRON /var/log/syslog` (Debian/Ubuntu) or
  `journalctl -u crond` (RHEL), then `logs/scheduler.log`.

### Step 4b: Or schedule with a systemd timer

Better logging (`journalctl`), runs missed while the server was off (`Persistent=true`), and failure
status in `systemctl`. One service + timer pair per script; example for business assets:

`/etc/systemd/system/idmc-export-business-assets.service`
```ini
[Unit]
Description=IDMC CDGC export: business assets
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=idmc
WorkingDirectory=/opt/idmc-cdgc-export
ExecStart=/opt/idmc-cdgc-export/run_scheduled.sh export_business_assets.py
TimeoutStartSec=3h
# IDMC password, encrypted at rest (see below); remove this line if you use passwordFile instead
LoadCredentialEncrypted=idmc_password:/etc/idmc/idmc_password.cred
```

The encrypted credential is the safest password store on RHEL 9 (systemd 252): the file can only be
decrypted on this server (host key, plus the TPM chip if present), and only for the service run, where the
script reads it from `$CREDENTIALS_DIRECTORY/idmc_password`. Create it once as root (input is hidden):

```bash
sudo install -d -m 700 /etc/idmc
sudo sh -c 'systemd-ask-password "IDMC password:" | systemd-creds encrypt --name=idmc_password - /etc/idmc/idmc_password.cred'
sudo chmod 600 /etc/idmc/idmc_password.cred
```

To change the password later, rerun the `systemd-creds encrypt` line. Then remove `passwordFile` from the
config and delete `~/.idmc/password`; the credential takes precedence anyway. The credential only exists for
systemd runs, so for manual tests (Step 3) run from a terminal and type the password at the prompt.

`/etc/systemd/system/idmc-export-business-assets.timer`
```ini
[Unit]
Description=Daily IDMC CDGC business asset export

[Timer]
OnCalendar=*-*-* 01:20:00
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now idmc-export-business-assets.timer
systemctl list-timers 'idmc-*'                          # next run time
sudo systemctl start idmc-export-business-assets.service # run once now to test
systemctl status idmc-export-business-assets.service     # last result
```

Other schedules: `OnCalendar=Sun *-*-* 02:00:00` (weekly), `OnCalendar=*-*-* 00/6:00:00` (every 6 hours);
check with `systemd-analyze calendar "Sun *-*-* 02:00:00"`. Proxy and CA file come from the config file
(`proxy`, `caBundle`); alternatively set `Environment=HTTPS_PROXY=...` / `Environment=REQUESTS_CA_BUNDLE=...`
in the `[Service]` section (cron: `HTTPS_PROXY=...` lines at the top of the crontab).

### Step 5: Clean up old files

Each run adds a file to `export/` and `logs/`. Remove files older than 30 days, e.g. daily at 03:00 in the
crontab:

```cron
0 3 * * *  find /opt/idmc-cdgc-export/export /opt/idmc-cdgc-export/logs -type f -name 'Export_*' -mtime +30 -delete
```

### Step 6: Monitor

- Failed runs: `grep -l '^Status     : FAILED' logs/Export_*.log`, or `grep 'exit [^0]' logs/scheduler.log`.
- A leftover `logs/*_in_progress.log` means a run was killed (server reboot, timeout); resume it with
  `--job-id` as described under Logs.
- For alerts, let your monitoring watch `logs/scheduler.log` for `(exit 1)`, or set `OnFailure=` in the
  systemd service to a notification unit.
