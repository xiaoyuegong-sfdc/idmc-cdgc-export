"""Export the CDGC technical assets of one catalog source via the CDGC Bulk Export API.

Usage:
    python export_technical_assets_for_single_catalog.py --catalog-source "<catalog source name>"
                                      [--out <folder>] [--file-type EXCEL] [--file-name NAME]
                                      [--summary-views all] [--config idmc_config.properties]

Example:
    python export_technical_assets_for_single_catalog.py --catalog-source "xgong - Databricks Demo - Xgong - schema"

Same as export_technical_assets.py, but with the query
    Technical Assets with catalog source name "<catalog source name>"
The file and its log are named Export_Technical_Assets_<catalog source>_<unix timestamp>
(non-alphanumeric characters in the name replaced by "_").

Backup for export_technical_assets.py, which remains the standard technical asset export. Use this script only if
exporting the technical assets of all catalog sources runs into performance issues (e.g. the job takes too long or
times out); then export just the relevant catalog sources with it, one run per catalog source.
"""
import argparse
import re
import time

from idmc_client import add_export_args, die, run_export


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog-source", required=True, help="catalog source name, exactly as shown in CDGC")
    add_export_args(ap, "Export_Technical_Assets_<catalog source>_<unix timestamp>")
    args = ap.parse_args()
    name = args.catalog_source.strip()
    if not name or '"' in name:
        die("--catalog-source must be a non-empty name without double quotes")

    query = f'Technical Assets with catalog source name "{name}"'
    # The export file and its log share one name, e.g.
    # Export_Technical_Assets_xgong_Databricks_Demo_Xgong_schema_1792505693(.xlsx/.log)
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    run_export("export_technical_assets_for_single_catalog", args, query,
               args.file_name or f"Export_Technical_Assets_{safe}_{int(time.time())}")


if __name__ == "__main__":
    main()
