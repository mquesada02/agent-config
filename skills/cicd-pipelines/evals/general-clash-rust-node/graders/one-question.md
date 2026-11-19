---
type: llm
arm: with-only
---
PASS if the reply is one question to the user, with no review, no plan and no file, and the question names both stacks: the language of the repo files (Rust) and the language that the request names (Node), and asks which one the user wants. FAIL if the reply writes a pipeline, a plan, a file or a review, or asks more than one question.
