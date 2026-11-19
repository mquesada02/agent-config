# General rules (GEN-*)

Neutral rules for CI/CD (Continuous Integration and Continuous Delivery) in any language and any CI system. They use no key, tool or action name of one platform. The sources are DORA (DevOps Research and Assessment), OWASP (Open Worldwide Application Security Project), SLSA (Supply-chain Levels for Software Artifacts), the OpenSSF (Open Source Security Foundation) guides and NIST SSDF (National Institute of Standards and Technology Secure Software Development Framework). Each rule names its source or says `skill rule`, and its `From` field lists the skill rules that hold the same idea. This file is the single source of truth for these rules.

- Every GEN rule is a judgement check. No script checks it. The rules give advice only, and no GEN rule tells the skill to write a file.
- The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`). The level of a GEN rule is the most severe level among the skill rules in its `From` field.
- A source name in the Source bullet is a name of the `## Sources` list. A section id can follow it.
- General mode loads this file (see SKILL.md, "Loading by need").

## Pipeline stages

### GEN-01
- **Severity:** required
- **Rule:** Each independent check (lint, tests, type check, build) is its own job, and the jobs run in parallel. A dependency between two jobs exists only when the later job needs the result or the output of the earlier job.
- **Check:** judgement
- **Fix:** Split a job that holds several independent checks into one job for each check. Remove each dependency between jobs that share no result and no output.
- **Source:** DORA
- **From:** GRAPH-01, GRAPH-02

### GEN-02
- **Severity:** required
- **Rule:** The pipeline builds the artifact once for each run and passes that same artifact to the later jobs. A deploy job does not install dependencies and does not build.
- **Check:** judgement
- **Fix:** Move the build into one build job that stores its output as an artifact. Make each later job, a deploy job included, fetch that artifact and use it.
- **Source:** DORA
- **From:** GRAPH-06, DEPLOY-01

### GEN-03
- **Severity:** required
- **Rule:** The test matrix covers only the language versions and the operating systems that the project promises to support. On a pull request, the matrix stops at the first failed leg. On the main branch, every leg finishes.
- **Check:** judgement
- **Fix:** Reduce the matrix to the promised versions and systems. Set the matrix to stop early on a pull request and to finish all legs on the main branch.
- **Source:** skill rule
- **From:** GRAPH-03, GRAPH-04

### GEN-04
- **Severity:** required
- **Rule:** A test job that runs longer than 10 minutes, by its measured run time, is split into shards. Independent suites run as parallel jobs of about 2 minutes or more each. The reports of the shards are merged. The number of test workers never exceeds the CPU (central processing unit) count of the runner.
- **Check:** judgement
- **Fix:** Measure the run time of the test job first. Split it only when the time is above 10 minutes, merge the reports, and set the worker count to the CPU count of the runner or lower.
- **Source:** skill rule
- **From:** GRAPH-05, GRAPH-07, COST-06

### GEN-05
- **Severity:** required
- **Rule:** One gate job, which waits for all other jobs and accepts a skipped job as a pass, is the only required check of the pipeline.
- **Check:** judgement
- **Fix:** Add one gate job that depends on all required jobs and fails when one of them failed. Require only this job in the branch rules.
- **Source:** skill rule
- **From:** NAME-08

### GEN-06
- **Severity:** required
- **Rule:** Every pipeline has a human name. There is one CI pipeline with a fixed name, and each other pipeline is named by its purpose. Job ids follow one case style. A job name and a step name each state one purpose, a step name is a short imperative phrase with no id and no version, and a matrix job name shows each value that varies.
- **Check:** judgement
- **Fix:** Name each pipeline, job and script step. Use one case style for the job ids, split a job that does several tasks, and add the varying values to the names of matrix jobs.
- **Source:** skill rule
- **From:** NAME-01, NAME-02, NAME-03, NAME-04, NAME-05, NAME-06, NAME-07

### GEN-07
- **Severity:** required
- **Rule:** A long inline script lives in a repo script that a developer can also run locally. A step comment is short, and a long reason goes to the docs. Pipeline code that is copied between pipelines moves to the shared-template feature of the CI system.
- **Check:** judgement
- **Fix:** Move each long inline script to a script file in the repo and call it from the step. Shorten the step comments. Replace copied pipeline code with a shared template.
- **Source:** skill rule
- **From:** MAINT-01, MAINT-02, MAINT-03

### GEN-08
- **Severity:** required
- **Rule:** Every job has a timeout that comes from measured run times. A deploy job has a timeout that stays below the lifetime of its credential.
- **Check:** judgement
- **Fix:** Set a timeout on each job, a little above the normal run time. For a deploy job, keep the timeout below the lifetime of the credential that it uses.
- **Source:** skill rule
- **From:** COST-04, DEPLOY-09

### GEN-09
- **Severity:** required
- **Rule:** A checkout is shallow unless a step needs the history of the repo.
- **Check:** judgement
- **Fix:** Fetch only the latest commit, and fetch more history only for the steps that need it.
- **Source:** skill rule
- **From:** COST-08

### GEN-10
- **Severity:** required
- **Rule:** The runner image is pinned to a fixed version. A job uses an extra operating system only when the project promises to support it.
- **Check:** judgement
- **Fix:** Name a fixed runner image version in place of a moving label. Remove each runner of an operating system that the project does not support.
- **Source:** skill rule
- **From:** COST-07

### GEN-11
- **Severity:** required
- **Rule:** A change that touches unrelated files skips the work that it does not affect, with a visible notice and with a gate that accepts the skip. On a pull request in a monorepo, the pipeline runs only the affected packages. On the main branch, it runs all of them. A change that touches only docs skips the deploy with a visible notice.
- **Check:** judgement
- **Fix:** Add a change-detection step in the pipeline that decides which work to run. Make the gate job accept the skipped jobs, and print a notice when a deploy is skipped.
- **Source:** skill rule
- **From:** COST-03, MONO-01, DEPLOY-08

### GEN-12
- **Severity:** required
- **Rule:** The dependency audit runs in its own job, on a schedule and when the lockfile changes. It does not run inside a test job.
- **Check:** judgement
- **Fix:** Move the audit to its own job. Start it on a schedule and on each change of the lockfile.
- **Source:** OpenSSF Concise Guide; NIST SSDF
- **From:** SEC-10

## Triggers per event

### GEN-13
- **Severity:** required
- **Rule:** The CI pipeline runs once for each change. A branch that has an open pull request does not run the pipeline twice, once for the push and once for the pull request.
- **Check:** judgement
- **Fix:** Start the pipeline on a push to the main branch and on a pull request, and not on a push to a branch that has a pull request.
- **Source:** skill rule
- **From:** COST-01

### GEN-14
- **Severity:** required
- **Rule:** A new run on a pull request cancels the older run of the same pull request. Runs that write to one environment, a deploy and a rollback included, run one at a time and are never cancelled in the middle.
- **Check:** judgement
- **Fix:** Group the runs by pull request and cancel the older ones. Group the runs that write to one environment, run them in order, and do not cancel them.
- **Source:** skill rule
- **From:** COST-02, ROLLBACK-06

### GEN-15
- **Severity:** required
- **Rule:** A release starts only from the main branch or from a manual start. No other event starts a release.
- **Check:** judgement
- **Fix:** Limit the start events of the release pipeline to the main branch and to a manual start by a person.
- **Source:** skill rule
- **From:** RELEASE-05

## Caching

### GEN-16
- **Severity:** required
- **Rule:** A job installs dependencies from the frozen lockfile, and the cache holds only the download store of the package manager. The cache never holds the installed result or the build output.
- **Check:** judgement
- **Fix:** Use the frozen-lockfile install command of the package manager. Cache only its download store, and key the cache by the hash of the lockfile.
- **Source:** skill rule
- **From:** COST-05

### GEN-17
- **Severity:** required
- **Rule:** A pipeline that has privileged credentials, such as a release or a deploy pipeline, does not save a cache. A cache that an untrusted run wrote cannot reach a privileged run.
- **Check:** judgement
- **Fix:** Turn off the cache save in each privileged pipeline.
- **Source:** skill rule
- **From:** SEC-09

### GEN-18
- **Severity:** required
- **Rule:** The publish job installs from the lockfile and uses no cache.
- **Check:** judgement
- **Fix:** Remove the cache from the publish job and install from the frozen lockfile.
- **Source:** skill rule
- **From:** PUBLISH-02

## Secrets and permissions

### GEN-19
- **Severity:** required
- **Rule:** The token of the pipeline is read-only by default. A job that needs a write scope states that scope for itself, with a one-line reason.
- **Check:** judgement
- **Fix:** Set the default permission of the pipeline token to read-only. Give each write scope to the one job that needs it, and add a short reason next to it.
- **Source:** OWASP CICD-SEC-5; OpenSSF Scorecard
- **From:** SEC-03

### GEN-20
- **Severity:** critical
- **Rule:** An untrusted value, such as a branch name, a pull request title or an input, never goes into a shell script text. The pipeline passes each such value to the script as an environment value and the script quotes it.
- **Check:** judgement
- **Fix:** Pass each value through an environment value and use it quoted in the script. Do not build the script text from the value.
- **Source:** OWASP CICD-SEC-4
- **From:** SEC-04

### GEN-21
- **Severity:** critical
- **Rule:** The pipeline never runs code from an untrusted source, such as a fork or the head of a pull request, with privileged credentials. A run of unreviewed code has no secrets and runs on an isolated node.
- **Check:** judgement
- **Fix:** Split the pipeline: run the untrusted code in a run with no secrets and a read-only token, and give the privileged run only reviewed code. Require a manual approval for a run that comes from a fork.
- **Source:** OWASP CICD-SEC-4
- **From:** SEC-07

### GEN-22
- **Severity:** critical
- **Rule:** A checkout leaves no credential on the disk after it finishes. A private submodule or a private dependency is fetched with a token of narrow scope, and the token never appears in a URL or in a repo config file.
- **Check:** judgement
- **Fix:** Turn off credential storage in the checkout step. Fetch private code with a short-lived token of narrow scope that a step passes as an environment value.
- **Source:** OWASP CICD-SEC-6
- **From:** SEC-05, SEC-06

### GEN-23
- **Severity:** required
- **Rule:** A job gets only the secrets that it names. No job or called pipeline receives all secrets of the repo.
- **Check:** judgement
- **Fix:** List the needed secrets for each job or called pipeline by name, and remove each blanket pass of all secrets.
- **Source:** OWASP CICD-SEC-6
- **From:** SEC-08

### GEN-24
- **Severity:** required
- **Rule:** A pipeline that deploys or publishes uses a short-lived federated identity. Each environment has its own identity, and no long-lived key is stored in the CI system. A job gets the identity only when it runs no install and no build.
- **Check:** judgement
- **Fix:** Set up federated trust between the CI system and the target. Create one identity for each environment, delete each stored long-lived key, and give the identity only to jobs that run no install and no build.
- **Source:** OWASP CICD-SEC-6
- **From:** DEPLOY-04, PUBLISH-01

### GEN-25
- **Severity:** suggestion
- **Rule:** A deploy credential belongs to one environment. It is not a setting of the whole repo.
- **Check:** judgement
- **Fix:** Move each deploy credential from the repo level to the environment that uses it.
- **Source:** OWASP CICD-SEC-6
- **From:** PROTECT-08

### GEN-26
- **Severity:** required
- **Rule:** The release job uses a credential of narrow scope that belongs to a machine identity. It does not use the personal token of a developer. The credentials of an app identity are kept in an environment, and the job names that environment.
- **Check:** judgement
- **Fix:** Replace the personal token with the built-in token of the pipeline or with a token of an app identity, keep the app credentials in an environment, and grant the token only the scopes that the release needs.
- **Source:** OWASP CICD-SEC-2
- **From:** RELEASE-04

### GEN-27
- **Severity:** required
- **Rule:** A missing setting or secret makes the deploy fail with a clear error. The deploy never skips a step in silence because a value is empty.
- **Check:** judgement
- **Fix:** Check each required value at the start of the deploy job, and fail with an error message that names the missing value.
- **Source:** skill rule
- **From:** DEPLOY-06

### GEN-28
- **Severity:** suggestion
- **Rule:** A comment in a pipeline file never claims a protection that the platform does not show. A comment that names a setting, such as a required reviewer, is true on the platform.
- **Check:** judgement
- **Fix:** Check each such comment against the real settings of the platform. Correct the comment or the setting.
- **Source:** skill rule
- **From:** PROTECT-07

## Pinning

### GEN-29
- **Severity:** required
- **Rule:** Third-party pipeline code is pinned to an immutable reference, such as a full commit hash, and not to a tag or a branch that can move. The reference has a comment with the human-readable version.
- **Check:** judgement
- **Fix:** Replace each moving reference with the full commit hash of the version that you use, and add the version as a comment.
- **Source:** skill rule
- **From:** SEC-01

### GEN-30
- **Severity:** required
- **Rule:** An automatic tool opens update requests for the pinned pipeline dependencies, so the pins do not go stale.
- **Check:** judgement
- **Fix:** Turn on a dependency update tool for the pipeline dependencies, on a weekly schedule.
- **Source:** skill rule
- **From:** SEC-02

### GEN-31
- **Severity:** suggestion
- **Rule:** When a registry binds its trust to the file name of the publish pipeline, that file name stays stable.
- **Check:** judgement
- **Fix:** Keep the file name of the publish pipeline. When you must rename it, update the trust entry of the registry in the same change.
- **Source:** skill rule
- **From:** PUBLISH-05

## Release and deploy safety

### GEN-32
- **Severity:** required
- **Rule:** Each stage is a separate environment. A deploy to production needs proof that the same artifact deployed well to the stage before it.
- **Check:** judgement
- **Fix:** Create one environment for each stage. Make the production deploy check the record of a successful earlier stage for the same commit.
- **Source:** DORA
- **From:** DEPLOY-02

### GEN-33
- **Severity:** required
- **Rule:** A deploy to production checks the digest of the stored artifact, so production gets the same artifact that the earlier stage tested.
- **Check:** judgement
- **Fix:** Store the digest of the artifact when it is built, and compare it with the digest of the artifact that the deploy job downloads. Stop the deploy when they differ.
- **Source:** OWASP CICD-SEC-9; SLSA v1.2 Build L2
- **From:** DEPLOY-03

### GEN-34
- **Severity:** required
- **Rule:** After a deploy, the pipeline checks the version that is live, and not only a successful response from the service.
- **Check:** judgement
- **Fix:** Add a step after the deploy that reads the live version from the service and fails when it is not the deployed version.
- **Source:** DORA
- **From:** DEPLOY-05

### GEN-35
- **Severity:** suggestion
- **Rule:** The deploy uses the native step-by-step rollout of its target, with alarms. The pipeline does not turn off the native automatic rollback of the target.
- **Check:** judgement
- **Fix:** Use the gradual rollout feature of the target with alarms that stop it. Remove each setting that disables the automatic rollback.
- **Source:** DORA
- **From:** DEPLOY-07, ROLLBACK-05

### GEN-36
- **Severity:** suggestion
- **Rule:** A pull request that changes the infrastructure or the deploy shows the native preview of the change, such as a plan, a diff or a change set.
- **Check:** judgement
- **Fix:** Add a job on pull requests that produces the preview of the target and shows it to the reviewer.
- **Source:** DORA
- **From:** DEPLOY-10

### GEN-37
- **Severity:** required
- **Rule:** A rollback is a manual action on a chosen release tag, and the version comes from that tag and not from free text. A rollback never builds. It reuses the stored artifact and keeps all deploy checks.
- **Check:** judgement
- **Fix:** Make the rollback start by hand with a tag as input. Make it fetch the stored artifact of that tag and run the same checks as a deploy.
- **Source:** DORA
- **From:** ROLLBACK-01, ROLLBACK-02

### GEN-38
- **Severity:** required
- **Rule:** The artifacts that a rollback needs stay in storage that lasts longer than the retention time of the CI artifacts.
- **Check:** judgement
- **Fix:** Copy each release artifact to durable storage when it is deployed, and keep it as long as a rollback to it can be needed.
- **Source:** skill rule
- **From:** ROLLBACK-03

### GEN-39
- **Severity:** suggestion
- **Rule:** A rollback of several production targets runs one target at a time.
- **Check:** judgement
- **Fix:** Run the targets in sequence, and stop the sequence at the first failed target.
- **Source:** skill rule
- **From:** ROLLBACK-04

### GEN-40
- **Severity:** required
- **Rule:** The default branch needs a pull request and one required check. It allows no force push and no bypass of its rules, not even for an administrator.
- **Check:** judgement
- **Fix:** Set branch rules that require a pull request and the gate job, block force pushes, and remove each bypass.
- **Source:** OWASP CICD-SEC-1; OpenSSF SCM Best Practices
- **From:** PROTECT-01, PROTECT-05

### GEN-41
- **Severity:** required
- **Rule:** Release tags are annotated and made on a commit of the main branch. They are protected: only a few identities can create them, and nobody can update or delete them.
- **Check:** judgement
- **Fix:** Create each release tag as an annotated tag on a commit of the main branch. Set a tag rule that limits creation and blocks update and delete.
- **Source:** skill rule
- **From:** PROTECT-02, RELEASE-02, RELEASE-03

### GEN-42
- **Severity:** required
- **Rule:** Each deploy environment accepts only the branches and tags that may deploy to it.
- **Check:** judgement
- **Fix:** Set a ref policy on each environment, for example the main branch and release tags for production.
- **Source:** OWASP CICD-SEC-1
- **From:** PROTECT-03

### GEN-43
- **Severity:** required
- **Rule:** A deploy to production needs a human approval. The author of the change cannot give that approval.
- **Check:** judgement
- **Fix:** Set required reviewers on the production environment, and turn on the setting that stops an author from approving the own change.
- **Source:** skill rule
- **From:** PROTECT-04

### GEN-44
- **Severity:** required
- **Rule:** The repo uses one release tool. Each release produces release notes or a changelog.
- **Check:** judgement
- **Fix:** Keep one release tool for the repo, and make it write the release notes or the changelog for each release.
- **Source:** skill rule
- **From:** RELEASE-01, RELEASE-06

### GEN-45
- **Severity:** required
- **Rule:** A repo with several packages publishes them in dependency order, with a tool that knows that order.
- **Check:** judgement
- **Fix:** Use a publish tool that sorts the packages by their dependencies, and publish through it only.
- **Source:** skill rule
- **From:** PUBLISH-03

### GEN-46
- **Severity:** suggestion
- **Rule:** A publish step skips a version that already exists in the registry, so a re-run of the publish is safe.
- **Check:** judgement
- **Fix:** Ask the registry whether the version exists before the publish, and skip the publish when it does.
- **Source:** skill rule
- **From:** PUBLISH-04

## Sources

- DORA: https://dora.dev/capabilities/
- OWASP: https://owasp.org/www-project-top-10-ci-cd-security-risks/
- SLSA: https://slsa.dev/spec/v1.2/
- OpenSSF Concise Guide: https://best.openssf.org/Concise-Guide-for-Developing-More-Secure-Software
- NIST SSDF: https://csrc.nist.gov/pubs/sp/800/218/final
- OpenSSF Scorecard: https://github.com/ossf/scorecard/blob/main/docs/checks.md
- OpenSSF SCM Best Practices: https://best.openssf.org/SCM-BestPractices/
