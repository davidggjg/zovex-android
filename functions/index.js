const admin = require('firebase-admin');

admin.initializeApp();

// Push notifications are sent exclusively via the GitHub Actions workflow
// (send-notification.yml), which is protected by a real secret stored in
// GitHub Secrets — not embedded in any client-side bundle or source file.
// The old HTTP endpoint exposed the shared secret in the APK and repo, so
// it has been removed. Deploy notifications via the workflow only.
