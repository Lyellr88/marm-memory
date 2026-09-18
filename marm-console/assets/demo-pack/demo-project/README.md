# Signalboard Demo

A fictional release-readiness service for the MARM Console demo. It has a deliberately layered import graph: intake, policy, readiness scoring, dependency checks, local delivery, reporting, and the command-line entry point.

Index this folder in MARM Console. The recording flow highlights `build_release_digest` in `signalboard/reporting/digest.py`.

Run the sample locally from this directory:

```powershell
python -m signalboard.cli
```
