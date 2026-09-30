# Log formats and counting rules

Each rule below comes from measuring real session logs, not from format documentation. The
counts were taken on September 30, 2026 from one developer machine: 3,489 Claude Code session
files and 305 Codex CLI session files. Agent log formats change without notice, so an adapter
is listed as supported only with the check that verified it.

## Shared record

Every adapter emits one row per model attempt with the columns in
[`llm_token_audit/record.py`](../llm_token_audit/record.py). Three rules keep rows comparable
across tools:

- `input_tokens` is uncached input only. Cache reads and cache writes have their own columns,
  so the three never overlap and can be priced separately.
- `output_tokens` includes reasoning tokens. `reasoning_tokens` is a subset of it.
- An empty value means the log did not report the field. It never means zero.

## Claude Code

Location: `~/.claude/projects/**/*.jsonl`, or `$CLAUDE_CONFIG_DIR/projects`. Usage lives on
`assistant` lines under `message.usage`.

**One response spans many lines.** Claude Code writes a line for each streamed content block
and repeats the response's usage on every one. Of 145,894 lines carrying usage, 81,694 repeat
a response already seen. Summing every line overstated total tokens by 124%.

Within one response's lines, input and cache counts stay constant and `output_tokens` only
grows; the last line holds the final value in all 13,962 responses whose lines differ. The
adapter keys on `message.id` and keeps the line with the highest output count.

**Responses repeat across files.** 244 responses appear in more than one file: 198 because a
resumed session copies earlier responses into its new file, and 46 because a subagent response
is logged in both the parent and the subagent file. The adapter deduplicates across every file
and credits each response to the earliest session that logged it.

**Fallback attempts hide inside `iterations`.** When Claude Code falls back to another model,
the top-level usage reports only the final attempt. The replaced attempt appears only in
`usage.iterations`. In one logged case the replaced attempt read 468,225 cached tokens that the
top-level usage omits. The adapter emits one row per attempt and marks earlier attempts
`superseded_attempt`. The log shows the attempt ran; it does not show whether it was billed.

**Other fields.** `cache_creation.ephemeral_1h_input_tokens` becomes
`cache_write_extended_ttl_tokens`. `output_tokens_details.thinking_tokens` becomes
`reasoning_tokens` and never exceeded `output_tokens`. Lines with model `<synthetic>` carry zero
usage and are skipped.

**Verification.** Claude Code logs carry no running total, so the adapter was checked against
an independent recount keyed on `requestId` instead of `message.id`. On a frozen copy of the
logs the two methods matched exactly on input, cache read, cache write, and output tokens.

## Codex CLI

Location: `~/.codex/sessions/**/*.jsonl`, or `$CODEX_HOME/sessions`. Usage lives on
`event_msg` lines of payload type `token_count`, with a cumulative `total_token_usage` and a
per-turn `last_token_usage`.

**Cached input is a subset of input.** `cached_input_tokens` never exceeded `input_tokens` in
26,439 events, and `total_tokens` equals input plus output. Treating the two as separate counts
would misreport a session cached at 96.8% as one cached at 49.2%. The adapter subtracts cached
from input to get uncached input.

**Totals repeat.** 405 events re-emit an unchanged cumulative total. Counting their per-turn
usage would double-count those turns, so the adapter skips any event whose total did not change.

**Counters can restart.** In one session the cumulative total restarted at the per-turn value.
The adapter records per-turn usage, never differences between totals, so a restart does not
distort the count.

**Cache writes are not reported.** `cache_write_input_tokens` was 0 in all 18,900 events that
carry it, so the adapter leaves cache writes empty rather than reporting zero.

**Verification.** For every session, the per-turn rows must sum to the log's own cumulative
total. All 297 sessions with usage reconcile. `python3 -m llm_token_audit check` repeats this
check on your logs and reports any session that fails.

## Adding an adapter

1. Measure the format across real logs before writing code: find duplicate records, subset
   relationships between fields, and anything reported as zero that is unmeasured.
2. Map each field into the shared record without double-counting.
3. Verify against the log's own totals, or against an independent recount when the log has
   none, and record the method and result here.
