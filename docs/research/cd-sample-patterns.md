## Resolution: catalog of real CD patterns in the sample repos

Source: the workflow files and the file history of the sample repos, read with read-only calls. Repos are anonymous. No workflow text is copied.

## 1. Coverage

- 25 private repos in two orgs. 20 have a workflows folder. 5 have none.
- 10 repos hold CD workflows. 38 CD workflow files in total (deploy, release, promote, rollback, apply, publish, scheduled audit).
- The other 10 repos with workflows (the TypeScript ingestion family) hold CI only. One of them says in a comment that its deploy path was deleted.
- I read in full: the CD files of repos B, D, E, F, G, H and the Terraform apply files of repo C. The thin caller files of repos I, J and K have the same shape as repo H. I scanned them for triggers, inputs and the called template, not line by line.
- History: the CD files are young and have few commits (2 to 5 each). The template hub (repo G) has the most (16 for the deploy template, 11 for the legacy deploy, 8 for the rollback).
- Labels. Labels B to E come from the CI catalog and I could match them by shape: B = the SQL database repo, C = the Terraform repo, D = the TypeScript frontend, E = the landing site. The new labels start at F:
  - Repo B: SQL database repo. Its only CD file publishes a signed migration bundle.
  - Repo C: Terraform infrastructure repo. 5 CD files (apply, apply-stage, a scheduled settings audit, a manual DNS test, a manual runner smoke test) and one plan-on-PR file.
  - Repo D: TypeScript frontend. 1 deploy file, 3 environments.
  - Repo E: landing site. 1 deploy file.
  - Repo F (new): Java backend on Lambda. 2 CD files (release, prod). 3 environments.
  - Repo G (new): the template hub. A repo of reusable workflows and one composite action that the Node app repos call. 7 CD files. Its own CI is one unit-test file.
  - Repos H, I, J, K (new): four app repos (Node) that call the template hub. 6 CD files each for H, I and J, 3 for K (a frontend that has no build step in the release flow).

Not found anywhere: npm publish, a package registry, container images, GitHub Releases (0 releases in all 6 repos that I counted), Kubernetes, Helm, CDK, SAM, Serverless. See section 2.

## 2. Deploy targets and IaC tools

Deploy targets (10 CD repos):

| Target kind | Repos | Count |
|---|---|---|
| AWS Lambda, zip uploaded to S3, then update-function-code and publish-version | F, G (template), H, I, J, K (callers) | 6 |
| Static site in S3 behind a CDN, with cache invalidation | D, E, G (dashboard path of the template) | 3 |
| Signed bundle in a write-once S3 bucket (no deploy; a separate pipeline reads it) | B | 1 |
| Terraform apply across an AWS Organization (stages: org, baseline, shared, nonprod, prod) | C | 1 |
| Legacy Lambda per account (same zip, other account, own floor) | G (template), H, I, J, K | 5 |

IaC tools:

| Tool | Where | Count |
|---|---|---|
| Terraform (version file, validate, plan on PR, apply on push) | C | 1 repo |
| CloudFormation (template lint in CI only; the stack is deployed outside the workflow) | one ingestion repo | 1 |
| None in the workflow (Lambda code update only; infra lives in repo C or a separate infra repo) | all other CD repos | 9 |

Other AWS services the CD jobs call: S3, Lambda, CloudFront, SSM Parameter Store (a minimum safe release value), KMS (signing), STS (OIDC). No ECS, no ECR, no EKS, no CodeDeploy, no Amplify in any workflow.

Runners: GitHub-hosted for all CD. Repos C, D, E and F pin `ubuntu-24.04`. Repos G to K use `ubuntu-latest`. One CI job in repo D uses a self-hosted pool by variable.

## 3. Patterns by family

Each line is: number, mark, repos, neutral description.

### Naming

1. bad: G, H, I, J, K: workflow names and job names are bare ids (`release`, `deploy`, `build`, `tag`). The called template jobs have no `name:`. The run page shows only job ids and matrix keys.
2. good: F, D: job names say what happens and carry the matrix value (`Deploy staging · <target>`). A comment says that the production workflow reads two job names and two artifact names, so they are a contract, listed in a doc.
3. bad: F: a job is found by NAME by another workflow (the prod workflow reads the job `Record the release` of the release workflow). A rename breaks production deploys. The mitigation is a comment plus a doc; no test pins it.
4. bad: G, H, I, J, K: the same workflow name `main-merge` or `deploy-legacy` exists in the hub and in every caller. The 4 caller repos use 3 different file names for the same flow (`main-merge`, `main`, `Main merge`).
5. good: D, E: the job id and the job name are equal and short (`dev`, `staging`, `prod`, `deploy`).

### Job graph

6. good: F: build once, upload once, deploy per target with a matrix and `fail-fast: false`, then a gate job that records the release only when every target ran. The gate runs with `!cancelled()` and fails when its needs were skipped, so a green run never lacks a release record.
7. good: G: `plan -> stage per tenant -> deploy staging -> tag -> back-merge`. The `tag` job takes `needs` of all target jobs and runs a gate command first: no tag unless every target passed (a skipped target counts as a failure).
8. good: D: staging builds once and stores the build as an artifact with a record of the commit. The prod job downloads that artifact and verifies it. Prod never rebuilds.
9. bad: D: the dev job and the staging job each run install and build on their own. Only staging output reaches prod, so dev builds a different artifact than the one that is promoted.
10. bad: E: one job runs install, build, three upload steps, delete, and invalidation in sequence. The three uploads are ordered on purpose, so this is not a matrix case, but the whole deploy is one job with no rollback step.
11. bad: H, I, J: a matrix builds the same zip four times (one per environment) for the legacy flow, although the build does not depend on the environment value (the artifact name does).
12. bad: H, I, J: the release flow builds twice (new account and legacy) with the same composite action in two jobs.
13. good: C: stages as reusable workflow calls with `needs` and `if: !failure() && !cancelled()`, so a failed stage stops every later stage and a stage with nothing to apply is skipped. A job at the end that checks that the commit is still the tip of the main branch.
14. bad: G: `deploy.yml` holds 5 modes (stage, deploy, prod, redeploy, dashboard) in 967 lines. Each mode copies the same steps (verify, role, update, wait, publish). It is one workflow file that is hard to read and 16 commits show frequent edits.

### Cost

15. bad: G, H, I, J, K: no `timeout-minutes` on any CD job (the default is 360 minutes). F, D and E have none either. Only repos B and C set limits (10 and 55 min). A stuck Lambda wait or smoke curl can run for 6 hours.
16. good: B: the limit is 10 minutes with a comment that says why (shorter than the OIDC token lifetime, so the job fails fast instead of dying with an expired token).
17. good: C, D, E, F: every deploy uses `concurrency` with `cancel-in-progress: false`, and a comment says that GitHub keeps one pending run per group. F uses one group per kind of ref so a develop push cannot replace a pending tag run.
18. bad: G, H, I, J, K: the deploy template has no `concurrency` block. Two promotions or a rollback during a deploy can write to the same tenant at once. Only the tag job and the promote job have a group.
19. good: D, E, F: a docs filter on a deploy push trigger is acceptable because the deploy is not a required check, and the comments say so. F keeps the list in one script and a test compares it with the workflow. The bad form is the same filter on a required CI check (see the CI catalog).
20. good: D, E, F: the CD build jobs use the toolchain cache of the setup action (pnpm or Maven), so a rebuild does not download every dependency.

### Security

21. good: all repos: `permissions: {}` at workflow level, then the minimum per job (`contents: read`, `id-token: write` only on the jobs that assume a role).
22. good: B, C, D, E, F, G, H to K: AWS access by OIDC with a role per environment and per action (upload, deploy, apply, plan, publish). No long-lived AWS key in any CD workflow.
23. good: D, E, F: the AWS role is assumed only after install and build, with a comment that scripts in install and build never see the role. F builds in a job that holds no credentials at all and uploads from another job.
24. good: B: the OIDC trust and the tag ruleset limit the publisher role to tags of one pattern. The workflow adds a check that the tagged commit is an ancestor of the main branch, and says it is a defense in depth and not the main control.
25. good: B: the publish payload is an allow-list of file types, rejects symlinks, whitespace and backslashes in names, signs a manifest with a KMS key, verifies the signature before upload and uploads the signature last as a completion marker.
26. bad: D: the three role ARNs (with an account id) are written in the workflow file. E and F read them from variables or from a matrix built from variables.
27. bad: H, I, J, K: reusable workflows are pinned to a version tag (`@v2.0.1`), not to a commit SHA. Third-party actions are pinned to SHA with a bare version comment. The pin is the weak link: a tag can move. Tag immutability rulesets exist in repos B, G and H, which reduce the risk for tags of those repos.
28. bad: H, I, J, K, G: the callers use 3 template versions at once (a v1.x for dev and legacy, two v2.x for the rest). Pins are bumped by hand; the template comments say to edit every pin in the hub before cutting a new tag. This is the drift of CI family A in CD form.
29. good: G: the role of the person who runs a promotion or a rollback is read with the triggering actor (not the first actor of a re-run) and checked before any other step. The tag is created by a GitHub App token that exists in one job of one environment.
30. good: F, G, B, D: `persist-credentials: false` on every checkout. G fetches tags with a header set only for one command and masks it.
31. bad: G: a long shell loop and about 15 `jq` calls build JSON files inside a workflow step (tag, candidate, promote steps), next to a Python module with the real decisions. The comments say the shell only gathers facts. It is better than inline logic, but the step is still 90 lines.
32. good: C, F, G: values from the event context go through `env:` and not into `run:` text.
32b. bad: B: one step puts a step output directly into the `run:` text (the version). An earlier step validates the value, so the risk is low, but the rule "no expression in `run:`" has an exception that a reader must trust.

### Deploy

33. good: F, D: three environments (dev, staging, prod). A push to the develop branch deploys dev, a version tag deploys staging, a merge of the release PR into the main branch deploys prod. Prod deploys only the artifact that ran in staging.
34. good: F: the staging job records the SHA-256 of the zip. The prod job refuses a different hash and a release PR that has no staging run.
35. good: G: the deploy job reads a minimum safe release from SSM and refuses a version below it (the floor check) before any change to the tenant.
36. good: G: after publish-version, the prod mode runs a smoke GET through the CDN domain of the tenant with retry. A failed smoke fails the job.
37. bad: G: the smoke check is one status-code check of one request. It does not check a version header or a body, so an old version that answers 200 passes.
38. good: E: the site upload runs in three steps (assets with a long immutable cache, then the HTML with a short cache, then delete of old files) so a visitor never gets HTML that points to a missing asset.
39. bad: E: the deploy job is skipped, not failed, when two org variables are empty. A silent skip shows a green run for a deploy that did not happen. D handles the same case by a step that writes a notice and a summary.
40. good: F: a deploy with no targets does not fail silently. A step writes a summary line and a notice, and the release job fails when no leg ran.
41. bad: H, I, J: every deploy needs three variables for each tenant (account id, domain) passed as JSON built with `format()` in the caller. Adding a tenant means editing 3 workflow files in each caller repo.
42. good: H, I, J, K, G: a `dry-run` input skips every AWS call and still runs the checks. A pull request runs the deploy call as a dry run, so the deploy workflow is tested before merge.
43. bad: F: the production deploy runs on `push` to the main branch, and the only approval is the merged release PR. There is no environment approval step. The comment says this on purpose. It is a risk when the main branch ruleset has a bypass list.

### Release

44. good: F, G: tags drive the flow. A candidate tag `vX.Y.Z-rc.N` is made on each merge to the main branch (G, by a GitHub App). A final tag `vX.Y.Z` is made by a manual promote and triggers the prod deploy. Annotated tags only, and the prod workflow checks that the tag is annotated.
45. good: G: the candidate number is computed by a tested Python module with a retry on a tag collision (3 tries). The module has unit tests in CI.
46. good: D, F: the tag must be on the develop branch. The check is `merge-base --is-ancestor` after a checkout with full history.
47. bad: all repos: no GitHub Release, no changelog and no release notes are made in any workflow (0 releases). The tag message is the only record of what a version holds.
48. good: G: a back-merge PR from the main branch into the develop branch is opened by the flow when the main branch has commits that develop lacks.
49. good: G: the plan step fails when a run has no target, and the tag gate refuses a tag when any target failed. A red legacy deploy does not stop the new-account staging deploy, but it blocks the tag.

### Rollback

50. good: G, H, I, J: rollback is a manual dispatch on an OLDER final tag. The version comes from the ref, not from an input, so a typo cannot choose a version. The run uses the workflow files of that tag.
51. good: G: a rollback never builds, never stages and never creates a tag. It reuses the prod deploy mode and keeps all its checks (the floor, the zip exists, the smoke). It stops with a clear message when the old zip has expired.
52. good: G: a prod rollback deploys tenants one at a time (`max-parallel: 1`, `fail-fast: true`).
53. good: G: a staging rollback runs on the main branch with a candidate tag input.
54. bad: C, D, E, B: no rollback workflow. C has a break-glass runbook (laptop apply). D and E redeploy by re-running an older run or by tagging again. B has no way to delete a bad bundle except an alarmed manual delete (the write-once bucket); a pre-upload verify exists to avoid that.
55. bad: G, H, I, J: the staged zip expires (artifact retention is in days), so a rollback that is older than the retention fails. The workflow only reports a clear error.

### Publish

56. good: B: publish = build, sign (KMS), verify, then write-once upload with a completion marker. No deploy in the same workflow. The workflow comment states the contract in an external doc.
57. bad: B: the tag name becomes an S3 key segment. The workflow validates it by a case statement that is 15 lines of shell with comments of 10 lines each.
58. good: G: Lambda `publish-version` with the commit SHA as the description. The version is a record of what ran.
59. bad: none of the repos publishes an npm package, a container image or a GitHub Release. The skill has no real fixture for a registry publish. Use a synthetic one.

### Protection

60. good: B, G, H, F, D, E: tag rulesets (creation gate, immutability) exist for `v*` and the bundle tag pattern. A release tag cannot be moved or deleted.
61. good: F, D, E, C, B, G, H: the main branch has a ruleset that requires a PR. F has a second ruleset for "merge commit only" on the release PR.
62. bad: F, D, C, E: the environments list only a deployment branch policy. The API listed no required-reviewer rule on any environment of repos F, D, C and E (3 + 3 + 4 + 1 environments). The approval is the PR, as the comments say. Environments exist to scope variables and the OIDC subject, not to gate.
63. bad: B: the workflow comment says the environment has required reviewers, but the API listed only a branch policy for it. The doc and the setting can disagree, and nothing in the repo checks it.
64. good: C: a weekly scheduled audit compares the repo settings with an expected file, finds bypassed rulesets on the main branch and finds commits that have no approved PR. It runs in an environment that accepts only the main branch, so a dispatch on another branch cannot use the App token.
65. bad: G, H, I, J, K: the prod and staging deploy jobs use no GitHub environment (only the tag job does). The control is the role trust policy on the tag ref and the tag rulesets. They live outside the workflow, so a reviewer cannot see them in the file.
66. good: G: the `promote` environment accepts only the main branch and holds the App key. The key reaches one step.

## 4. Triggers, permissions, environments, secrets

Triggers (counts are CD files):

| Trigger | Count | Use |
|---|---|---|
| push to a branch (develop, main) | many (about a third of the files) | deploy dev, deploy staging, merge flow |
| push of a version tag (`v*`, final only, `!v*-*`) | one per Lambda app repo and per frontend | prod deploy |
| push of a version tag for staging | 2 repos (D, F) | staging deploy |
| push of a bundle tag | 1 | publish |
| workflow_dispatch (inputs: candidate, tenants, target, mode) | promote and rollback of each app repo, plus 3 manual test files | promote, rollback, redeploy, tests |
| workflow_call | the 7 template files of G, plus the apply stage of C | reusable flows |
| schedule (weekly cron) | 1 | settings audit |
| pull_request in a CD file | the dev deploy of the app repos | dry run of the deploy |

The counts in this table are approximate. The patterns in section 3 are exact.

Permissions: `permissions: {}` or `contents: read` at the top in all 38 files. `id-token: write` only on deploy jobs. `pull-requests: write` only in the release job that opens the back-merge PR. `actions: read` and `pull-requests: read` in the prod job that looks up the staging run.

Environments: dev, staging, prod (repos D, F); org, nonprod, prod, audit (repo C); prod (repo E); one for tag creation (repo H) and one for publish (repo B). All have a custom branch policy; none shows a reviewer rule. Repo G has no environment at all.

Secret and variable KINDS:
- Secrets: a GitHub App id and a GitHub App private key (for tag creation and for reading org settings). The key is empty in the caller and supplied by the environment. No PAT, no AWS key, no npm token, no registry token in any CD workflow.
- Org or repo variables: AWS account ids, role ARNs, S3 bucket names, CDN domains, KMS key ids, the list of deploy targets (a JSON string or a comma list), a flag for staging onboarded, a budget policy id.
- Context: `GITHUB_TOKEN` (short-lived) for read calls; the App token for writes of tags.

## 5. Synthetic eval fixture candidates

Build each fixture from scratch. Copy no file.

1. `fx-cd-no-timeout`: a deploy workflow with `id-token: write` and no `timeout-minutes` on any job. Expected: cost (15).
2. `fx-cd-no-concurrency`: a deploy on push with no `concurrency` group, or with `cancel-in-progress: true`. Expected: cost (18); the good form is a group per environment with no cancel (17).
3. `fx-cd-rebuild-per-env`: three jobs (dev, staging, prod) that each run install and build. Expected: job graph, build once and promote the artifact (8, 9).
4. `fx-cd-prod-from-push`: prod deploys on push to the main branch with no environment approval and no gate on the staging run. Expected: protection and deploy (43, 62).
5. `fx-cd-role-in-yaml`: a role ARN with an account id typed in the workflow, and the role is assumed before install and build. Expected: security (23, 26).
6. `fx-cd-tag-unpinned`: a reusable workflow referenced by a branch or by a mutable tag. Expected: security (27).
7. `fx-cd-rollback-by-input`: a rollback that takes a free text version input and rebuilds. Expected: rollback, the version should come from the ref and no rebuild (50, 51).
8. `fx-cd-silent-skip`: a deploy job with an `if:` on empty variables that skips with no notice. Expected: deploy (39).
9. `fx-cd-publish-no-guard`: a publish on tag push with no check that the tag is on the main branch and no write-once check. Expected: publish and security (24, 56).
10. `fx-cd-good-reference`: a three-environment flow with build once, matrix deploy with `fail-fast: false`, a gate job with `!cancelled()`, a record artifact and a hash check in prod. Expected: no finding (6, 8, 34).

Gaps: no real npm publish, container image, GitHub Release or ECS/CDK/SAM workflow exists in the samples. The AWS targets that the samples cover are Lambda, S3 with a CDN, Terraform and a signed S3 bundle.
