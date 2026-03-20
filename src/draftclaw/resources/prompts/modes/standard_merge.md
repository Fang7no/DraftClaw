[Task]
You will receive one or more `errorlist` batches from the {{ merge_scope_label }}.

Remove semantic duplicates within this channel only and return one final `errorlist`.

[Rules]
- Do not add new items.
- The concrete error-type definitions follow `system/base_guardrails.md`.
- Deduplicate only within the batches from this channel.
- Do not compare against or reconcile with the other channel. That cross-channel combination happens locally after both channel merges finish.
- If two items describe the same underlying issue, keep only the most informative one.
- If two items share a location but clearly describe different problems, keep both.
- Preserve the original `error_type` of the kept item.
- Return only one JSON object.

[Input]
{{ round_errorlists_json }}
