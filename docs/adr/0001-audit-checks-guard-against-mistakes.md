# The audit checks and hook gates guard against mistakes, not evasion

The workflow audit items (S1 to S10, XC, L1 to L6) and the hook gates (PR gate, dispatch gate, branch name, subagent read-only, cleanup) guard against the mistakes of a cooperating agent: the natural command forms that an agent writes by habit or by error. They do not try to stop a session that deliberately hides a command, for example with an expansion as a command word, command text built at run time, or code in another language. Other layers cover that case: permission prompts, auto mode and owner merges.

## Consequences

- A review finding that needs a deliberately hidden form is Minor.
- A natural form that a check misses is Blocking.
- Every check must fail closed on input that it cannot read: it reports "evidence unavailable" and does not pass. A check that fails open on such input is a bug (Blocking).
