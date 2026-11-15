# Research: production practices for continuous delivery (CD) on GitHub Actions and AWS

Researched 2026-11-15. Facts and documented practice only. Each claim has a source tag in brackets, and the URLs are in the Sources list at the end. Anything not verified is marked "unverified". Secondary sources are marked "secondary". This file builds on cd-practices.md (mechanics) and cd-sample-patterns.md (anonymous patterns from real repos). It does not repeat them. It refers to them as "see cd-practices.md, section N" and "see cd-sample-patterns.md, section N". It also builds on research 335 (CI practices).

Versions and states seen today:

| Item | What I saw |
|---|---|
| SLSA (Supply-chain Levels for Software Artifacts) spec | v1.2 is "Approved" and current. v1.1 is marked "Retired". v1.2 adds a Source track. [S28, S30] |
| `actions/attest` and `actions/attest-build-provenance` | v4.2.2 (see cd-practices.md, versions table). `attest-build-provenance` v4 is "simply a wrapper on top of `actions/attest`". [S24] |
| `gh attestation verify` | Default predicate type is `https://slsa.dev/provenance/v1`. [S27] |
| GitHub REST API version in the artifact metadata reference | 2026-03-10 (from a search summary; unverified). [S22] |
| AWS Systems Manager Change Manager | Closed to new customers from 2025-11-07. Change Calendar is still documented. [S33] |
| github/awesome-copilot | Default branch head `8ecd5b17f02fe5fbebf35eccd1867265eded811f`. [S51, S52] |
| wshobson/agents | 42,558 stars, last push 2026-11-09. [S53] |
| vercel/next.js `build_and_deploy.yml` | Default branch on 2026-11-15. Uses `actions/upload-artifact` v7.0.1 and `actions/checkout` v6.0.2. [S49] |
| cli/cli `deployment.yml` | Default branch on 2026-11-15. Uses `actions/attest` v4.2.2, `actions/checkout` v7.0.1, `actions/download-artifact` v8.0.2. [S50] |

Page text came through the WebFetch tool, which returns model-made summaries. Quotes below are from those summaries unless I say that I read the raw file (the workflow and skill files in section 8 were read raw with `gh api` GETs).

## Summary: the 10 most important findings

1. AWS says one thing and Lambda docs say another about canary. The AWS deployment strategies whitepaper calls canary "a type of blue/green deployment strategy". The Lambda docs say "Canary deployments differ from blue/green deployments by exposing the new version to only a portion of requests rather than switching all traffic at once." [S3, S7]
2. Each AWS target has its own native progressive tool. Lambda: a weighted alias (at most two published versions) or CodeDeploy with predefined canary and linear configurations. ECS: rolling update, CodeDeploy blue/green, or native ECS blue/green with bake time. S3 with CloudFront: a staging distribution with a continuous deployment policy. Terraform: "does not automatically roll back a partially-completed apply". [S4, S5, S6, S7, S9, S41]
3. Immutable versions are the base of rollback. A published Lambda version is an immutable snapshot, and version numbers are never reused. SemVer (Semantic Versioning) says a released version "MUST NOT be modified". Google release engineering labels (`dev`, `canary`, `production`) point at versioned, signed packages. [S8, S31, S46]
4. GitHub keeps a deployment record per job that uses an environment (unless `deployment: false`). Deployment status states are `error`, `failure`, `inactive`, `in_progress`, `queued`, `pending`, `success`. A separate artifact metadata API takes deployment records per artifact digest, environment, cluster and deployment name. [S18, S20, S21, S22]
5. Attestations alone give SLSA Build Level 2 (L2). Level 3 (L3) needs the build in a reusable workflow. GitHub says attestations give "no benefit unless they are verified" and are "not a guarantee that an artifact is secure". GitHub's own enforcement page covers Kubernetes admission only, not pre-deploy checks on AWS targets. [S23, S26]
6. AWS Well-Architected (WA) practice is automation with defined rollback criteria. It lists these anti-patterns: manual emergency workflows that skip steps, and "rapid follow-on deployments without allowing for bake time". [S16, S17]
7. Amazon's published pipeline numbers: a one-box stage serves "at most ten percent" of requests, at least one hour of bake time after each one-box stage, two to four hours after later regional waves, and "at most 33 percent" of boxes replaced at once. The pipeline is blocked while an alarm is in the alarm state. [S39]
8. Sources conflict on release flow. Google SRE (Site Reliability Engineering) cuts release branches from mainline and cherry-picks fixes onto them. DORA (DevOps Research and Assessment) data links high performance to "three or fewer active branches", daily merges, and no code freezes, and says release branches are not needed at multiple releases a day. [S31, S36]
9. Sources conflict on deploy windows. Amazon avoids "Fridays and late-afternoon deployments". AWS Change Calendar blocks changes in defined ranges. DORA treats code freezes as a symptom of long-lived branches and lists "nobody has to work outside business hours to deploy" as a goal. [S33, S35, S36, S39]
10. Rollback safety is a design property, not only a pipeline step. Amazon splits a data-format change into two deployments (read the new format first, write it later) and tests rollback explicitly. Expand, migrate, contract (parallel change) does the same for interfaces and schemas. [S13, S38]

---

## 1. Deployment strategies

Definitions from first-party and secondary sources. The AWS whitepaper says each AWS deployment service supports a number of general-purpose strategies [S1].

- Rolling: "slowly replaces previous versions of an application with new versions ... by completely replacing the infrastructure". It is "generally faster than a blue/green deployment". There is "no environment isolation between the old and new application versions", which "increases risks and complicates the process of rollback". [S2]
- Blue/green: two near-identical production environments. One is live. The other gets the next release. When it passes tests, "the router" sends all traffic to it. "If anything goes wrong you switch the router back to your blue environment." (secondary: Martin Fowler reports practice). [S10]
- Canary: send a new version to a small group first, then expand; "rerouted back to the old version" on problems. The trade-off: "multiple software versions must be run and managed at the same time, and database changes must support both" (secondary). [S11]
- AWS whitepaper on canary: traffic shifts "in two increments"; the first is "the canary group". It can continue "in two steps or linearly". [S3]
- Feature flags decouple release from deployment: the article "advocates separating [feature] release from [code] deployment". Fowler's toggle categories: release, experiment, ops, permissioning. He treats toggles "as inventory which comes with a carrying cost" and suggests a removal task in the backlog, expiry dates, and a cap on active flags (secondary). [S12]
- WA OPS06-BP04 (a best practice in the Operational Excellence pillar) lists four kinds of production testing: A/B testing, canary testing, feature-flag testing, and regression testing. [S16]
- Google SRE: canarying is "a partial and time-limited deployment of a change in a service and its evaluation". The canary gets the change and the rest of the service is the control. [S32]

What each in-scope AWS target offers (documented mechanisms only):

| Target | Documented mechanisms |
|---|---|
| Lambda | Versions are immutable snapshots after publish. [S8] An alias is "a pointer to a function version that you can update". A weighted alias points to at most two versions. Both must be published, and share the execution role and dead-letter queue setup. [S7] CodeDeploy predefined configurations: `CodeDeployDefault.LambdaCanary10Percent5Minutes` (also 10, 15 and 30 minutes), `LambdaLinear10PercentEvery1Minute` (also 2, 3 and 10 minutes), and `LambdaAllAtOnce`. [S4] AWS SAM (Serverless Application Model) wires this with `AutoPublishAlias` and `DeploymentPreference`. [S7] |
| ECS (Elastic Container Service) | Rolling update (the ECS controller; see cd-practices.md, section 5 for the circuit breaker). CodeDeploy blue/green with canary, linear or all-at-once. Predefined: `ECSCanary10Percent5Minutes`, `ECSCanary10Percent15Minutes`, `ECSLinear10PercentEvery1Minutes`, `ECSLinear10PercentEvery3Minutes`, `ECSAllAtOnce`. With a Network Load Balancer only `ECSAllAtOnce` works. [S4, S5] Native ECS blue/green: bake time (minutes that blue and green run together before blue ends), six lifecycle stages, Lambda or pause hooks, alarm-based rollback. [S6] |
| S3 and CDN (content delivery network) | CloudFront continuous deployment: a staging distribution plus a continuous deployment policy sends "some traffic from real (production) viewers to the new CDN configuration"; you then "promote" it to the primary distribution. [S9] For versioned file names instead of invalidation, see cd-practices.md, section 5. |
| CloudFormation or CDK (Cloud Development Kit) | The whitepaper points to CloudFormation update policies for rolling updates. [S2] CodeDeploy can run ECS blue/green through CloudFormation, but "you cannot create your own custom canary or linear deployment configuration" there. [S4] Rollback and alarm triggers: see cd-practices.md, section 5. |
| Terraform | "Terraform does not automatically roll back a partially-completed apply." A saved plan file runs "without a confirmation prompt". [S41] I found no first-party Terraform page on canary or blue/green strategy (unverified; see open items). |

Conflicts and notes:

- Canary versus blue/green. AWS whitepaper: canary is "a type of blue/green deployment strategy that is more risk-averse". Lambda docs: canary "differs from blue/green deployments by exposing the new version to only a portion of requests". [S3, S7]
- ECS tooling moves. The CodeDeploy-for-ECS page opens with "We recommend that you use the Amazon ECS blue/green deployment". The CodeDeploy configuration page still documents the ECS canary and linear configurations. [S4, S5]
- Lambda weighted alias: "Lambda uses a simple probabilistic model". "At low traffic levels, you might see a high variance between the configured and actual percentage". The invoked version shows in the `START` log line and in the `x-amz-executed-version` response header (synchronous calls). [S7]
- Lambda alias update with `function-version` and an empty `AdditionalVersionWeights` "also resets the routing configuration". [S7]
- Fowler on blue/green and databases: schema changes are "the hardest part"; use a refactoring that "support[s] both the new and old version of the application". [S10]

## 2. Artifact promotion and the record of what ran where

What the sources say:

- AWS WA REL08-BP05: set up "a continuous integration service to compile your source code, run tests, and create deployment artifacts", then a deployment service. It also says to "automate the most difficult procedures". [S17]
- Google SRE principle "hermetic builds": builds are "insensitive to the libraries and other software installed on the build machine". Binaries report build date, revision and build identifier. Packages are "named, versioned with a unique hash, and signed". Labels (`dev`, `canary`, `production`) mark the stage, and moving a label updates installers. [S31]
- Immutability facts: Lambda versions and numbers (above) [S8]; SemVer "MUST NOT be modified" [S46]; GitHub artifacts uploaded with `upload-artifact` v4 and later are immutable (see cd-practices.md, section 5).
- I found no AWS or GitHub first-party page that names "build once, promote the same artifact" as a rule. Prior art that states it: the github/awesome-copilot instructions say to use artifacts "to pass compiled binaries or packaged applications from a build job to a deployment job, ensuring the exact same artifact is deployed that was built and tested" (secondary). [S51]
- Prior art in a workflow: Next.js builds once, persists tarballs with `upload-artifact`, then a gated `publishRelease` job runs with `environment:` set to a computed name. [S49] cli/cli builds per platform, then a `release` job downloads the merged artifacts and runs under the chosen environment. [S50]

GitHub records:

- A job that references an environment "creates a deployment object" by default. `deployment: false` skips that, which "keeps the deployment history clean but disables custom protection rules". [S18]
- Deployments REST API, create: `ref` is "the branch, tag, or SHA to deploy". `environment` defaults to `production`. `auto_merge` is on by default and merges the default branch into the ref when it is behind ("we will attempt to merge it for you"); success returns 202 and conflicts return 409. `required_contexts` unset checks all unique status contexts; an empty array skips the checks. `transient_environment` and `production_environment` are flags. [S19]
- Deployment statuses: `error`, `failure`, `inactive`, `in_progress`, `queued`, `pending`, `success`. `auto_inactive` (default true) marks earlier successful deployments inactive for non-transient, non-production environments with the same name. `log_url` and `environment_url` are optional. The `deployment_status` webhook event carries them. [S20]
- Linked artifacts page: storage records (repository, registry, attestations) and deployment records (environment, runtime risks such as "internet exposed"). It holds metadata, not files. Plan availability: not stated on the page (unverified). [S21]
- Artifact metadata REST API: a search summary says `POST /orgs/{org}/artifacts/metadata/deployment-record` takes artifact name and digest, environment stage, cluster and deployment name, and that "multiple requests for the same combination ... will only create one record". It says to call it "whenever an artifact is deployed to a new staging or production environment". I did not open that reference page (unverified). [S22]
- Storage records come from `actions/attest` when `push-to-registry` is true and the job has `artifact-metadata: write`. [S25]

## 3. Supply chain

SLSA Build track (v1.1 text; v1.2 is current and adds a Source track) [S28, S29, S30]:

- Build L0: no guarantees.
- Build L1: "Provenance exists." It "can be used to prevent mistakes but is trivial to bypass or forge."
- Build L2: hosted build platform that generates and signs provenance. Forging it "requires an explicit 'attack'".
- Build L3: hardened builds. Signing secrets must not be reachable from user build steps: "Such secret material MUST NOT be accessible to the environment running the user-defined build steps." Builds are isolated: "It MUST NOT be possible for one build to persist or influence the build environment of a subsequent build." L3 is "intended for most software releases".
- Spec note: SLSA v1.2 Source track level 2 focuses on history and provenance, and level 3 on "continuous enforcement of technical controls". [S30]

GitHub artifact attestations:

- Content: signed claims "that record where and how your software was built", possibly with workflow, repository, environment, commit SHA, triggering event, and an SBOM (software bill of materials). [S23]
- Levels: "Attestations alone provide SLSA v1.0 Build Level 2. To reach Build Level 3, run builds in a reusable workflow that many repositories share." [S23]
- Availability: public repositories on all current plans; private or internal repositories need GitHub Enterprise Cloud. Public repos use the Sigstore public good instance with a public transparency log. Private repos use GitHub's Sigstore instance with no transparency log. [S23, S24]
- Permissions: `id-token: write`, `contents: read`, `attestations: write`; add `packages: write` for container images and `artifact-metadata: write` for storage records. [S25]
- Verify: `gh attestation verify` needs `--owner` or `--repo`. Reusable workflows need `--signer-workflow` or `--signer-repo`. Other flags: `--cert-identity` (exact match of the certificate SubjectAlternativeName), `--source-ref`, `--deny-self-hosted-runners`, `--bundle` (offline; names are compared "only against names recorded in the certificate at creation time, so later renames go undetected"), `--predicate-type`. [S27]
- Container images use `oci://` references. SBOMs use `--predicate-type`. [S25]
- Limits, quoted: "Generating attestations provides no benefit unless they are verified"; attestations are "*not* a guarantee that an artifact is secure"; you "must define your own policy criteria". GitHub advises to "sign releases and binaries that people will run or download" and not "frequent test builds or individual files like source code". [S23]
- Enforcement: the documented path is the Sigstore Policy Controller on Kubernetes (admission). The page "covers cluster admission only, not pre-deploy checks". [S26] I found no first-party page that shows a pre-deploy verify step for Lambda, S3 or CloudFormation targets (unverified; see open items).
- Prior art: cli/cli attests release artifacts only when `environment == 'production'` and not a dry run, with `create-storage-record: false`. [S50] The awesome-copilot instructions say "Enforce that only signed images can be deployed to production environments" (secondary). [S51]
- For npm provenance and trusted publishing, see cd-practices.md, section 3. For immutable GitHub releases, see cd-practices.md, section 5.

## 4. Gates and verification

Automated gates and rollback:

- WA OPS06-BP04: "The rollback should be initiated automatically on pre-defined conditions such as when the desired outcome of your change is not achieved or when the automated test fails." Anti-patterns include one pipeline that delivers independent application, infrastructure and configuration changes together, and running regression tests without monitoring workload health. [S16]
- WA REL08-BP05 anti-patterns: manual changes; skipping steps "through manual emergency workflows"; following "accelerated timelines" instead of plans; "rapid follow-on deployments without allowing for bake time". [S17]
- Amazon pipeline: gamma stage mirrors production; one-box stage at most ten percent of requests; bake at least one hour after one-box stages and two to four hours after other regional waves; at most 33 percent of boxes at once; "at least 12 hours" after the first regional wave; "If the alarm is currently in the alarm state, the pipeline prevents the change from moving forward." Deployments are "completely hands-off". [S39]
- Google SRE canary advice: start with SLIs (service level indicators) such as request failures and latency; keep about a dozen metrics at most; break metrics down by canary and control; pair relative comparisons with absolute SLO (service level objective) checks; automatically pause or roll back when canary error rate diverges from control. [S32]

Smoke tests, health checks and version checks:

- CodeDeploy hooks. Lambda: `BeforeAllowTraffic`, `AfterAllowTraffic`. ECS: `BeforeInstall` (no rollback possible at that point), `AfterInstall`, `AfterAllowTestTraffic`, `BeforeAllowTraffic`, `AfterAllowTraffic` (each result can trigger rollback). The hook function reports `Succeeded` or `Failed`; "The deployment is considered to have failed if CodeDeploy is not notified ... within one hour." [S43]
- Native ECS blue/green: test traffic reaches the green revision first; optional header rules route chosen requests (for example `X-Test-Version`) to green; lifecycle hooks run Lambda functions or pause. [S6]
- Health checks (Amazon Builders' Library, written by AWS): liveness is the shallowest; dependency checks are the deepest. Deep checks "can produce false positives" and can turn "a soft dependency into a hard one". Without a dependency check "a deployment system may not notice bad code" and "marches along breaking one server after another"; Amazon teams add fleet-size and error-rate alarms that halt rollouts. [S40]
- Version checks: I found no first-party page that names "check the version, not only the status code" as a practice (unverified). Documented mechanisms: the Lambda `x-amz-executed-version` header and `START` log entry [S7]; SRE binaries that report revision and build identifier [S31].

Change freezes and deploy windows (sources differ; both quoted):

- AWS Systems Manager Change Calendar: date ranges when actions "might or might not be performed". `DEFAULT_OPEN` calendars are closed during events; `DEFAULT_CLOSED` calendars are open only during events. `GetCalendarState` returns the current state (quota 10 requests per second). Example uses: high demand, "vacations or holidays". [S33]
- Amazon: "Oncall engineers typically take longer to engage at night, on office holidays, and on weekends." Many teams exclude "Fridays and late-afternoon deployments". [S39]
- DORA: code freezes are "a symptom of long-lived branches". A goal of continuous delivery is that nobody "has to work outside business hours to deploy". [S35, S36]
- Whether GitHub Actions has a native freeze feature: not verified here (see cd-practices.md, section 1 for custom deployment protection rules).

Approvals and separation of duties:

- GitHub required reviewers and "Prevent self-review": see cd-practices.md, section 1.
- Amazon: changes "must be approved by a team member before merging into the mainline branch"; the article gives no reviewer count. [S39]
- Google SRE principle "enforcement of policies and procedures": layered access controls gate approving changes, creating releases and deploying. [S31]
- awesome-copilot instructions: manual approvals for production "often involving multiple team members, security sign-offs, or change management processes" (secondary prior art, not a first-party source). [S51]

## 5. Release flow design

Trunk versus release branches (sources differ):

- DORA: trunk-based development means merging small changes "at least once (and potentially several times) a day". Higher performance is linked with "three or fewer active branches", daily merges to trunk, and no code freezes. Changes on a release branch are "merged back to trunk as soon as possible". "When releases happen multiple times a day, release branches aren't needed." [S36]
- Google SRE: "Releases come from a branch cut from the mainline at a specific revision." Fixes go to mainline first and are then cherry-picked. Because cherry-picks "can create code that exists nowhere on the mainline", release branches are retested. [S31]
- trunkbaseddevelopment.com (secondary): very high cadence teams "do not need (and cannot use) release branches". Teams releasing daily or less may branch, cherry-pick and release from the branch. Bugs "roll forward on trunk". It can create a release branch retroactively. [S37]

Tag-driven promotion, release candidates and channels (prior art, read raw):

- Next.js: `build_and_deploy.yml` runs on pushes to `canary` and `releases/**`, and on tags. A release commit pushed to a branch is skipped ("Publishing is driven by the tag push for that same commit"). The tag name picks the GitHub environment: `*-canary.*` to `release-canary`, `*-beta.*` to `release-beta`, `*-rc.*` to `release-release-candidate`, `*-preview.*` to `release-preview`, no suffix to `release-stable`. A tag with no matching channel fails with an error. Pre-release channels get a draft GitHub release that an `undraftRelease` job publishes after the gated publish. [S49]
- cli/cli: `deployment.yml` runs only on `workflow_dispatch`. Inputs: `tag_name` (for example `v2.100.0` or `v2.100.0-rc.1`), `environment` (input type `environment`, default `production`), `platforms`, `release`, and `dry_run` (default `true`). The run name shows tag, environment and "(dry run)". [S50]
- SemVer: a pre-release such as `1.0.0-rc.1` ranks below `1.0.0`; build metadata is ignored in precedence. [S46]
- For tag-triggered workflows and their security, see cd-practices.md, section 9. For Changesets, release-please and semantic-release, see cd-practices.md, section 4.

Changelogs and release notes:

- GitHub generated release notes list merged pull requests, contributors and a full-changelog link. `.github/release.yml` sets categories (by label) and exclusions (by label or author). The page describes the web interface; the API route is not covered there (unverified). [S48]
- Keep a Changelog (secondary convention): write for people, one entry per version, change types Added, Changed, Deprecated, Removed, Fixed, Security, and an Unreleased section. Commit logs are "full of noise". [S47]

## 6. Rollback and roll-forward

Rollback:

- WA OPS05-BP09: "Frequent, small, and reversible changes reduce the scope and impact of a change." Anti-pattern: "manual in-place updates ... and have no clear roll-back plan". Risk if absent: Low. [S15]
- Amazon explains the main cause of unsafe rollback: a change in protocol or data format that the old version cannot read. Fix: two deployments. "Prepare" deploys a version that reads the new format but writes the old one. After every server has it and a "bake period" of several days, "Activate" writes the new format. The article warns you "can't safely roll back both phases" and that old data must be backfilled before old-format reading is removed. Test: "Explicitly testing for rollback safety eliminates the need to rely on manual analysis." The test deploys to about half the fleet, completes the deployment, and rolls back until every server runs the old software; it passes only with no errors at any stage. [S38]
- AWS native rollback paths (CodeDeploy, ECS circuit breaker, Lambda alias, CloudFormation, CDK): see cd-practices.md, section 5.
- Terraform: no automatic rollback of a partly finished apply; after you fix the error "you must apply the configuration again". In the HashiCorp GitHub Actions tutorial, PR review and merge are the checkpoint, and the article does not say that apply uses the exact reviewed plan. It does not discuss concurrency or state locking. [S41, S42]

Roll-forward:

- trunkbaseddevelopment.com (secondary): at high cadence, bugs are rolled forward on trunk "as if it were a feature", as quickly as possible. [S37]
- DORA tracks "failed deployment recovery time" and "deployment rework rate" (unplanned deployments caused by incidents). It does not say when to prefer rollback over roll-forward. [S34]
- I found no first-party page that decides between rollback and roll-forward (unverified; see open items).

Artifact retention for rollback:

- Lambda: version numbers are never reused, "even after you delete and recreate a function". [S8]
- ECR (Elastic Container Registry) lifecycle policies expire images "within 24 hours after they meet the expiration criteria". Count types: `imageCountMoreThan`, `sinceImagePushed`, `sinceImagePulled`, `sinceImageTransitioned`. "Use the lifecycle policy preview" before applying. [S45]
- awesome-copilot: "store previous successful build artifacts and images for quick recovery" (secondary). [S51]
- GitHub artifact retention (1 to 90 days): see cd-practices.md, section 5.

Database migrations and expand/contract:

- Parallel change (also "expand and contract") has three phases: expand (add new beside old), migrate (move clients, "often the longest phase"), contract (remove old). Each phase "can be released on its own". Downside: the supplier supports two versions during migration (secondary). [S13]
- Fowler on blue/green: deploy the schema change first, confirm, then deploy the app, then remove old-version support once stable (secondary). [S10]
- wshobson `deployment-pipeline-design` skill: "Always make migrations backward-compatible (additive only) for at least one release"; never run destructive migrations such as `DROP COLUMN` until old code is retired in all environments (secondary prior art). [S53]

IaC rollback: CloudFormation and CDK behaviour is in cd-practices.md, section 5. Terraform is above. Other tools: not covered.

## 7. Operating CD

DORA metrics [S34]:

- Throughput: change lead time (commit in version control to production), deployment frequency, failed deployment recovery time.
- Instability: change fail rate (deployments needing "immediate intervention, often a rollback or a hotfix"), deployment rework rate (unplanned deployments caused by a production incident).
- DORA advice: apply the metrics to one application or service at a time. Do not set them as targets, because that invites gaming. The page gives no performance cluster thresholds. Top performers do well on all five; speed and stability are "generally correlated".
- The CD capability page lists these outcomes: short lead times "for both regular and emergency changes", low change fail rates, short time to restore, and timely high-priority fixes. [S35]
- Data sources inside GitHub for these metrics (deployment records, statuses): [S19, S20, S22]. Whether any first-party tool computes DORA metrics from them: not verified.

Concurrency and queues:

- GitHub concurrency and environments are separate features: see cd-practices.md, section 1 (including the conflicting "one pending" statements).
- Prior art, read raw. cli/cli: `group: ${{ github.workflow }}-${{ github.ref_name }}` with `cancel-in-progress: true`. [S50] Next.js: pull request runs share a group per branch; push runs include the SHA in the group so "the branch push and tag push of the same release commit ... don't share a group -- otherwise the skipped branch run could cancel the production tag run". It also sets `cancel-in-progress: true`. [S49]

Notifications:

- GitHub: the `deployment_status` webhook event; the deployments page names Slack and Microsoft Teams integrations. [S18, S20]
- CodeDeploy: SNS (Simple Notification Service) triggers per deployment group, up to 10, for events Success, Failure, Started, Stopped, Rollback and Ready (blue/green only). The JSON can feed SQS (Simple Queue Service) or Lambda. [S44]
- Amazon: pipeline blocking on alarms and automatic rollback replace human watching ("completely hands-off"). [S39]

## 8. Prior art

Published guidance (first-party and well-known):

- AWS Well-Architected, Operational Excellence: OPS05-BP02 to BP10 list version control, testing, build and deployment systems, multiple environments, "frequent, small, reversible changes" and full automation; OPS06-BP04 covers automated testing and rollback. [S14, S15, S16]
- AWS Well-Architected, Reliability: REL08-BP05 "Deploy changes with automation". Desired outcome: "automatic rollbacks, and staggered production deployments". Risk if absent: Medium. [S17]
- Amazon Builders' Library: safe hands-off deployments, rollback safety, health checks. [S38, S39, S40]
- Google SRE: release engineering (four principles: self-service, high velocity, hermetic builds, enforcement of policies and procedures) and canarying releases. [S31, S32]
- DORA: metrics, continuous delivery capability, trunk-based development. [S34, S35, S36]
- SLSA and GitHub attestation docs. [S23 to S30]
- GitHub "well-architected" and GitHub "recommended practices" pages: not read (unverified).

Open-source workflows read raw (read-only `gh api` GETs):

- vercel/next.js `.github/workflows/build_and_deploy.yml`: computes a deploy target (`production`, `staging`, `force-preview`, `automated-preview`, `skipped`); builds once; uploads artifacts; `publishRelease` uses `environment: ${{ needs.deploy-target.outputs.release_environment }}`; separate `bot-autonomous` environment for un-drafting the GitHub release; the file names environments per release channel. Also files for `create_release_branch`, `trigger_release`, `sync_backport_canary_release`, `test_e2e_deploy_release`. [S49]
- cli/cli `.github/workflows/deployment.yml`: manual dispatch with `dry_run` default true; `environment` input; code signing and GPG signing only in production; attestation only in production and not in dry run; `release` job gated by an input. It is the only release workflow file in that repo's `.github/workflows` that matched `deploy|release|publish`. [S50]
- aws/aws-cdk: the only workflow names matching deploy or release words are `integration-test-approval-deployment.yml` and `integration-test-deployment.yml`; I did not open them (unverified). [no tag]

Agent skills and rule packs for CD (as section 7 of research 335 did for CI):

1. github/awesome-copilot `instructions/github-actions-ci-cd-best-practices.instructions.md`. Sections "Advanced Deployment Strategies": staging, production, deployment types (rolling, blue/green, canary, dark launch, A/B), rollback and incident response; plus a review checklist. Generic and Kubernetes-flavoured (for example `maxSurge`, service mesh). It says to pin actions to full commit SHAs. [S51]
2. github/awesome-copilot `agents/devops-expert.agent.md`. Phases Plan to Monitor; mentions blue-green, canary, feature flags, rollback automation, DORA metrics, and "Rollback should be as easy as deployment". [S52]
3. wshobson/agents `plugins/cicd-automation/skills/deployment-pipeline-design/SKILL.md` (42,558 stars on the repo). Inputs: environment topology, rollout requirements, monitoring stack. Outputs: deployment strategy, health checks, gate definitions, rollback plan. Troubleshooting entries: health check passes but service unhealthy; Argo Rollouts canary never promotes; production job never starts when no reviewer is set; rollback with applied migrations. Platform YAML is in a `references/` file that I did not read. [S53]
4. Listings (secondary, repo contents not opened): `dmonteroh/curated-agent-skills` (deployment-engineer), `oakoss/agent-skills` (deployment-strategy), `aj-geddes/useful-ai-prompts` (deployment-automation), `affaan-m/everything-claude-code` (deployment-patterns). A code search for "canary" in `SKILL.md` files also listed `garrytan/gstack` and `wondelai/skills` (`release-it`); not opened. [S54]
5. Not found: a pack that checks workflow files for AWS-specific CD rules such as OIDC subject conditions, alias weights, or CodeDeploy hooks (I searched the listings above only; unverified).

## Unverified or open items

- Whether GitHub Actions has a native change freeze or deploy window feature (section 4).
- A first-party page that shows a pre-deploy attestation check for AWS targets (Lambda, S3, CloudFormation) (section 3).
- A first-party statement of "check the version, not only the status code" (section 4).
- A first-party rule for choosing rollback or roll-forward (section 6).
- The artifact metadata deployment-record endpoint: only a search summary was read (section 2). The GitHub plans that include the linked artifacts page are not stated on the page I read.
- CloudFront continuous deployment quotas and limits (the quotas page was not opened) (section 1).
- Terraform first-party guidance on progressive delivery; I found none in the pages I opened (section 1).
- ECR image tag immutability setting; not read (section 6).
- Whether the GitHub API can generate release notes in the way the docs page describes; that page covers the web interface only (section 5).
- DORA performance cluster thresholds: the metrics page gives none; I did not open the annual research report (section 7).
- GitHub well-architected and recommended practices pages: not read (section 8).
- `aws/aws-cdk` approval-deployment workflows and the listed agent-skill repos in item 4 of section 8: listing only.
- Amazon numbers (10 percent, 33 percent, bake times) come from one article by one author and describe Amazon's own pipeline, not a general rule (section 4).
- All page text came through WebFetch summaries, not raw page source, except the repository files in section 8.

## Sources

- [S1] AWS whitepaper, deployment strategies: https://docs.aws.amazon.com/whitepapers/latest/overview-deployment-options/deployment-strategies.html (landing text only was returned)
- [S2] AWS whitepaper, rolling deployments: https://docs.aws.amazon.com/whitepapers/latest/overview-deployment-options/rolling-deployments.html
- [S3] AWS whitepaper, canary deployments: https://docs.aws.amazon.com/whitepapers/latest/overview-deployment-options/canary-deployments.html
- [S4] CodeDeploy, deployment configurations: https://docs.aws.amazon.com/codedeploy/latest/userguide/deployment-configurations.html
- [S5] ECS, CodeDeploy blue/green deployment type: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-bluegreen.html
- [S6] ECS, creating an ECS blue/green deployment: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deploy-blue-green-service.html
- [S7] Lambda, weighted alias canary deployments: https://docs.aws.amazon.com/lambda/latest/dg/configuring-alias-routing.html
- [S8] Lambda, function versions: https://docs.aws.amazon.com/lambda/latest/dg/configuration-versions.html
- [S9] CloudFront continuous deployment: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/continuous-deployment.html
- [S10] Martin Fowler, BlueGreenDeployment (secondary): https://martinfowler.com/bliki/BlueGreenDeployment.html
- [S11] Martin Fowler, CanaryRelease (secondary): https://martinfowler.com/bliki/CanaryRelease.html
- [S12] Martin Fowler, Feature Toggles (secondary): https://martinfowler.com/articles/feature-toggles.html
- [S13] Martin Fowler, ParallelChange (secondary): https://martinfowler.com/bliki/ParallelChange.html
- [S14] AWS Well-Architected, Operational Excellence, design for operations: https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/design-for-operations.html
- [S15] AWS WA OPS05-BP09: https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/ops_dev_integ_freq_sm_rev_chg.html
- [S16] AWS WA OPS06-BP04: https://docs.aws.amazon.com/wellarchitected/latest/operational-excellence-pillar/ops_mit_deploy_risks_auto_testing_and_rollback.html
- [S17] AWS WA REL08-BP05: https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_tracking_change_management_automated_changemgmt.html
- [S18] GitHub Docs, deploying with GitHub Actions: https://docs.github.com/en/actions/deployment/about-deployments/deploying-with-github-actions
- [S19] GitHub REST API, deployments: https://docs.github.com/en/rest/deployments/deployments
- [S20] GitHub REST API, deployment statuses: https://docs.github.com/en/rest/deployments/statuses
- [S21] GitHub Docs, about linked artifacts: https://docs.github.com/en/code-security/concepts/supply-chain-security/linked-artifacts
- [S22] GitHub REST API, artifact metadata (search summary only): https://docs.github.com/en/rest/orgs/artifact-metadata
- [S23] GitHub Docs, artifact attestations concept: https://docs.github.com/en/actions/concepts/security/artifact-attestations
- [S24] actions/attest-build-provenance repository: https://github.com/actions/attest-build-provenance
- [S25] GitHub Docs, use artifact attestations: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- [S26] GitHub Docs, enforce artifact attestations: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/enforce-artifact-attestations
- [S27] GitHub CLI manual, `gh attestation verify`: https://cli.github.com/manual/gh_attestation_verify
- [S28] SLSA v1.1, levels: https://slsa.dev/spec/v1.1/levels
- [S29] SLSA v1.2, build requirements: https://slsa.dev/spec/v1.2/build-requirements
- [S30] SLSA v1.2, what's new: https://slsa.dev/spec/v1.2/whats-new
- [S31] Google SRE book, release engineering: https://sre.google/sre-book/release-engineering/
- [S32] Google SRE workbook, canarying releases: https://sre.google/workbook/canarying-releases/
- [S33] AWS Systems Manager Change Calendar: https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-change-calendar.html
- [S34] DORA, software delivery metrics: https://dora.dev/guides/dora-metrics/
- [S35] DORA, continuous delivery capability: https://dora.dev/capabilities/continuous-delivery/
- [S36] DORA, trunk-based development capability: https://dora.dev/capabilities/trunk-based-development/
- [S37] trunkbaseddevelopment.com, release from trunk (secondary): https://trunkbaseddevelopment.com/release-from-trunk/
- [S38] Amazon Builders' Library, ensuring rollback safety during deployments: https://builder.aws.com/content/3F04j2yRAAMBuPSPs50xwXZqg01/ensuring-rollback-safety-during-deployments
- [S39] Amazon Builders' Library, automating safe, hands-off deployments: https://builder.aws.com/content/3ErTKQOTKc5NIw031UePBPxTQ6I/automating-safe-hands-off-deployments
- [S40] Amazon Builders' Library, implementing health checks: https://builder.aws.com/content/3Ev53O39izHCtWLzp4XU6t8PC1O/implementing-health-checks
- [S41] Terraform CLI, apply command: https://developer.hashicorp.com/terraform/cli/commands/apply
- [S42] HashiCorp tutorial, Terraform with GitHub Actions: https://developer.hashicorp.com/terraform/tutorials/automation/github-actions
- [S43] CodeDeploy, AppSpec hooks section: https://docs.aws.amazon.com/codedeploy/latest/userguide/reference-appspec-file-structure-hooks.html
- [S44] CodeDeploy, SNS event notifications: https://docs.aws.amazon.com/codedeploy/latest/userguide/monitoring-sns-event-notifications.html
- [S45] Amazon ECR lifecycle policies: https://docs.aws.amazon.com/AmazonECR/latest/userguide/LifecyclePolicies.html
- [S46] Semantic Versioning 2.0.0: https://semver.org/
- [S47] Keep a Changelog 1.1.0 (secondary): https://keepachangelog.com/en/1.1.0/
- [S48] GitHub Docs, automatically generated release notes: https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes
- [S49] vercel/next.js build_and_deploy.yml (read raw): https://github.com/vercel/next.js/blob/canary/.github/workflows/build_and_deploy.yml
- [S50] cli/cli deployment.yml (read raw): https://github.com/cli/cli/blob/trunk/.github/workflows/deployment.yml
- [S51] github/awesome-copilot, CI/CD best practices instructions (read raw): https://github.com/github/awesome-copilot/blob/main/instructions/github-actions-ci-cd-best-practices.instructions.md
- [S52] github/awesome-copilot, devops-expert agent (read raw): https://github.com/github/awesome-copilot/blob/main/agents/devops-expert.agent.md
- [S53] wshobson/agents, deployment-pipeline-design skill (read raw): https://github.com/wshobson/agents/blob/main/plugins/cicd-automation/skills/deployment-pipeline-design/SKILL.md
- [S54] Web search listing of CD agent skills (secondary, repos not opened): https://skills.cat/skills/dmonteroh/curated-agent-skills/deployment-engineer
