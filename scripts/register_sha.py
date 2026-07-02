"""
Called during the GitHub Actions build to:
1. Extract the SHA-1 fingerprint from the release keystore
2. Register it with Firebase (so GoogleSignin works without DEVELOPER_ERROR)
3. Download the updated google-services.json from Firebase
Falls back to the static GOOGLE_SERVICES_JSON_BASE64 secret on any error.
"""
import base64
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request


def fallback():
    b64 = os.environ.get("GOOGLE_SERVICES_JSON_BASE64", "")
    if b64:
        with open("android/app/google-services.json", "wb") as f:
            f.write(base64.b64decode(b64))
        print("Wrote google-services.json from static secret (fallback)")
    else:
        print("WARNING: no GOOGLE_SERVICES_JSON_BASE64 secret found")


# --- 1. Extract SHA-1 from release keystore ---
print("=== Extracting SHA-1 from keystore ===")
r = subprocess.run(
    [
        "keytool", "-list", "-v",
        "-keystore", "android/app/zovex-release.keystore",
        "-alias", "zovex-key",
        "-storepass", "zovex2026",
    ],
    capture_output=True,
    text=True,
)

if r.returncode != 0:
    print(f"keytool failed (exit {r.returncode}):\n{r.stderr}")
    fallback()
    sys.exit(0)

# Print first few lines of keytool output for debugging
for line in r.stdout.split("\n")[:20]:
    print(f"  keytool: {line}")

sha1_raw = None
for line in r.stdout.split("\n"):
    if "SHA1:" in line:
        sha1_raw = line.split("SHA1:")[1].strip()
        break

if not sha1_raw:
    print("Could not find SHA1: line in keytool output — using static google-services.json")
    fallback()
    sys.exit(0)

# Normalize: remove spaces, ensure uppercase with colons (AA:BB:CC:...)
sha1_hex = sha1_raw.replace(":", "").replace(" ", "").upper()
if len(sha1_hex) != 40:
    print(f"Unexpected SHA-1 length {len(sha1_hex)} from {sha1_raw!r} — using static")
    fallback()
    sys.exit(0)

# Firebase API expects: AA:BB:CC:DD:... (uppercase hex pairs with colons)
sha1_formatted = ":".join(sha1_hex[i:i+2] for i in range(0, 40, 2))
print(f"Release SHA-1: {sha1_formatted}")

# --- 2. Register with Firebase and fetch updated google-services.json ---
try:
    from google.auth.transport.requests import Request as GReq
    from google.oauth2 import service_account

    sa = json.loads(os.environ["FIREBASE_SA_JSON"])
    project_id = sa["project_id"]
    print(f"Firebase project: {project_id}")

    creds = service_account.Credentials.from_service_account_info(
        sa,
        scopes=[
            "https://www.googleapis.com/auth/firebase",
            "https://www.googleapis.com/auth/cloud-platform",
        ],
    )
    creds.refresh(GReq())
    hdrs = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }

    def api(url, data=None):
        method = "POST" if data else "GET"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        return json.loads(urllib.request.urlopen(req).read())

    # Find the Android app ID for com.zovexapp
    resp = api(f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps")
    app_id = next(
        (a["appId"] for a in resp.get("apps", []) if a.get("packageName") == "com.zovexapp"),
        None,
    )
    if not app_id:
        raise RuntimeError("com.zovexapp not found in Firebase project")
    print(f"Firebase appId: {app_id}")

    # Register SHA-1 — Firebase expects AA:BB:CC:... format with colons
    try:
        api(
            f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/sha",
            data=json.dumps({"shaHash": sha1_formatted, "certType": "SHA_1"}).encode(),
        )
        print(f"SHA-1 registered with Firebase: {sha1_formatted}")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print(f"SHA-1 already registered — no change needed")
        else:
            raise

    # Download updated google-services.json — retry up to 4x waiting for Android client to appear
    gs_json = None
    android_client_found = False

    for attempt in range(4):
        if attempt > 0:
            print(f"Android client not in config yet, waiting 5s before retry {attempt + 1}...")
            time.sleep(5)

        cfg = api(
            f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/config"
        )
        gs_json = base64.b64decode(cfg["configFileContents"]).decode()
        gs_obj = json.loads(gs_json)

        print(f"  Attempt {attempt + 1} — oauth_clients in google-services.json:")
        for client_entry in gs_obj.get("client", []):
            for oc in client_entry.get("oauth_client", []):
                ctype = oc.get("client_type")
                cert = oc.get("android_info", {}).get("certificate_hash", "")
                client_id = oc.get("client_id", "")[:40]
                print(f"    type={ctype} cert={cert or '(none)'} id={client_id}...")
                if ctype == 1:
                    # Normalize cert hash for comparison
                    cert_norm = cert.replace(":", "").upper()
                    if cert_norm == sha1_hex:
                        android_client_found = True
                        print(f"    ^^^ MATCH — Android OAuth client with release SHA-1 found!")

        if android_client_found:
            break

    if not android_client_found:
        print("WARNING: No Android OAuth client matching release SHA-1 found in google-services.json")
        print("Google Sign-In may still fail with DEVELOPER_ERROR")

    with open("android/app/google-services.json", "w") as f:
        f.write(gs_json)
    print("google-services.json written from Firebase API")

except Exception as exc:
    print(f"Firebase step failed: {exc}")
    traceback.print_exc()
    print("Falling back to static google-services.json")
    fallback()
