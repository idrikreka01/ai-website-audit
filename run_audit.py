#!/usr/bin/env python3
import json
import sys
import urllib.error
import urllib.request

ENDPOINT = "http://localhost:8000/audits"


def main() -> None:
    url = input("Enter URL: ").strip()
    if not url:
        print("No URL given.", file=sys.stderr)
        sys.exit(1)

    body = json.dumps({"url": url, "mode": "standard"}).encode("utf-8")

    req = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            print(f"Status: {resp.status}")
            try:
                print(json.dumps(json.loads(raw), indent=2))
            except json.JSONDecodeError:
                print(raw)

    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"HTTP Error {e.code}", file=sys.stderr)
        print(err, file=sys.stderr)
        sys.exit(1)

    except urllib.error.URLError as e:
        print(f"Request failed: {e.reason}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
