"""Export CDGC technical assets via the CDGC Bulk Export API.

Usage:
    python export_technical_assets.py [--out <folder>] [--query "Technical Assets"] [--file-type EXCEL]
                                      [--file-name NAME] [--summary-views all]
                                      [--config idmc_config.properties]

Authenticates from idmc_config.properties like the other export scripts, then:
  1. POST /data360/search/export/v1/assets?knowledgeQuery=Technical Assets&segments=all
          &fileName=...&summaryViews=all&fileType=EXCEL       (body {"size": 0} = all matches)
  2. GET  /data360/observable/v1/jobs/{jobId}                 until the job finishes
  3. GET  /data360/observable/v1/jobs/{jobId}/outputProperties/files/{key}
and saves the file to the export folder (--out, else exportFolder from the config, else ./export).
"""
import argparse
import time

from idmc_client import add_export_args, run_export


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", default="Technical Assets", help='CDGC search query (default: "Technical Assets")')
    add_export_args(ap, "Export_Technical_Assets_<unix timestamp>")
    args = ap.parse_args()
    # The export file and its log share one name, e.g. Export_Technical_Assets_1792505693(.xlsx/.log)
    run_export("export_technical_assets", args, args.query,
               args.file_name or f"Export_Technical_Assets_{int(time.time())}")


if __name__ == "__main__":
    main()
