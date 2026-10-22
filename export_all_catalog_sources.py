"""Export all CDGC catalog sources to a JSON file.

Usage:
    python export_all_catalog_sources.py [--out <folder>] [--sort name:ASC]
                                         [--filter ColumnName:Operator:Value] [--custom]
                                         [--config idmc_config.properties]

Authenticates from idmc_config.properties like the other export scripts, then pages through
GET /data360/catalog-source-management/v1/catalogsources until every catalog source
is fetched, and saves them as one JSON document ({"metadata", "catalogSources"}) to
the export folder (--out, else exportFolder from the config, else ./export).
"""
import argparse
import json
import os
import time

from idmc_client import DEFAULT_CONFIG, Cdgc, die
from run_log import RunLog


def fetch_all(cdgc, page_size, sort, filter_, custom):
    sources, offset, metadata, partial = [], 0, {}, False
    while True:
        params = {"offset": offset, "limit": page_size, "sort": sort}
        if filter_:
            params["filter"] = filter_
        if custom:
            params["custom"] = "true"
        r = cdgc.s.get(f"{cdgc.api}/data360/catalog-source-management/v1/catalogsources", params=params)
        page = cdgc._check(r, "Catalog Source API").json()
        metadata = metadata or page.get("metadata", {})
        partial = partial or page.get("metadata", {}).get("partialResult", False)
        batch = page.get("catalogSources", [])
        sources.extend(batch)
        offset += len(batch)
        total = page.get("metadata", {}).get("filterElements", 0)
        print(f"  fetched {offset}/{total}")
        if not batch or offset >= total:
            break
    if len(sources) != metadata.get("filterElements", len(sources)):
        print(f"  warning: expected {metadata.get('filterElements')} catalog sources, got {len(sources)}")
    return {"metadata": {**metadata, "partialResult": partial}, "catalogSources": sources}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="folder to save the JSON file to, created if missing "
                                  "(default: exportFolder from the config file, else ./export)")
    ap.add_argument("--sort", default="name:ASC", help="sort order, ASC or DESC (default: name:ASC)")
    ap.add_argument("--filter", help="filter as ColumnName:Operator:Value")
    ap.add_argument("--custom", action="store_true", help="include custom catalog sources")
    ap.add_argument("--page-size", type=int, default=25, help="catalog sources per request (default: 25)")
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="config file (default: idmc_config.properties next to this script)")
    args = ap.parse_args()
    if args.page_size < 1:
        die("--page-size must be at least 1")

    # The JSON file and its log share one name, e.g. Export_Catalog_Sources_1792505693(.json/.log)
    file_name = f"Export_Catalog_Sources_{int(time.time())}"
    with RunLog("export_all_catalog_sources", args.config, file_name) as log:
        with log.task("Authenticate") as t:
            cdgc = Cdgc(args.config)
            print(f"Org: {cdgc.org_name} ({cdgc.org_id})")
            t["result"] = f"{cdgc.auth_mode}; org {cdgc.org_name} ({cdgc.org_id})"

        with log.task("Fetch catalog sources") as t:
            print("Fetching catalog sources")
            result = fetch_all(cdgc, args.page_size, args.sort, args.filter, args.custom)
            m = result["metadata"]
            t["result"] = (f"{len(result['catalogSources'])} fetched of {m.get('filterElements')} matching "
                           f"({m.get('totalElements')} total), partialResult={m.get('partialResult')}")

        with log.task("Save JSON file") as t:
            out = args.out or cdgc.export_folder
            os.makedirs(out, exist_ok=True)
            path = os.path.abspath(os.path.join(out, f"{file_name}.json"))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(result['catalogSources'])} catalog sources to {path}")
            t["result"] = f"{path} ({os.path.getsize(path):,} bytes)"


if __name__ == "__main__":
    main()
