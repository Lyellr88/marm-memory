# MARM Console Demo Pack

This pack creates safe, fictional material for a MARM Console recording. It contains no API keys, personal memories, private paths, customer data, or third-party assets.

## Contents

- `seed/memories.json`: 36 fictional memories for the `console-demo` session, spanning release readiness, alerts, notifications, dependencies, handoffs, and recording guidance.
- `setup_demo.py`: imports those memories through a loopback MARM runtime.
- `demo-project/`: a multi-layer Python repository with visible imports, symbols, and a runnable local release-readiness flow for Indexed Projects and Code Explorer.
- `recording-plan.md`: the 60 to 90 second walkthrough, shot list, and edit direction.
- `asset-manifest.md`: confirms the pack contains only original, reusable material.

## Safe setup

Use a dedicated MARM profile or disposable local database for recording. Do not run this against a database containing personal memories or production project data.

1. Start MARM and Console locally:

   ```powershell
   marm-memory console
   ```

2. In another terminal, import the synthetic memories:

   ```powershell
   python marm-console/assets/demo-pack/setup_demo.py
   ```

The script permits only `localhost`, `127.0.0.1`, or `::1` targets. If your local runtime requires authentication, it reads `MARM_API_KEY` from the environment without printing or storing it.

3. In **Indexed Projects**, index `marm-console/assets/demo-pack/demo-project` in **Full** mode. Keep the repository's `.git` directory after initializing it if you want to demonstrate automatic re-indexing.

4. In **Knowledge Graph**, choose **Build Concepts** and build the `console-demo` session. Wait for the successful run before recording the Memory Explorer.

5. Follow `recording-plan.md`. Review every frame before delivery for real browser tabs, usernames, filesystem paths outside this pack, and any existing Console data.

## Optional Git setup

The Code Explorer does not require Git for initial indexing. To show the project-watch behavior, initialize the demo project before indexing:

```powershell
cd marm-console/assets/demo-pack/demo-project
git init
git add .
git commit -m "Demo project"
```

## Reset

The importer intentionally does not delete anything. For a fresh take, use a disposable MARM profile or delete only the `console-demo` session and the `signalboard-demo` indexed project through Console.
