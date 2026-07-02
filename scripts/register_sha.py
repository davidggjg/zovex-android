"""
Called during the GitHub Actions build to:
1. Register the release SHA-1 with Firebase (for google-services.json)
2. Write google-services.json (from Firebase or static fallback)
3. Create a Firebase iOS app if missing → extract the iOS OAuth CLIENT_ID
   so Chrome Custom Tabs sign-in can use a custom-scheme redirect URI that
   Google actually accepts (unlike the WEB client which rejects custom schemes).
"""
import base64
import json
import os
import re
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
    ["keytool", "-list", "-v",
     "-keystore", "android/app/zovex-release.keystore",
     "-alias", "zovex-key", "-storepass", "zovex2026"],
    capture_output=True, text=True,
)
if r.returncode != 0:
    print(f"keytool failed: {r.stderr}")
    fallback()
    sys.exit(0)

sha1_raw = None
for line in r.stdout.split("\n"):
    if "SHA1:" in line:
        sha1_raw = line.split("SHA1:")[1].strip()
        break

if not sha1_raw:
    print("SHA1 line not found in keytool output")
    fallback()
    sys.exit(0)

sha1_hex = sha1_raw.replace(":", "").replace(" ", "").upper()
if len(sha1_hex) != 40:
    print(f"Unexpected SHA-1 length: {sha1_raw!r}")
    fallback()
    sys.exit(0)

sha1_formatted = ":".join(sha1_hex[i:i+2] for i in range(0, 40, 2))
print(f"Release SHA-1: {sha1_formatted}")

# --- 2. Firebase: register SHA-1 + write google-services.json ---
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

    def api(url, data=None, method=None):
        m = method or ("POST" if data is not None else "GET")
        req = urllib.request.Request(url, data=data, headers=hdrs, method=m)
        return json.loads(urllib.request.urlopen(req).read())

    # Find Android app
    resp = api(f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps")
    app_id = next(
        (a["appId"] for a in resp.get("apps", []) if a.get("packageName") == "com.zovexapp"),
        None,
    )
    if not app_id:
        raise RuntimeError("com.zovexapp not found in Firebase project")
    print(f"Firebase Android appId: {app_id}")

    # Register SHA-1 (idempotent — ignore 409)
    sha_list = api(f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/sha")
    already = any(
        c.get("shaHash", "").replace(":", "").upper() == sha1_hex
        for c in sha_list.get("certificates", [])
    )
    if already:
        print("SHA-1 already registered")
    else:
        try:
            api(
                f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/sha",
                data=json.dumps({"shaHash": sha1_formatted, "certType": "SHA_1"}).encode(),
            )
            print(f"SHA-1 registered: {sha1_formatted}")
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print("SHA-1 already registered (409)")
            else:
                raise

    # Write google-services.json from Firebase (may or may not have Android OAuth client)
    cfg = api(
        f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/config"
    )
    gs_json = base64.b64decode(cfg["configFileContents"]).decode()
    with open("android/app/google-services.json", "w") as f:
        f.write(gs_json)
    print("google-services.json written from Firebase")

    # --- 3. Create Firebase iOS app if missing → get iOS OAuth CLIENT_ID ---
    print("=== Setting up iOS OAuth client for Chrome Custom Tabs ===")
    ios_resp = api(f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/iosApps")
    ios_apps = ios_resp.get("apps", [])
    ios_app = next(
        (a for a in ios_apps if a.get("bundleId") == "com.zovexapp"),
        None,
    )

    if not ios_app:
        print("Creating Firebase iOS app for bundle ID com.zovexapp ...")
        op = api(
            f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/iosApps",
            data=json.dumps({"bundleId": "com.zovexapp", "displayName": "ZOVEX"}).encode(),
        )
        op_name = op.get("name", "")
        print(f"  Operation: {op_name}")

        for attempt in range(24):
            time.sleep(5)
            try:
                op = api(f"https://firebase.googleapis.com/v1beta1/{op_name}")
            except Exception as poll_err:
                print(f"  Poll {attempt + 1} error: {poll_err}")
            print(f"  Poll {attempt + 1}/24 — done={op.get('done', False)}")
            if op.get("done"):
                break

        if not op.get("done"):
            raise RuntimeError("iOS app creation timed out after 2 minutes")

        ios_app = op.get("response", {})
        print(f"  iOS app created: appId={ios_app.get('appId', '?')}")
    else:
        print(f"  iOS app found: appId={ios_app.get('appId', '?')}")

    ios_app_id = ios_app["appId"]

    # Get iOS plist config
    ios_cfg = api(
        f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/iosApps/{ios_app_id}/config"
    )
    plist_str = base64.b64decode(ios_cfg["configFileContents"]).decode()

    # Extract CLIENT_ID (the iOS OAuth client ID)
    match = re.search(r"<key>CLIENT_ID</key>\s*<string>(.*?)</string>", plist_str)
    if not match:
        raise RuntimeError("CLIENT_ID not found in iOS plist — OAuth client may not be provisioned yet")

    ios_client_id = match.group(1)
    # CLIENT_ID looks like "1095467813314-xxxx.apps.googleusercontent.com"
    # Scheme: "com.googleusercontent.apps.1095467813314-xxxx"
    scheme_id = ios_client_id.replace(".apps.googleusercontent.com", "")
    ios_scheme = f"com.googleusercontent.apps.{scheme_id}"

    print(f"  iOS CLIENT_ID: {ios_client_id}")
    print(f"  iOS scheme:    {ios_scheme}")

    with open("ios_oauth.txt", "w") as f:
        f.write(f"{ios_client_id}\n{ios_scheme}\n")
    print("  Wrote ios_oauth.txt — build will apply iOS client ID to source files")

except Exception as exc:
    print(f"Firebase step failed: {exc}")
    traceback.print_exc()
    print("Falling back to static google-services.json")
    fallback()
