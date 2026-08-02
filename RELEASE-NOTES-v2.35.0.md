# MARM v2.35.0

This release makes long-memory retrieval more durable and repairable. It also fixes embedding migration failures on databases that contain long content.

## Long-memory chunks no longer disappear silently at shutdown

MARM stores memories longer than 500 words as smaller chunks so recall can match the relevant passage rather than judge the entire memory as one block. Those chunks are written after the parent memory, which previously left a gap: if the server stopped during that background work, the parent memory survived but its chunks could be lost without an error.

Both HTTP and STDIO shutdown now wait up to five seconds for pending chunk writes. The limit is configurable with `CHUNK_DRAIN_TIMEOUT_SECONDS`, and any work left unfinished can be repaired safely with the new rechunk command.

## New rechunk repair command

Run either command with all MARM processes stopped:

```bash
marm-mcp-server --rechunk
# or
marm-memory maintenance chunks rechunk
```

It repairs chunks missing after an interrupted write, re-splits chunks created under older sizing rules, and removes chunks from memories now below the long-memory threshold. Already-correct memories are skipped, so the command is safe to run again.

The command refuses to run if stored vectors use a different embedding dimension from the configured model. In that case, run `marm-mcp-server --migrate-embeddings` first.

## Embedding migration now handles long content safely

`--migrate-embeddings` previously processed 100 memories at a time. Because the encoder pads every item in a batch to the longest text, one long memory could force an enormous allocation and crash the migration.

Migration now sizes batches from the actual content length. Short memories still use efficient large batches, while long-memory databases no longer attempt unsafe allocations.

## Upgrade note

Existing installs should run `marm-mcp-server --rechunk` once after upgrading, with MARM stopped. Recall still works without it, but long memories may be less accurate until their chunks are repaired.

See the [v2.35.0 changelog](CHANGELOG.md) for the full technical details.
