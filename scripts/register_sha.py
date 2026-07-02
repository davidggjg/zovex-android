"""
Called during the GitHub Actions build to:
1. Extract the SHA-1 fingerprint from the release keystore
2. Delete + re-add it in Firebase (triggers Android OAuth client creation)
3. Wait up to 90s for the Android OAuth client to appear in google-services.json
4. Falls back to the static GOOGLE_SERVICES_JSON_BASE64 secret on any error.
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

# --- 2. Firebase: delete existing SHA-1 entry then re-add to trigger OAuth client creation ---
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

    # Find the Android app ID for com.zovexapp
    resp = api(f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps")
    app_id = next(
        (a["appId"] for a in resp.get("apps", []) if a.get("packageName") == "com.zovexapp"),
        None,
    )
    if not app_id:
        raise RuntimeError("com.zovexapp not found in Firebase project")
    print(f"Firebase appId: {app_id}")

    # List existing SHA certificates
    sha_list = api(f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/sha")
    existing = sha_list.get("certificates", [])
    print(f"Existing SHA certificates: {len(existing)}")

    # Delete any existing SHA-1 with our fingerprint (delete+re-add triggers OAuth client creation)
    for cert in existing:
        cert_name = cert.get("name", "")
        cert_hash = cert.get("shaHash", "")
        cert_normalized = cert_hash.replace(":", "").upper()
        if cert_normalized == sha1_hex:
            print(f"Deleting existing SHA-1 entry: {cert_name}")
            try:
                req = urllib.request.Request(
                    f"https://firebase.googleapis.com/v1beta1/{cert_name}",
                    headers=hdrs,
                    method="DELETE",
                )
                urllib.request.urlopen(req).read()
                print("Deleted successfully")
            except Exception as del_exc:
                print(f"Delete failed: {del_exc}")
            time.sleep(2)
            break

    # Add the SHA-1 (this triggers Android OAuth client creation in Google Cloud Console)
    print(f"Adding SHA-1: {sha1_formatted}")
    try:
        result = api(
            f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/sha",
            data=json.dumps({"shaHash": sha1_formatted, "certType": "SHA_1"}).encode(),
        )
        print(f"SHA-1 added: {result}")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("SHA-1 already registered (409) — will still check for OAuth client")
        else:
            raise

    # Wait up to 90 seconds for the Android OAuth client to appear in google-services.json
    print("Waiting for Android OAuth client to be provisioned...")
    gs_json = None
    android_client_found = False
    for attempt in range(10):
        wait = 5 if attempt == 0 else 10
        print(f"  Waiting {wait}s (attempt {attempt + 1}/10)...")
        time.sleep(wait)

        cfg = api(
            f"https://firebase.googleapis.com/v1beta1/projects/{project_id}/androidApps/{app_id}/config"
        )
        gs_json = base64.b64decode(cfg["configFileContents"]).decode()
        gs_obj = json.loads(gs_json)

        for client_entry in gs_obj.get("client", []):
            for oc in client_entry.get("oauth_client", []):
                ctype = oc.get("client_type")
                cert = oc.get("android_info", {}).get("certificate_hash", "")
                cert_norm = cert.replace(":", "").upper()
                print(f"    oauth type={ctype} cert={cert or '(none)'}")
                if ctype == 1 and cert_norm == sha1_hex:
                    android_client_found = True
                    print("    ^^^ MATCH — Android OAuth client found!")

        if android_client_found:
            print(f"Android OAuth client provisioned after {attempt + 1} attempts!")
            break

    if not android_client_found:
        print("Android OAuth client NOT found after 90s — using fallback google-services.json")
        fallback()
        sys.exit(0)

    with open("android/app/google-services.json", "w") as f:
        f.write(gs_json)
    print("google-services.json written with Android OAuth client — Google Sign-In should work!")

except Exception as exc:
    print(f"Firebase step failed: {exc}")
    traceback.print_exc()
    print("Falling back to static google-services.json")
    fallback()
