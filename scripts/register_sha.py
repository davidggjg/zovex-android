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

sha1 = None
for line in r.stdout.split("\n"):
    if "SHA1:" in line:
        sha1 = line.split("SHA1:")[1].strip().replace(":", "").replace(" ", "")
        break

if not sha1 or len(sha1) != 40:
    print("Could not extract SHA-1 from keystore — using static google-services.json")
    fallback()
    sys.exit(0)

print(f"Release SHA-1: {sha1}")

# --- 2. Register with Firebase and fetch updated google-services.json ---
try:
    from google.auth.transport.requests import Request as GReq
    from google.oauth2 import service_account

    sa = json.loads(os.environ["FIREBASE_SA_JSON"])
    project_id = sa["project_id"]

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

    # Register SHA-1 (409 = already registered, that's fine)
    try:
        api(
            f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/sha",
            data=json.dumps({"shaHash": sha1, "certType": "SHA_1"}).encode(),
        )
        print("SHA-1 registered with Firebase successfully")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("SHA-1 already registered — no change needed")
        else:
            raise

    # Download the now-updated google-services.json
    cfg = api(
        f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/config"
    )
    gs_json = base64.b64decode(cfg["configFileContents"]).decode()
    with open("android/app/google-services.json", "w") as f:
        f.write(gs_json)
    print("Updated google-services.json written from Firebase API")

except Exception as exc:
    print(f"Firebase step failed: {exc}")
    print("Falling back to static google-services.json")
    fallback()
