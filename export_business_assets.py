"""Export CDGC business assets (with stakeholders and relationships) via the CDGC Bulk Export API.

Usage:
    python export_business_assets.py [--out <folder>] [--query "Business Assets"] [--file-type EXCEL]
                                     [--file-name NAME] [--summary-views all] [--job-id ID]
                                     [--config idmc_config.properties]

Steps:
  1. Authenticate from the config file (baseUrl, username, jwtFile; see README "Password").
     If username is set, call the IDMC User Login API, exchange the sessionId for a
     JWT via the User JWT API, and cache the new JWT in jwtFile (idmc_config.jwt).
     Otherwise the JWT in jwtFile is used.
  2. Start a bulk export job:  POST /data360/search/export/v1/assets   (body {"size": 0} = all matches)
  3. Poll the job until done:  GET  /data360/observable/v1/jobs/{jobId}
  4. Download the export file: GET  /data360/observable/v1/jobs/{jobId}/outputProperties/files/{key}
"""
import argparse
import time

from idmc_client import add_export_args, run_export


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", default="Business Assets", help='CDGC search query (default: "Business Assets")')
    add_export_args(ap, "Export_Business_Assets_<unix timestamp>")
    args = ap.parse_args()
    # The export file and its log share one name, e.g. Export_Business_Assets_1792505693(.xlsx/.log)
    run_export("export_business_assets", args, args.query,
               args.file_name or f"Export_Business_Assets_{int(time.time())}")


if __name__ == "__main__":
    main()
