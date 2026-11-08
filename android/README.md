# Homelab Hub (Android app)

Kotlin + Jetpack Compose. Shows your Hub's dashboard on your phone.

- **Pairing:** scan the QR code from the Hub's **Phones** page (or type the address and code).
- **Dashboard:** status summary, services grouped by category, pull to refresh. It refreshes automatically
  while the app is open, at the Hub's poll interval.
- **Details:** Proxmox nodes and VMs, *arr queue and upcoming, downloads, Jellyfin streams, and more.
- **Privacy:** only the Hub address and one read-only token are stored, encrypted with the Android Keystore,
  and excluded from backups. Permissions: Internet, plus Camera (QR scanning only).
  No Google Play Services required.

## Build

1. Open this `android/` folder in Android Studio and let Gradle sync.
2. **Build → Build App Bundle(s) / APK(s) → Build APK(s)**. The output is `app/build/outputs/apk/debug/app-debug.apk`.
3. Copy the APK to your phone and open it. Allow "Install unknown apps" for the file manager when asked.

Unit tests: right-click `app/src/test` → **Run Tests**, or run `./gradlew testDebugUnitTest`.

See [../docs/API.md](../docs/API.md) for the Hub API the app uses.
