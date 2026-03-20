● marm-memory - marm_system_info (MCP)
  ⎿  {
       "status": "operational",
       "version": "2.2.6",
     … +42 lines (ctrl+o to expand)

● marm-memory - marm_log_session (MCP)(session_name: "computer-dx")
  ⎿  {
       "status": "success",
       "message": "📂 Session 'computer-dx' created/activated",
     … +2 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-project-overview-computer-dx is a flat PowerShell diagnostic
                                    toolkit (v1.5). 11 scripts + 2 C# helpers. No modules — all scripts are standalone.
                                    Three categories: Collectors (Get-*.ps1), Orchestrators (Run-*.ps1),
                                    Resolve-ToolPath.ps1 (shared tool resolver). Full Pester v5 test suite: 186 passed,
                                    0 failed, 4 skipped. Run-Analyzer.ps1 for PSScriptAnalyzer. Git initialized. Located
                                     at C:\\Users\\lyell\\Desktop\\computer-dx.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-project-overview-computer-dx is a flat PowerShell diagnostic tool
     … +11 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-script-inventory-11 production scripts: Get-HWiNFOData,
                                    Get-EventViewerLogs, Get-GPUZData, Get-CPUZData, Get-SystemDiagnostics,
                                    Get-NSMIData, Get-AMDSMIData, Get-SmartctlData, Run-P95StressTest,
                                    Run-HeavenStressTest, Resolve-ToolPath. 2 C# helpers: GPUZShmem.cs (GPU-Z shared
                                    memory), HWiNFOSM.cs (HWiNFO shared memory). Pause/resume (P/Q) on 4 scripts.
                                    config/tool-paths.json for tool overrides. reports/ directory holds all JSON output
                                    by subdirectory.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-script-inventory-11 production scripts: Get-HWiNFOData, Get-Event
     … +11 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-run-heavenstresstest-architecture-Orchestrator model. Vendor
                                    detection via CIM Win32_VideoController. NVIDIA uses Get-NSMIData + HWiNFO sidecar.
                                    AMD uses Get-AMDSMIData + HWiNFO sidecar. Intel/Unknown uses HWiNFO only (null
                                    primary). Pre/post snapshot model — NO in-run polling, NO Samples[], NO FlapCount.
                                    Read-SnapshotField returns normalized PSCustomObject stored in PreTest.Primary /
                                    PostTest.Primary. Join-Snapshot is display-only. Analysis.Comparison holds pre/post
                                    deltas. PostTest.NewTDREvents is the TDR path. Heaven launched from original bin\\
                                    dir with UNIGINE bootstrap args.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-run-heavenstresstest-architecture-Orchestrator model. Vendor dete
     … +12 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-decision-tree-engine-plan-New script:
                                    Invoke-DiagnosticAnalysis.ps1. Read-only engine that consumes existing JSON reports
                                    and emits structured troubleshooting findings. 6 branches: gpu_tdr,
                                    pcie_degradation, thermal_throttling, driver_regression, power_instability,
                                    intermittent_pattern. 4 correlation rules. Spec lives at
                                    docs/current/decision-tree.md (moved from future/decision-tree-draft.md). Full Files
                                     Affected section and Test Strategy section added to spec this session.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-decision-tree-engine-plan-New script: Invoke-DiagnosticAnalysis.p
     … +11 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-decision-tree-engine-contract-Parameter contract: -ReportsPath
                                    (default .\\reports), -Since int days (default 7), -Branch string[] (selective),
                                    -OutputJson string, -Quiet switch. Report selection: most recent = current state,
                                    oldest = Branch 4 baseline, 7-day window configurable. Conflicting files policy: any
                                     file triggers Medium, all files agree for High. Intel/Unknown: skip Primary PCIe
                                    path, HWiNFO sidecar only. Timestamp tolerance: Event 1001 disqualifies Event 41
                                    only within 1 hour. All timestamps convert to UTC datetime before cross-source
                                    comparison.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-decision-tree-engine-contract-Parameter contract: -ReportsPath (d
     … +13 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-decision-tree-test-strategy-Two-layer test approach. Layer 1: 18
                                     static fixtures (6 branches x 3 cases each) in tests/fixtures/decision-tree/. Layer
                                     2: tests/helpers/New-DiagnosticFixture.ps1 — fixture composer that builds synthetic
                                     JSON inputs from a signal hashtable into a temp directory for compound/edge-case
                                    scenarios. Pester file: tests/Invoke-DiagnosticAnalysis.Tests.ps1. Covers per-branch
                                     unit tests, compound+correlation scenarios, and edge cases (TempIsF conversion,
                                    null primary, conflicting files, empty dirs, negative filter for Event 1001).")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-decision-tree-test-strategy-Two-layer test approach. Layer 1: 18
     … +13 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-roadmap-next-steps-computer-dx next: implement
                                    Invoke-DiagnosticAnalysis.ps1 per spec in docs/current/decision-tree.md. Then CI/CD
                                    decision (GitHub Actions — discussed, not yet implemented). Then GUI wrapper using
                                    Tauri (Godot ruled out — game engine, wrong tool for data-heavy diagnostic
                                    dashboard). GUI pairs computer-dx with win-cache-purger
                                    (C:\\Users\\lyell\\Desktop\\caching-script) after both reach pre-GUI milestone.
                                    win-cache-purger next milestone: Quarantine Module v2.4.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-roadmap-next-steps-computer-dx next: implement Invoke-DiagnosticA
     … +11 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-working-rules-never-rewrite-full-files-Golden rule: never use
                                    Write (full file overwrite) on existing scripts. Always use Edit (targeted diffs).
                                    Validate skill runs PSScriptAnalyzer on edited files only — never project-wide.
                                    Auto-invoke skills after structural changes: /validate, /synopsis-validator,
                                    /test-sync, /update-docs. Offer but don't auto-invoke: /spec, /review. Never
                                    auto-invoke: /commit (permanent git action). User relies on Claude for technical
                                    judgment — not just execution. Always verify against source code before accepting
                                    any other AI's findings.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-working-rules-never-rewrite-full-files-Golden rule: never use Wri
     … +13 lines (ctrl+o to expand)

● marm-memory - marm_log_entry (MCP)(entry: "2026-03-20-session-summary-this-session-Pure docs session. Completed all 37
                                     edits across 4 passes on decision-tree spec (moved to
                                    docs/current/decision-tree.md). Removed all stale Heaven telemetry fields
                                    (FlapCount, Samples[], MinPCIeGenAtLoad, Stable, PeakTempC, PeakPowerW). Fixed false
                                     Resolved entries. Renamed diag.pcie_flapping to diag.pcie_degradation everywhere.
                                    Added Files Affected section, 5 Engine Design Notes gaps, Test Strategy section with
                                     fixture composer design, and TOC entries for all new sections. MARM MCP connected
                                    for first time.")
  ⎿  {
       "status": "success",
       "message": "📝 Log entry added: 2026-03-20-session-summary-this-session-Pure docs session. Completed all 37
     … +13 lines (ctrl+o to expand)

● 10 entries logged across the full session. Covered:

  - Project overview and v1.5 state
  - Full script inventory
  - Run-HeavenStressTest architecture (the pre/post model — the thing that drove most of the spec corrections)
  - Decision tree plan and engine contract
  - Test strategy and fixture composer design
  - Roadmap (decision tree → CI/CD → GUI)
  - Working rules (golden rule, skill auto-invoke policy, source-first verification)
  - This session's work summary