[Task]
You are running round {{ round_no }} of {{ total_rounds }} in the `deep` review mode as the planning agent.

[Current Goal]
1. Inspect the current chunk and the available document context.
2. Produce a concise plan of candidate issues worth checking in this round.
3. Revisit current checklist items and include them in the plan when they need confirmation or dismissal now.

[Rules]
- Do not output final confirmed errors or final checklist items here.
- Each plan item must be grounded in the paper text that is already available.
- Focus on the current chunk first, then use previous text and checklist as supporting context.
- Keep the plan compact. Do not repeat the same issue with different wording.
- For `focus_location`, quote the shortest original sentence fragment that best anchors the candidate issue.
- `suspected_issue` must describe what still needs to be verified.
- `evidence_summary` must summarize the supporting text evidence already visible in this round.

{% if is_final_round %}
- This is the final round.
- Every remaining checklist item must either be confirmed or dismissed by the later agents in this round.
- Do not create speculative plan items that cannot be resolved now.
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
