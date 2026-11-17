# Language-neutral test design for the general fallback

Ticket: #812 (part of map #810). Question: what language-neutral guidance on test design should the `testing` skill give when a language has no entry?

Labels: FACT = stated by a cited source I read. INFERENCE = my reasoning from facts. UNTESTED = plausible, not checked.
Date of research: 2026-11-17. Options are unranked. The owner decides.

## Short answer

1. FACT: Sources agree on a shape: many small, fast tests; fewer broad, slow ones. [Fowler Pyramid; SWE Ch.11]
2. FACT: Sources disagree on what "unit" means. Fowler: the team decides; solitary (doubles) vs sociable (real collaborators). Google: unit is about scope (one class or method), separate from size (resources used). [Fowler UnitTest; SWE Ch.11]
3. FACT: Choose the lowest level that can show the failure. If a high-level test fails and no low-level test does, add a low-level test. [Fowler Pyramid]
4. FACT: Sources disagree on mocks. Classicists prefer real objects or fakes and state checks. Mockists use mocks and behavior checks. Google says: real, then fake, then stub, interaction checks last. [Fowler Mocks; SWE Ch.13]
5. FACT: A "runnable" test is isolated, deterministic and fast (three of Beck's twelve desiderata). Google size tags limit what a small test may do (one process, no sleep, no I/O, no blocking calls). [Test Desiderata; SWE Ch.11]
6. FACT: Top flaky-test causes in one study (161 analyzed fix commits): async wait (45%), concurrency (20%), test order dependency (12%). [Luo 2014]
7. FACT: Test behaviors through public APIs. Name tests after the behavior. One condition per test. Keep tests straight-line. [SWE Ch.12; Fowler Pyramid]
8. FACT: Coverage finds untested code. It is a poor quality score and a poor target. [Fowler TestCoverage]
9. INFERENCE: The fallback can be a short checklist with a "when in doubt" rule per topic, plus a pointer to ask the repo's test rules file for the real commands.
10. UNTESTED: No eval has checked that an agent follows this guidance. Not in scope here.

## Findings per topic

### 1. Kinds and levels of tests

- FACT: Google separates **size** (resources a test may use) from **scope** (code paths verified). Size: small = single process, no sleep, no I/O, no blocking calls; medium = multiple processes and threads, network only to `localhost`; large = may span machines. Scope: unit (one class or method), integration (a few components), end-to-end (whole system). [SWE Ch.11]
- FACT: Fowler's practical pyramid: unit tests (one subject, collaborators often doubled), integration tests (your code against one external part such as a database, file system or separate service), contract tests, UI tests, end-to-end tests. He says layer names matter less than using them the same way in one team. [Fowler Pyramid]
- FACT: Google's rough target is about 80% unit, 15% integration, 5% end-to-end by count. It names two bad shapes: the "ice cream cone" (too many end-to-end) and the "hourglass" (too few integration). [SWE Ch.11]
- FACT: Contract tests check each side of an interface in isolation against a shared agreement. In consumer-driven contracts, the consumer's tests generate the contract, and the provider replays it. Pact calls this "contract by example", unlike a static schema. The same docs note the term is used loosely for other checks. [Pact docs; Fowler Pyramid]
- FACT: Property-based tests state a general property and run it on many generated inputs. QuickCheck (2000) introduced the idea for Haskell. Hypothesis docs call it "a powerful addition to unit testing. It is not always a replacement." Useful properties: round trip (encode then decode), fast version equals slow clear version, an invariant is kept (total money is preserved). [Claessen and Hughes; Hypothesis docs]
- FACT: Snapshot tests compare output with a stored reference file. Jest docs: commit snapshots and review them like code; keep them small and readable; keep them deterministic (no dates or platform data); do not regenerate snapshots to silence a failure without finding the cause. [Jest docs]
- INFERENCE: A language-neutral fallback should define terms by size and scope in a short glossary, then say: "use the repo's own words if its test rules file defines them."

#### Where sources disagree: "unit"

| View | Source | Position |
|---|---|---|
| Team decides | Fowler | "Unit" is ill-defined. Often a class, sometimes a function or a group of classes. Sociable tests (real collaborators) are fine. |
| Solitary | Fowler (describing the other camp) | Replace collaborators with doubles so a fault elsewhere does not fail this test. |
| By scope | Google SWE book | Unit = narrow scope (one class or method). Size is a separate axis with hard limits. |

- INFERENCE: The fallback can avoid the argument by asking for properties (fast, isolated, deterministic) instead of one definition.

### 2. Choosing the level for a change

- FACT: "Push your tests as far down the test pyramid as you can." Keep high-level tests for what lower levels cannot cover. Remove redundant ones. [Fowler Pyramid]
- FACT: Pipeline stages should be ordered by speed and scope, not by test type. [Fowler Pyramid]
- FACT: Fowler says the real check of sufficiency is whether bugs rarely escape to production and whether developers feel safe to change code. [Fowler TestCoverage]
- INFERENCE: A simple rule for the fallback: pick the lowest level that would fail if the change were wrong; add an integration test only where the risk is the join (database, network, file format, another team's API); add an end-to-end test only for a critical user path.
- INFERENCE: Candidate decision table: pure logic -> unit; code that talks to one external system -> integration against a real or fake instance; interface shared with another team or service -> contract; output with large structured text -> snapshot; wide input space or an inverse pair -> property-based.

### 3. Fakes, stubs, mocks and seams

- FACT: Vocabulary (Meszaros, as used by Fowler): dummy (passed, never used), fake (working shortcut, such as an in-memory database), stub (canned answers), spy (stub that records calls), mock (pre-programmed expectations, verifies calls). [Fowler Mocks]
- FACT: State verification checks the outcome. Behavior verification checks the calls made. [Fowler Mocks]
- FACT: Classical style uses real objects and doubles only when awkward. Mockist style mocks any object with interesting behavior; its tests are more coupled to implementation, so changing how collaborators are called breaks them. Fowler presents both and says he is a classicist. [Fowler Mocks]
- FACT: Google ordering: prefer a real implementation if fast and deterministic; a fake is "often the ideal technique" when a double is needed (and fakes should be tested, for example with contract tests, and owned by the team that owns the real code); stubbing is limited; "Interaction testing should be avoided when possible", except for state-changing calls like sending an email. Many stubs in one test may signal a design problem. [SWE Ch.13]
- FACT: A seam lets a test substitute a dependency. Dependency injection is the common technique. Adding seams early costs less than adding them later. Doubles lack full fidelity, so add larger tests with real parts. [SWE Ch.13]
- FACT: Wrap the system clock so tests can inject a fixed time. Replace remote services with a double and run separate contract tests to check the double still matches. [Fowler Non-determinism]
- INFERENCE: Candidate seam list: clock, random source, file system, network, process environment, external service clients, id generators. Put the seam at the edge of the code you own, not inside third-party code.
- INFERENCE: Candidate rule of thumb: real > fake > stub > mock. Use a mock or spy only to prove an outbound side effect that has no readable state.

### 4. Failure paths and edge cases

- FACT: Unit tests should cover all non-trivial code paths, "including happy path and edge cases". Fowler's pyramid article says little more. [Fowler Pyramid]
- FACT: The Beyonce rule: "If you liked it, then you shoulda put a test on it." Test any behavior you want to keep. [SWE Ch.11]
- FACT: Property-based tools can generate inputs a human would not think of, such as random inputs of the right shape to find crashes. [Hypothesis docs]
- INFERENCE (from the above and standard test-design practice; I did not fetch a primary source for the list): candidate edge checklist: empty, one, many, maximum; zero, negative, off-by-one at boundaries; invalid or malformed input; missing or unreadable resource; timeout; partial failure; duplicate or repeated call; error message or error type is part of the behavior; resource cleanup after failure.
- GAP: No primary source read on boundary-value analysis or error-path coverage. Candidates to read later: Myers, "The Art of Software Testing"; ISTQB Foundation syllabus.

### 5. Test naming and structure

- FACT: Name a test after the behavior (action and expected outcome). If the name needs "and", split the test. Test behaviors, not methods. [SWE Ch.12]
- FACT: Arrange, Act, Assert (or Given, When, Then). "Test one condition per test." "Readability matters." [Fowler Pyramid]
- FACT: DAMP over DRY in tests: some duplication is fine if each test is clear and self-contained. Avoid loops, conditionals and string building in tests. [SWE Ch.12]
- FACT: Test through the public API, as a user would. [SWE Ch.12]
- FACT: Snapshot names should describe the expected content. [Jest docs]
- INFERENCE: Naming the file and the group by the unit under test and by size tag helps selecting a group later (see topic 6).

### 6. What makes a test runnable

- FACT: Beck's desiderata include: isolated (result does not depend on order), deterministic, fast, automated, specific (a failure shows its cause), structure-insensitive (survives refactors). [Test Desiderata]
- FACT: Fast: Fowler gives no absolute number. He cites 300 ms for a "compile suite" run after nearly every change (Gary Bernhardt) and ten minutes for a "commit suite" (Kent Beck). His point: fast enough that people run them often. [Fowler UnitTest]
- FACT: Small tests at Google may not sleep, do I/O or make blocking calls; medium tests may use threads and `localhost` only. The size is a label that tooling can use to select tests. [SWE Ch.11]
- FACT: Isolation remedies: rebuild or clean the starting state for each test (a transaction rolled back is one way). [Fowler Non-determinism]
- FACT: Slow suites often come from sleep-based waits. Polling for the state change is better. [SWE Ch.11]
- FACT: Do not wait for async work with a bare sleep. Use a callback, or poll with a short interval and a generous overall timeout. [Fowler Non-determinism]
- INFERENCE (parallel safety): a test is safe to run in parallel when it owns all state it touches. Candidate checks: unique temp directories, no fixed ports (use port 0 or a free port), unique database names or schemas, no shared global or static state, no writes to the working directory, no reliance on another test's output. Evidence for the cause: shared state and shared files such as `/tmp` break tests when run together (reader comments on a Google blog post; weak source) and test-order dependency is a top cause in Luo 2014.
- INFERENCE (grouping): a change should run only its group. Candidate group axes: size (small, medium, large), scope or layer (unit, integration, end-to-end), and area (package or module). Google uses size as a tag. Which axes to use is a decision for the owner and the setup mode, not for this fallback.
- UNTESTED: that a given repo's test runner can select by tag, path or name without custom work.

### 7. Common causes of flaky tests

- FACT: Definition: a flaky test has a non-deterministic outcome for the same code version. [Luo 2014]
- FACT: Study of 201 commits that likely fix flaky tests in 51 open-source projects. Of 161 analyzed commits: async wait 45%, concurrency 20%, test order dependency 12%; other categories include resource leak, network, time, I/O, randomness, floating point, unordered collections. 78% of flaky tests were flaky when first written. 24% of fixes changed the code under test, not the test. [Luo 2014]
- FACT: Fixes: 54% of async wait fixes used `waitFor` style waiting. 74% of order-dependency fixes cleaned shared state between runs. 31% of concurrency fixes added locks. [Luo 2014]
- FACT: Fowler's list: lack of isolation, asynchronous behavior, remote services, time, resource leaks. He suggests quarantining non-deterministic tests in a separate suite so they do not erode trust, then fixing them fast. [Fowler Non-determinism]
- FACT: Google reports a flaky rate near 0.15%. Past about 1% the tests lose value. Reruns hide the cause. Common sources: clock time, thread scheduling, network latency. [SWE Ch.11]
- FACT: UI and end-to-end tests are "notoriously flaky" (browser quirks, timing, animations, pop-ups); the pyramid's remedy is fewer of them. [Fowler Pyramid]
- Disagreement on retries: Google book says reruns only delay the fix. Fowler says quarantine, then fix. Blog commenters report teams that rerun and treat marking as flaky as permission to ignore. [SWE Ch.11; Fowler Non-determinism; Google blog comments (weak source)]
- INFERENCE: Fallback flaky checklist: sleeps, shared state, order, clock, randomness, ports and temp paths, network, threads, unordered collections, leaked resources, floating point equality.

### 8. Review criteria for existing tests

- FACT: Brittle tests over-specify outcomes or use heavy boilerplate and fail on unrelated changes. Misused mocks are a leading cause. "Change-detector" tests fail on any production change. [SWE Ch.11, Ch.13]
- FACT: Do not treat coverage as a goal: "a useful tool for finding untested parts" but "of little use as a numeric statement of how good your tests are". 100% may signal tests written for the metric. [Fowler TestCoverage]
- FACT: If a higher-level test finds a bug and no lower-level test fails, write a lower-level test. Remove redundant higher-level tests. [Fowler Pyramid]
- FACT: Review snapshots as code; watch for regenerate-on-failure habits. [Jest docs]
- INFERENCE: Candidate review criteria (map to Beck's desiderata): fails when behavior breaks (behavioral); survives a refactor (structure-insensitive); one reason to fail and a clear name (specific, readable); no sleep, clock, network or shared state (deterministic, isolated); fast enough for its size; at the lowest sensible level; no logic in the test; a mock only where a side effect cannot be read.

## Draft outline of the general fallback guidance (candidate content, not a decision)

1. Terms. Size (small, medium, large) by what the test may touch. Scope (unit, integration, contract, end-to-end). Defer to the repo's test rules file where it defines terms.
2. Pick a level. Lowest level that fails if the change is wrong. Table: pure logic, one external system, shared interface, big structured output, wide input space, critical user path.
3. Make it runnable. Fast, isolated, deterministic, parallel-safe, groupable. Checklist per item.
4. Seams and doubles. Seam list. Order: real, fake, stub, mock. Keep a fake honest with a contract test.
5. Failure paths and edges. Checklist.
6. Name and structure. Behavior names, arrange-act-assert, one condition per test, straight-line, public API.
7. Flaky causes. Checklist and the rule: find the cause; quarantine only with an owner and a date (INFERENCE).
8. Review criteria. Checklist above.
9. Hand-offs. Commands, groups and frameworks come from the repo's test rules file (setup mode). When absent, say so and propose, do not invent.

## Options (unranked, owner decides)

A. Definition of "unit": (1) define by scope (Google); (2) define by properties only (fast, isolated, deterministic) and avoid the word; (3) follow the repo's own usage and ask when absent.
B. Test doubles default: (1) Google order real > fake > stub > mock; (2) classical (real, double only when awkward) as a flat rule; (3) mention both camps and let the repo's rules file pick.
C. Grouping axis for "run only this group": (1) by size tag; (2) by layer (unit, integration, end-to-end); (3) by area (module or path); (4) a mix.
D. Flaky policy in the fallback: (1) fix the cause, never retry; (2) quarantine with owner and date, then fix; (3) bounded retry plus tracked fix. (Policy about when tests run belongs to the audit effort, out of scope on the map.)
E. Depth: (1) one short file of checklists; (2) one file per topic loaded only when needed.
F. Property-based and snapshot tests: (1) include as kinds with short guidance; (2) mention by name only and defer to language entries.

## Gaps

- No primary source read for boundary-value and error-path design (see topic 4).
- Google blog posts on test sizes and flaky tests returned only comments through the fetch tool. I used the SWE book chapter instead. The 2016 post's figures (for example 1.5% of runs flaky) were not verified.
- Luo 2014 covers 51 open-source projects, mostly Java. Rates may differ in other languages. (INFERENCE)
- Meszaros, "xUnit Test Patterns" (test smells, test double names) not read directly; names came via Fowler.
- Nothing read on parallel-safety beyond isolation sources. The checklist is INFERENCE.
- Existing skills: the map asks to check existing skills and the installed TDD skill. Not done here; this ticket covers external sources only. See `testing-existing-skills.md` (ticket 811).
- No eval of whether an agent follows this guidance (UNTESTED).

## Sources

Read (OK):
- Fowler, "UnitTest": https://martinfowler.com/bliki/UnitTest.html
- Fowler, "Mocks Aren't Stubs": https://martinfowler.com/articles/mocksArentStubs.html
- Fowler / Vocke, "The Practical Test Pyramid": https://martinfowler.com/articles/practical-test-pyramid.html
- Fowler, "Eradicating Non-Determinism in Tests": https://martinfowler.com/articles/nonDeterminism.html
- Fowler, "TestCoverage": https://martinfowler.com/bliki/TestCoverage.html
- Winters, Manshreck, Wright, "Software Engineering at Google", Ch.11 Testing Overview: https://abseil.io/resources/swe-book/html/ch11.html
- Same, Ch.12 Unit Testing: https://abseil.io/resources/swe-book/html/ch12.html
- Same, Ch.13 Test Doubles: https://abseil.io/resources/swe-book/html/ch13.html
- Beck, Test Desiderata: https://testdesiderata.com/
- Jest, Snapshot Testing: https://jestjs.io/docs/snapshot-testing
- Pact docs: https://docs.pact.io/
- Hypothesis docs, introduction: https://hypothesis.readthedocs.io/en/latest/tutorial/introduction.html
- Luo, Hariri, Eloussi, Marinov, "An Empirical Analysis of Flaky Tests", FSE 2014 (PDF, read as text): https://mir.cs.illinois.edu/lamyaa/publications/fse14.pdf
- Claessen and Hughes, "QuickCheck: A Lightweight Tool for Random Testing of Haskell Programs", ICFP 2000 (PDF, abstract and introduction only): https://www.cs.tufts.edu/~nr/cs257/archive/john-hughes/quick.pdf

Read but body missing (comments only, used as weak evidence or not at all):
- Google Testing Blog, "Flaky Tests at Google and How We Mitigate Them": https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html
- Google Testing Blog, "Test Sizes": https://testing.googleblog.com/2010/12/test-sizes.html

Read, nothing useful:
- Google Research, "The State of Continuous Integration Testing at Google": https://research.google/pubs/the-state-of-continuous-integration-testing-google/ (abstract has no figures)

Failed: none by HTTP error. The GitHub issues #812 and #810 were read with `gh issue view --json` (plain `gh issue view` fails on a Projects (classic) error).
