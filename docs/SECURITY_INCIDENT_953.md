# SurveySync 9.5.3 Defender incident — October 16, 2026

## Report and containment

The operator reported Microsoft Defender `Trojan:Win32/Bearfoos.A!ml` against the installed `SurveySync.exe`. Defender removed/quarantined the launcher and associated shortcuts. This is a confirmed detection report, not a confirmed finding of malicious source code or a confirmed false positive. No affected project files were shown.

Beta and Stable releases were removed from `update.json`; old clients now fail closed rather than downloading 9.5.3 or being silently downgraded. The v9.5.3 release is retained as a withdrawn draft, with its original evidence. Do not restore the blocked executable, add exclusions, disable protection, or launch the application through an alternate entry point to bypass the block.

## Original artifact evidence

The accepted installer is 9,107,024 bytes, SHA-256 `65b617f9a69aca551f68344124ef7f239afce10e4391edbc89f4d4cec9e09d95`. It was extracted without executing the installer or application. The Inno 6.7 parser used only for forensic extraction is pinned to dscho/innoextract commit `376a13e7c41cc5528b6088d0dd16ec1b323a8d37`; the older distribution parser failed on that format and is not counted as a successful scan.

The extracted launcher is 2,529,792 bytes, SHA-256 `e238799ffd8c84c7d648db8a97468abde8771b418156612e0224ff0f450f9fd1`. The updater is 2,290,176 bytes, SHA-256 `ccdd9ced728482dee53d75b4ad311be3b93de4f9eb49943e900a197b2f274676`. Embedded build information identifies Go 1.23.12. A local byte comparison of 207 shipped .py/.js/.ps1/.html/.go/.lock files against the accepted source snapshot found no differences or extra files in those categories. This comparison does not include arbitrary external dependencies installed at setup time.

Run `38949172536` scanned both exact original executables without executing them on an isolated Windows runner. Defender engine `1.1.26090.9`, signatures `1.461.59.0` (updated 2026-10-16), active antivirus and real-time protection: both explicit custom scans reported **no threats**, exit 0, with unchanged pre/post hashes. Logs and engine state are in artifact `12067059005`. That environment did not reproduce the user's detection. This is NOT Microsoft analyst clearance and does not establish the hash of the user's quarantined copy. Original source-to-native-binary reproduction is a separate test; only its actual matching result may be claimed.

## Candidate 9.5.4 build changes

Production Go is pinned to 1.27.2. Builds use Microsoft SDK resources for the SurveySync icon, product/company/version metadata and an asInvoker manifest. Debug/symbol information is retained for diagnostics. Neither launcher behavior nor antivirus policy is weakened. Native product metadata is not Authenticode signing, and a configured signing certificate is still required to sign.

The full build must run active Defender scans after native signing and again on the final signed installer. The documented detection-only custom scan mode ignores exclusions and includes archives, reports threats, and leaves real-time protection enabled. No-threat output, zero exit, fresh signatures, and unchanged artifact hashes are all required. Missing/unavailable/localized-unrecognized evidence fails the build. An independent Python validator binds every log and result to the actual files. Evidence is excluded from the installer and retained separately.

Tests cover invalid/detected/missing/stale/modified evidence and security-hold behavior. Existing functional gates are not bypassed. Do not release a candidate solely because an earlier executable or source-only test passed.

## Release decision

9.5.3 remains withdrawn. Candidate scan and Windows installation results must be checked before distributing 9.5.4. A clean test-machine scan cannot guarantee that every Windows cloud/reputation configuration will agree. No Microsoft sample submission or vendor clearance has been completed through this environment. User project data must remain untouched during repair.

References: https://go.dev/doc/devel/release ; https://go.dev/doc/faq#virus ; https://learn.microsoft.com/en-us/defender-endpoint/command-line-arguments-microsoft-defender-antivirus ; https://www.microsoft.com/en-us/wdsi/filesubmission
