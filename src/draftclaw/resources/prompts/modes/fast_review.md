[Task]
You are reviewing chunk {{ round_no }} of {{ total_rounds }} in the `fast` review mode as the context-aware main agent.

[Current Goal]
1. Check the current chunk for context-aware or document-level issues that can already be confirmed.
2. Use previous chunks and the current checklist as supporting context.
3. Promote a previous checklist item into `errorlist` only if the current evidence is sufficient.
4. Keep unresolved context-aware concerns in `checklist`.

[Rules]
- The concrete error-type definitions follow `system/base_guardrails.md`.
- This agent only handles these `error_type` titles: `Methodological Logic Errors`, `Experimental Operational Defects`, `Distorted Claims`, `Falsified Citations`, `Contextual Misalignment`, `Inconsistency between Text and Figures`.
- Do not report `Language Expression Errors`, `Knowledge Background Errors`, or `Numerical and Calculation Errors`. The local-error agent handles those separately.
- Return only the incremental `errorlist` and `checklist` for this chunk.
- `check_explanation` must start with `please check`.
- Make every location concrete, such as section names, paragraph topics, sentence fragments, or figure/table identifiers.
- Do not repeat issues that were already confirmed earlier.
- For each `error_location`, quote the shortest original sentence fragment that directly contains the problem. Do not paste long paragraphs.
- `error_reason` must explain the core evidence from the paper text.
- `error_reasoning` must spell out the judgment chain from textual evidence to conclusion.

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
