Return exactly one JSON object and nothing else.

`error_type` values and their concrete meanings must follow `system/base_guardrails.md`.

The top-level shape must be:
{
  "errorlist": [
    {
      "id": "integer",
      "error_location": "string",
      "error_type": "Language Expression Errors | Knowledge Background Errors | Numerical and Calculation Errors | Methodological Logic Errors | Experimental Operational Defects | Distorted Claims | Falsified Citations | Contextual Misalignment | Inconsistency between Text and Figures",
      "error_reason": "string",
      "error_reasoning": "string"
    }
  ],
  "notes": "optional"
}
