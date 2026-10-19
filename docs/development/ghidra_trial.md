# Ghidra trial: retained SurveySync 9.5.3 native artifacts

Completed October 19, 2026. This was a bounded developer investigation, with no
application build, publication, promotion, installer execution, or application
execution.

## Decision

Keep Ghidra as an optional developer tool. The trial demonstrated that it can
recover useful Go function names, call relationships, and pseudocode from the
actual retained Windows launcher and updater. It can support investigation of a
specific compiled dependency or a difficult file-format compatibility question.
It does not add a current GIS, surveying, OCR, or interface feature, and it should
not become a SurveySync runtime dependency.

No new launcher defect was demonstrated by this limited examination. It did not
establish why the user's Defender installation flagged a launcher, whether the
user's quarantined file had the same hash, or that either program is malware-free.
The existing 9.5.3 withdrawal and separate 9.5.4 candidate review are independent
of this trial.

## Exact inputs and provenance

The source of the examined files was the retained artifact
`incident-953-exact-original-files`, artifact ID `12067489044`, from
[workflow run 38949172536](https://github.com/cpaul1988/SurveySync/actions/runs/38949172536).
The ZIP was downloaded through the connected repository access. The values below
were computed locally, and both executable hashes matched the existing incident
record. This is an artifact identity check, not a new source-to-binary reproduction.

| Item | Bytes | Verified SHA-256 |
| --- | ---: | --- |
| Original native-files ZIP | 8,770,302 | `35204ec592dd67cedbbbe1995158ec71e0c7e50331a573315e703f8c428edf38` |
| `app/SurveySync.exe` | 2,529,792 | `e238799ffd8c84c7d648db8a97468abde8771b418156612e0224ff0f450f9fd1` |
| `app/SurveySyncUpdater.exe` | 2,290,176 | `ccdd9ced728482dee53d75b4ad311be3b93de4f9eb49943e900a197b2f274676` |

Only the two executable entries and a small set of source/version files needed
for interpretation were extracted from the ZIP. The executable bytes were given
to Ghidra as input files and were never launched. SHA-256 was checked before and
after analysis and remained unchanged for both samples.

The archive's version files identify `9.5.3` / `9.5.3-beta.1`. Its shipped
`installer/app_launcher.go` and `installer/update_helper.go` helped interpret the
recovered functions. Matching names or behavior to those sources is not proof of
complete binary equivalence. The existing incident record identifies the earlier
installer as SHA-256
`65b617f9a69aca551f68344124ef7f239afce10e4391edbc89f4d4cec9e09d95`;
this trial analyzed the retained loose executables rather than re-extracting that
original installer.

The unpublished replacement candidate installer was also retrieved and its hash verified as
`17fb62ee40b9da9658dd8e24a7d935d91acc2f8dcb508e06067d2d63abb9493e`.
Its header identifies Inno Setup 6.7.0. No replacement native binary was extracted
or analyzed in this trial; it must not be described as covered by the findings
below.

## Isolated tooling

Official archives were downloaded to the scratch `devtools` directory and checked
against upstream release checksums before extraction or use. Java selection,
Ghidra preferences, temporary files, projects, and logs were scoped to the analysis
process/output directory. Global Java configuration and the user's workstation
were not changed.

| Tool | Upstream archive | Verified SHA-256 |
| --- | --- | --- |
| Ghidra 12.1.4 | `ghidra_12.1.4_PUBLIC_20260921.zip` | `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db` |
| Eclipse Temurin JDK 21.0.12.1+1, Linux x64 | `OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz` | `ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94` |

Ghidra's release asset digest and release-body checksum agreed. The JDK archive
matched both Adoptium's metadata checksum and its published SHA-256 file. These
checks establish agreement with the retrieved upstream checksums; they are not
an independent audit of the analysis tools.

The release-specific Ghidra 12.1.4 guide requires JDK 21. The moving `master`
documentation already describes a later development version and JDK 25, so it was
not used to select this trial's runtime.

## Method and completion evidence

`scripts/devtools/run_ghidra_trial.py` requires an explicit expected input hash,
uses an empty output directory, and launches only Ghidra. It gives auto-analysis
240 seconds by default, limits Ghidra to two analysis CPUs and a 2 GB heap, and
applies an additional 480-second wall-clock limit to the analysis process group.
The script preserves a run manifest with commands, versions, hashes, elapsed time,
exit status, and timeout status. It returns failure if auto-analysis timed out,
the report is missing or cannot be parsed, the input changed, or the headless
process failed.

`SurveySyncStaticAudit.java` exports program identity, memory blocks, static
external symbols, main-package functions, and direct call relationships. It
attempts pseudocode generation for at most 48 main-package functions, with a
20-second per-function limit. Compiler-generated wrappers and comparators in the
main namespace are included in the counts.

| Final run | Launcher | Updater |
| --- | ---: | ---: |
| Ghidra format / language | PE / x86 64-bit / Go | PE / x86 64-bit / Go |
| Go version detected from the binary | 1.23.12 | 1.23.12 |
| Recovered functions, including runtime/library code | 2,747 | 2,618 |
| Functions attributed to the main package | 27 | 14 |
| Selected decompilations completed | 27 of 27 | 14 of 14 |
| Static external symbols | 46 | 46 |
| Recorded external library | `KERNEL32.DLL` | `KERNEL32.DLL` |
| Wall-clock time, including startup and export | 74.359 seconds | 67.751 seconds |
| Headless process exit | 0 | 0 |
| Auto-analysis / outer timeout | Neither reached | Neither reached |
| Input hash after analysis | Unchanged | Unchanged |

The console logs explicitly record successful auto-analysis, post-analysis, and
program import. No additional DLL files were loaded: the local Linux environment
did not supply `KERNEL32.DLL`. Ghidra analyzed the samples and their embedded Go
code, not the implementations of the Windows system APIs.

An initial launcher run verified that recovery/export worked. The final runs above
used the timeout-aware scripts. The hashes below identify the script versions
actually executed for those historical runs:

- `SurveySyncStaticAudit.java`:
  `d5501978e47441a1f2fbab60c1857bc5d8de899595c5e622fd771b8448fb8020`
- `run_ghidra_trial.py`:
  `6014b61e643b6bb3c20dbd3f9c2b29e17ba063a6c7445728b960eda0ad7ce925`

After the successful analysis, the runner received two diagnostic robustness
improvements: malformed, partial, invalid-text, or non-object JSON reports now
preserve a manifest with `report_parse_error` and return failure; Java property
arguments are quoted so output paths containing spaces or quote characters retain
the intended preference/temp locations. The revised runner SHA-256 is
`ff5be296ef1e150120e02869eca73e03405b66113a5264bce97113acbc6d0f87`.

The revision was checked with an inert input, a stub headless exporter, and the
actual JDK. Six targeted cases covered a valid report, partial JSON, a non-object
JSON root, invalid encoded text, a missing report, and a reported analysis timeout;
all preserved the manifest and returned the expected success/failure status.
Temporary paths contained spaces and both quote characters. A separate real-JDK
property check confirmed the intended `user.home` and `java.io.tmpdir` values.
The check summary is `devtools/results/runner_robustness_checks.json` outside the
repository. The successful Ghidra analyses were not repeated, and their original
manifests and recorded runner hashes were not changed.

## Observed behavior and interpretation

These observations refer to recovered functions and call sites. The source files
shipped in the same artifact were consulted to interpret Windows API names and
the product's intended workflow.

| Recovered function / address | Observed static evidence | Interpretation |
| --- | --- | --- |
| Launcher `main.main`, `00519800` | Calls logging, single-instance handling, `os/exec.Command`, process `Start` and `Wait`, job-object helpers, and pending-update handoff. Pseudocode sets `HideWindow=true` and `CreationFlags=0x08000000`. | A native wrapper starts and supervises the private Python desktop process while suppressing a console window. The hidden-console flag alone does not establish malicious behavior or explain an antivirus verdict. |
| Launcher `main.verifyPendingInstaller`, `00517a20` | Calls absolute-path and symlink resolution, file stat/read, SHA-256, and case-insensitive comparison. Recovered branches check the staged file and reject validation failures. | The expected staged-installer verification path is present in the retained native launcher. This is evidence of those checks, not exhaustive proof against every possible race or filesystem condition. |
| Launcher `main.launchPendingUpdate`, `00518200` | Calls the verifier, reads/writes the helper, hashes the copied bytes, creates a helper command, and checks a helper heartbeat. Pseudocode sets `CreationFlags=0x208`. | A copied helper is started as a detached process in a new process group so installation can continue after the launcher exits. |
| Launcher single-instance/job helpers, `005192c0`, `00519400`, `00519560` | Recovered mutex/job routines use `syscall.(*LazyProc).Call`; the shipped source identifies the corresponding Windows mutex and Job Object APIs. | The launcher manages duplicate instances and child-process lifetime. Lazy API lookup explains why the static import table is not a full inventory of possible runtime DLL/API use. |
| Updater `main.main`, `004fd3e0` | Recovered control flow calls `waitForLauncherExit`, then `verifyUpdateInstaller`, then creates/starts/waits for the setup process. | The helper contains the expected wait, re-verification, and setup handoff sequence. |
| Updater `main.verifyUpdateInstaller`, `004fc6e0` | Recovered calls include path/symlink resolution, stat/read, SHA-256, and comparison. | Installer validation is present in the helper as well as the launcher. |

An independent, read-only `objdump -p` inspection also identified both files as
PE32+ Windows GUI images and reported an empty PE Security Directory. This was
observed metadata; Ghidra was not used as an Authenticode verification service.

The useful result is that Ghidra independently exposes recognizable behavior in
the actual retained native artifacts. A routine Python source bug would still be
investigated more directly through source, logs, and a focused reproducer. A
future proprietary-format trial should begin with one specific failing format
variant, paired reference data, and a concrete parsing question. No Trimble `.job`
decoder or new format support was created or demonstrated here.

## Evidence locations and reproduction

Raw executables, tool archives, projects, and full pseudocode remain outside the
repository under `/workspace/scratch/af50c5c9a2be/devtools`. They are not intended
for the application installer. The final output directories are:

- `results/original953-launcher-final/`
- `results/original953-updater/`

Each contains `run_manifest.json`, `static_report.json`, `console.log`,
`analysis.log`, `script.log`, and `decompiled/`. The final static-report hashes are:

| Report | SHA-256 |
| --- | --- |
| Launcher | `f3986671d4ec7bb946e4ac1cb5bd7d14dc6175d50d59b3a1a5b638a3d21402c8` |
| Updater | `41348d4eddbb25c57c338b7982eee012048a7df4acfa5f791cd7ae68dd3c28ea` |

Reproduction uses Python 3.11+ and the Unix Ghidra headless launcher. Download and
verify the tool archives linked below, extract the hash-identified samples without
executing them, and choose fresh output directories. From the repository root:

```bash
python scripts/devtools/run_ghidra_trial.py \
  --ghidra-dir /workspace/scratch/af50c5c9a2be/devtools/ghidra/ghidra_12.1.4_PUBLIC \
  --jdk-dir /workspace/scratch/af50c5c9a2be/devtools/jdk21/jdk-21.0.12.1+1 \
  --sample /workspace/scratch/af50c5c9a2be/devtools/artifacts/original953/SurveySync.exe \
  --sha256 e238799ffd8c84c7d648db8a97468abde8771b418156612e0224ff0f450f9fd1 \
  --output /workspace/scratch/af50c5c9a2be/devtools/results/launcher-reproduction

python scripts/devtools/run_ghidra_trial.py \
  --ghidra-dir /workspace/scratch/af50c5c9a2be/devtools/ghidra/ghidra_12.1.4_PUBLIC \
  --jdk-dir /workspace/scratch/af50c5c9a2be/devtools/jdk21/jdk-21.0.12.1+1 \
  --sample /workspace/scratch/af50c5c9a2be/devtools/artifacts/original953/SurveySyncUpdater.exe \
  --sha256 ccdd9ced728482dee53d75b4ad311be3b93de4f9eb49943e900a197b2f274676 \
  --output /workspace/scratch/af50c5c9a2be/devtools/results/updater-reproduction
```

Adjust absolute paths for another workstation. Wall-clock timing, logs, generated
project files, and some heuristic analysis output can vary; compare the input
hashes, pinned tools, completion status, and substantive recovered evidence.

## Scope limits

- No Windows target executable was run, and no dynamic behavior was observed.
- Static imports omit possible runtime-loaded APIs; decompilation is heuristic.
- This was not a full review of all 2,747/2,618 recovered functions, all Python
  payload code, or dependencies fetched during installation.
- No fresh antivirus scan, Microsoft analyst submission, or clearance occurred.
- The user's exact quarantined bytes were unavailable.
- The existing original-file scan/reproduction history and the 9.5.4 acceptance
  evidence remain separate evidence sets. Nothing here authorizes changing an
  existing release hold.

## Primary references

- [Official Ghidra 12.1.4 release and checksum](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build)
- [Ghidra 12.1.4 runtime guide](https://github.com/NationalSecurityAgency/ghidra/blob/Ghidra_12.1.4_build/GhidraDocs/GettingStarted.md)
- [Official Ghidra archive](https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip)
- [Temurin 21.0.12.1+1 release](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1)
- [Temurin archive checksum](https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz.sha256.txt)
- [Ghidra import/decompiler training](https://ghidra.re/ghidra_docs/GhidraClass/Beginner/Introduction_to_Ghidra_Student_Guide.html)
- [Ghidra NOTICE and component licenses](https://github.com/NationalSecurityAgency/ghidra/blob/master/NOTICE)

Ghidra's core is Apache 2.0; its NOTICE describes separately licensed third-party
components and standalone GPL support programs. This trial added no Ghidra code
or binaries to SurveySync's distributed runtime.
