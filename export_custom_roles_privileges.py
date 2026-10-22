"""Export all custom (non-system) IDMC roles with their privileges to a JSON file.

Usage:
    python export_custom_roles_privileges.py [--out <folder>] [--exclude-created-by USER ...]
                                             [--config idmc_config.properties]

Authenticates from idmc_config.properties like the other export scripts, then calls the IICS v3 API
(iics.baseApiUrl.v3 from the config):
  1. GET /public/core/v3/roles                                         all roles, keep systemRole == false,
                                                                       drop roles created by mdm-authorization
  2. GET /public/core/v3/roles?q=roleName=="<name>"&expand=privileges  for each custom role
and saves the roles with privileges as one JSON array to the export folder
(--out, else exportFolder from the config, else ./export). The log summarizes each role.
"""
import argparse
import json
import os
import time
from collections import Counter

from idmc_client import DEFAULT_CONFIG, Cdgc, die
from run_log import RunLog


def get_roles(cdgc, role_name=None):
    params = {"q": f'roleName=="{role_name}"', "expand": "privileges"} if role_name else None
    r = cdgc.v3.get(f"{cdgc.v3_api}/public/core/v3/roles", params=params)
    return cdgc._check(r, "Roles API").json()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder to save the JSON file to, created if missing "
                                  "(default: exportFolder from the config file, else ./export)")
    ap.add_argument("--exclude-created-by", nargs="*", default=["mdm-authorization"], metavar="USER",
                    help="skip custom roles created by these users (default: mdm-authorization, "
                         "i.e. roles provisioned by the MDM apps); pass with no value to keep all")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="config file (default: idmc_config.properties next to this script)")
    args = ap.parse_args()

    # The JSON file and its log share one name, e.g. Export_Custom_Roles_Privileges_1792505693(.json/.log)
    file_name = f"Export_Custom_Roles_Privileges_{int(time.time())}"
    with RunLog("export_custom_roles_privileges", args.config, file_name) as log:
        with log.task("Authenticate") as t:
            cdgc = Cdgc(args.config)
            print(f"Org: {cdgc.org_name} ({cdgc.org_id})")
            t["result"] = f"{cdgc.auth_mode}; org {cdgc.org_name} ({cdgc.org_id}); v3 API {cdgc.v3_api}"

        with log.task("Get all roles") as t:
            roles = get_roles(cdgc)
            non_system = [r for r in roles if r.get("systemRole") is False]
            excluded = {u.lower() for u in args.exclude_created_by}
            custom = sorted((r["roleName"] for r in non_system if (r.get("createdBy") or "").lower() not in excluded),
                            key=str.lower)
            skipped = len(non_system) - len(custom)
            by = ", ".join(args.exclude_created_by) or "nobody"
            print(f"{len(roles)} roles, {len(non_system)} custom (systemRole: false), "
                  f"{skipped} created by {by} skipped, {len(custom)} to export")
            t["result"] = (f"{len(roles)} roles, {len(roles) - len(non_system)} system, {len(non_system)} custom; "
                           f"{skipped} created by {by} excluded, {len(custom)} to export")

        with log.task("Get privileges of custom roles") as t:
            result = []
            for i, name in enumerate(custom, 1):
                matches = [r for r in get_roles(cdgc, name) if r.get("roleName") == name]
                if not matches:
                    die(f'role "{name}" not found when fetching its privileges')
                result.extend(matches)
                print(f"  {i}/{len(custom)} {name}: {len(matches[0].get('privileges') or [])} privileges")
            t["result"] = f"{len(result)} roles, {sum(len(r.get('privileges') or []) for r in result)} privileges"

        with log.task("Save JSON file") as t:
            out = args.out or cdgc.export_folder
            os.makedirs(out, exist_ok=True)
            path = os.path.abspath(os.path.join(out, f"{file_name}.json"))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(result)} custom roles to {path}")
            t["result"] = f"{path} ({os.path.getsize(path):,} bytes)"

        # Per-role summary for the log: status, privilege count and privileges per service
        width = max([len(r["roleName"]) for r in result] + [4])
        log.summary.append(f"{'Role':<{width}}  {'Status':<8}  {'Privileges':>10}  Services (privileges)")
        for r in result:
            privs = r.get("privileges") or []
            services = Counter(p.get("service") or "(no service)" for p in privs)
            log.summary.append(f"{r['roleName']:<{width}}  {r.get('status') or '':<8}  {len(privs):>10}  "
                               + ", ".join(f"{s} ({n})" for s, n in sorted(services.items())))
        disabled = [r["roleName"] for r in result if r.get("status") != "Enabled"]
        empty = [r["roleName"] for r in result if not r.get("privileges")]
        log.summary += ["", f"Custom roles: {len(result)}; not enabled: {', '.join(disabled) or 'none'}; "
                            f"without privileges: {', '.join(empty) or 'none'}"]


if __name__ == "__main__":
    main()
