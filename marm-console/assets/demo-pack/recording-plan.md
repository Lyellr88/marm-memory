# Recording Plan

Target: 60 to 90 seconds, 1920x1080 landscape, no voiceover required. Record at 60 fps if practical, then deliver the final at 30 or 60 fps.

## Before recording

- Use the synthetic `console-demo` session and `signalboard-demo` repository only.
- Close unrelated browser tabs, terminals, notifications, bookmarks, and apps.
- Keep browser zoom at 100 percent and use a neutral desktop background.
- Do not show API keys, real paths, real memory/session names, account names, or package-management output.

## Sequence

| Time | Screen action | Edit focus |
| --- | --- | --- |
| 0:00 to 0:07 | Open Overview and hold on the Console health summary. | Title: `MARM Console`. Slow push-in toward the active local runtime state. |
| 0:07 to 0:23 | Open Memories, search `release readiness`, then open a matching result. | Ease into the search field and result. Keep the cursor calm, with one restrained click cue. |
| 0:23 to 0:40 | Open Knowledge Graph, show the Memory Explorer, select a concept, and trace its neighborhood. | Pull back to establish the graph, then push in only on the selected concept and its details. |
| 0:40 to 0:58 | Open Indexed Projects, show `signalboard-demo`, then open Code Explorer and select `build_release_digest`. | Use a clean cut between workspaces. Let the graph settle before zooming into the selected file. |
| 0:58 to 1:12 | Open the terminal dock and run `marm-memory doctor`. Optionally, from `demo-project`, run `python -m signalboard.cli`. | Keep terminal text readable. Show the dock as the local control surface, not as a wall of output. Crop a prompt if it contains a local path. |
| 1:12 to 1:20 | Return to Overview or Knowledge Graph. | End card: `Local memory. Connected code. One control plane.` |

## Motion and graphic direction

- Use smooth keyframed push-ins and pull-backs with easing. Zoom only when it directs attention to a meaningful interaction.
- Remove hesitant cursor travel and dead time. Use one consistent cursor treatment and subtle click emphasis.
- Favor clean cuts, short dissolves, and restrained titles. Avoid glitch effects, fast whip pans, exaggerated click rings, or constant zooming.
- Captions should be high contrast, brief, and safe inside a 16:9 title-safe area. Deliver an `.srt` alongside the final video.

## First-cut checkpoint

Before a full edit, provide a 10 to 15 second low-resolution sample containing one search interaction and one graph interaction. Confirm pacing, zoom behavior, cursor treatment, and title style before completing the full cut.
