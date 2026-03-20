[Task]
You are running round {{ round_no }} of {{ total_rounds }} in the `standard` review mode.

[Current Goal]
1. Check the current chunk for context-aware or document-level issues that can be confirmed now.
2. Use the previous chunks and current checklist as supporting context.
3. Promote a previous checklist item into `errorlist` only if the current evidence is sufficient.
4. Keep unresolved context-aware concerns in `checklist`.

[Rules]
- Focus on the current chunk first.
- Do not repeat issues that were already confirmed earlier.
- `check_explanation` must start with `please check`.
- Return only the incremental `errorlist` and `checklist` for this round.
- The concrete error-type definitions follow `system/base_guardrails.md`.
- This agent only handles these `error_type` titles: `Methodological Logic Errors`, `Experimental Operational Defects`, `Distorted Claims`, `Falsified Citations`, `Contextual Misalignment`, `Inconsistency between Text and Figures`.
- Do not report `Language Expression Errors`, `Knowledge Background Errors`, or `Numerical and Calculation Errors`. The local-error agent handles those separately.
- For each `error_location`, quote the shortest original sentence fragment that directly contains the problem. Do not paste long paragraphs.
- `error_reason` must explain the core evidence from the paper text.
- `error_reasoning` must spell out the full judgment chain from textual evidence to conclusion.

[Important Constraints]
- Do not judge an error based on publication year, recency, or whether they appear to be from the future.
- Only check citation issues that can be verified from the paper itself (e.g., internal inconsistency, missing references, mismatched labels).

{% if is_final_round %}
- This is the final round.
- Revisit every item in [Current Checklist] using the full context now available.
- Do not add any new checklist items in this round.
- Either confirm a checklist item into `errorlist` or dismiss it. The final checklist must be empty after this round.
{% endif %}

[Current Chunk]
{{ current_chunk_text }}

[Previous Text]
{% if history_text %}
{{ history_text }}
{% else %}
(none)
{% endif %}

[Current Checklist]
{{ checklist_json }}
