---
name: idmc-cdgc-export
description: Export Informatica IDMC / CDGC metadata with the bundled Python scripts - business assets, technical assets (all or one catalog source), catalog sources, and custom roles with privileges. Use when the user asks to export, back up, list or summarize CDGC business/technical assets, catalog sources, or IDMC custom roles/privileges, or to authenticate against IDMC with the stored config.
---

# IDMC / CDGC export

Scripts live next to this file. Read `README.md` for all options; this file says how to run them well.

## Before running

1. Only Python 3.9+ is needed (standard library only); never `pip install` anything for these scripts.
2. If `idmc_config.properties` is missing, copy it from `idmc_config.example.properties`. Check it without
   revealing secrets. Never print, log or echo the `password` or `proxy` values, nor the content of the
   `passwordFile`, the JWT file (`*.jwt`) or `IDMC_PASSWORD`; mask them, e.g.
   `sed 's/^\(password\|proxy\)=..*/\1=***/' idmc_config.properties`.
3. Authentication: if `username` is set, the scripts log in and cache a new JWT in `jwtFile`
   (default `idmc_config.jwt`). The password comes from `password`, the systemd credential `idmc_password`,
   `IDMC_PASSWORD`, `passwordFile`, else a terminal prompt (README "Password"). You cannot answer the
   prompt: if a run stops with "no password", ask the user to run it themselves (`! python <script>`) or to
   set `IDMC_PASSWORD` / `passwordFile`; never ask them to type the password into the chat. Without
   `username`, the scripts use the JWT in `jwtFile`; a JWT is valid for a few hours. If a script fails
   with "JWT ... expired", ask the user to put a fresh JWT into that file or to set `username`, then rerun. Do not go looking
   for other credential files.
4. Network: `TLS certificate check failed` means a TLS-inspecting proxy; ask for its CA file and set
   `caBundle`. Connection or proxy errors: set `proxy` (never print proxy passwords).

## Which script

| Request | Command | Typical duration |
|---|---|---|
| Business assets / glossary | `python export_business_assets.py` | ~1.5 min |
| All technical assets | `python export_technical_assets.py` | 30+ min, run in the background |
| Technical assets of one catalog source | `python export_technical_assets_for_single_catalog.py --catalog-source "<exact name>"` | minutes |
| Catalog sources | `python export_all_catalog_sources.py` | seconds |
| Custom roles and privileges | `python export_custom_roles_privileges.py` | seconds |

- Catalog source names must match exactly; get them from the catalog sources export
  (`catalogSources[].name`) if unsure.
- Roles export excludes system roles and roles created by `mdm-authorization` by default;
  `--exclude-created-by` with no value includes them.
- Use `python -u` when running in the background so progress output is not buffered.

## After running

- Every run prints `Log written to <path>`; read that log and report `Status`, task results and the
  output file path. For roles, the log's Summary section lists each role with status, privilege count
  and privileges per service.
- Bulk exports: if the run was interrupted, `logs/<name>_in_progress.log` remains with the job id;
  resume with `--job-id <id> --file-name <name>` instead of starting a new job.
- Large technical exports arrive as a zip of several `.xlsx` (or `.csv`) files; list the zip contents
  rather than extracting everything.
- Do not delete exports or logs unless the user asks.

## Scheduling

For recurring runs on Linux, follow README.md "Scheduling on Linux": `run_scheduled.sh` via cron or a
systemd timer, with `username` in the config (a stored JWT expires) and the password in an encrypted systemd
credential (timer) or a `chmod 600` `passwordFile` (cron), not in the config. For tests on Windows, see
README.md "Testing on Windows".
