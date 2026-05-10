import requests
import json
import sys
from datetime import datetime

API_URL = "https://jsonplaceholder.typicode.com/posts/1"
OUTPUT_FILE = "output.json"

def fetch_api(url):
    try:
        response = requests.get(url, timeout=10)

        # 🔴 Handle HTTP errors (4xx, 5xx)
        response.raise_for_status()

        return response.json()

    except requests.exceptions.HTTPError as e:
        print(f"[HTTP ERROR] {e}")
        sys.exit(1)

    except requests.exceptions.ConnectionError:
        print("[CONNECTION ERROR] Failed to connect to API")
        sys.exit(1)

    except requests.exceptions.Timeout:
        print("[TIMEOUT ERROR] API request timed out")
        sys.exit(1)

    except requests.exceptions.RequestException as e:
        print(f"[UNKNOWN ERROR] {e}")
        sys.exit(1)


def write_output(data, file_path):
    try:
        # Add metadata (useful in DevOps pipelines)
        wrapped_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }

        with open(file_path, "w") as f:
            json.dump(wrapped_data, f, indent=4)

        print(f"[SUCCESS] Output written to {file_path}")

    except IOError as e:
        print(f"[FILE ERROR] Could not write file: {e}")
        sys.exit(1)


def main():
    print("[INFO] Calling API...")

    data = fetch_api(API_URL)

    print("[INFO] Writing output...")
    write_output(data, OUTPUT_FILE)


if __name__ == "__main__":
    main()