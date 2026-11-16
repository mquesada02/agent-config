# Research: CD practices on GitHub Actions for Node/TypeScript repos deploying to AWS

Researched 2026-11-15. Facts only. Each claim has a source tag in brackets, and the URLs are in the Sources list at the end. Anything not verified is marked "unverified". This file builds on research 335 (CI practices). It does not repeat 335. It refers to it as "see 335, Sx".

Versions seen today (latest release tag, full commit SHA; annotated tags were dereferenced with `gh api repos/<owner>/<repo>/commits/<tag>`):

| Action or tool | Latest release | Full commit SHA |
|---|---|---|
| aws-actions/configure-aws-credentials | v6.3.0 (2026-09-15); floating `v6` tag points to the same commit | e1253824e5c10ff9df46874f81ed3ec929e19cfd |
| aws-actions/amazon-ecr-login | v2.1.7 | 03f1aad4c6c7ffd436567f42f9384779290529bd |
| aws-actions/amazon-ecs-render-task-definition | v1.9.1 | 8d79160660ad39c402a16e5fc7cd2a32e8f7d6b7 |
| aws-actions/amazon-ecs-deploy-task-definition | v2.6.4 | a00d4d57ac0de1a99b39fe469f3d898d38717c2b |
| aws-actions/amazon-ecs-deploy-express-service | v1.2.2 | 7c48a2de16441d528a3c89829831968dc1455010 |
| aws-actions/aws-lambda-deploy | v1.1.2 | d496277188b89f0be02d7a2216fc912c0427702a |
| aws-actions/aws-cloudformation-github-deploy | v2.2.0 | 81e3b03d2266bcb76c4bcc37a7d71d9cb67838bb |
| aws-actions/setup-sam | v3 (release tag is `v3`) | 341eee193f458fa5aae5d52c94b0c5cf3a1c5a52 |
| aws-actions/aws-codebuild-run-build | v1.0.19 | 7e46c3fa1c1f217e26a73712796b1f78938b534b |
| hashicorp/setup-terraform | v4.0.1 | dfe3c3f87815947d99a8997f908cb6525fc44e9e |
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| actions/setup-node | v7.1.0 | 949feb2413d6458794dcd2491c4babbbce0c15c1 |
| actions/upload-artifact | v7.0.2 | cf430e030ddbb5b0abf93d22962f4752f3646cd9 |
| actions/download-artifact | v8.0.2 | 9000827ccba6bdab643e8b6fd33ac0654aef8333 |
| actions/attest | v4.2.2 | 1e69f48acb82d1966a394da916b4c1698aa569d6 |
| actions/attest-build-provenance | v4.2.2 | 4d101475d8b20a2381f78447822ac1eab6504dd8 |
| changesets/action | v2.1.2 (2026-09-07; v2 pairs with Changesets v3) | ae32849d5ba541f9ae29e40e22a623bc13562f51 |
| googleapis/release-please-action | v5.0.0 (2026-04-22) | 45996ed1f6d02564a971a2fa1b5860e934307cf7 |
| pnpm/action-setup | v6.1.1 | 73e46992e05b19abd31f2f3c20e0e7370d762115 |
| ossf/scorecard-action | v2.5.0 | fa7117db83c52d787ae5a89f350999701505d78e |
| nektos/act | v0.2.97 | 2540ba6c49dfbafe167d655e4044921cd2ed19e7 |
| zizmorcore/zizmor | v1.32.0 | 21bd300700d43d9ba04b0c1fce72a89391ac80b4 |

Other versions seen: `@changesets/cli` 3.0.3, release-please (library) v17.11.2, semantic-release v25.0.9, npm CLI v12.2.2 (latest release), OpenSSF Scorecard v5.6.0. [S6, S12, S15, S17, S19, S52, S53, S56]

The `gh api` SHA lookups are read-only GETs and were run on 2026-11-15. `aws-actions/amazon-ecs-deploy-task-definition` was last pushed 2026-10-31; `amazon-ecs-deploy-express-service` and `aws-lambda-deploy` are not in research 335.

## Summary: the 10 most important findings

1. A job that uses `environment:` gets an OIDC `sub` of the form `repo:ORG/REPO:environment:NAME`. The branch or tag is then not in `sub`. Branch and tag sub forms (`...:ref:refs/heads/X`, `...:ref:refs/tags/X`) and the `pull_request` form apply only when the job has no environment. [S4]
2. Since 2026-07-15, new repositories (and renamed or transferred ones, and opted-in older ones) emit an immutable `sub` that includes owner and repository IDs: `repo:OWNER@OWNER-ID/REPO@REPO-ID:...`. A trust policy that has the old name-only form fails with `Not authorized to perform sts:AssumeRoleWithWebIdentity` for such repositories. [S4, S6]
3. `concurrency` and `environment` are not connected. A concurrency group can be any string. A workflow that uses the same environment without `concurrency` is not limited. Two GitHub docs statements about "one pending" conflict (see section 1). [S3]
4. Environment protection rules (required reviewers, wait timer, branch/tag policy, custom rules) hold a job back before it starts and before it can read environment secrets. Administrators can bypass them by default unless the bypass setting is off. On the Free, Pro and Team plans, required reviewers, wait timers and custom rules are available only in public repositories. A job that waits for approval fails after 30 days. [S2, S3]
5. npm trusted publishing needs npm CLI 11.5.1 or later, Node 22.14.0 or later, `id-token: write`, a GitHub-hosted runner and a trusted-publisher entry that matches the workflow file name exactly. npm does not check the entry when you save it. Provenance is automatic only for public packages from public repositories. [S9, S10]
6. Sources conflict on `registry-url` for publishing. npm docs and the setup-node docs set `registry-url: https://registry.npmjs.org`. The semantic-release GitHub Actions recipe says not to set `registry-url` because it can cause `EINVALIDNPMTOKEN`. [S9, S12, S19]
7. The three release tools split work differently. Changesets: a "Version Packages" pull request, then `changeset publish` (publishes unpublished versions, makes git tags). release-please: a release pull request from Conventional Commits, then tag and GitHub release on merge (publish is a separate step). semantic-release: no pull request; it tags, publishes and creates a GitHub release on each push. Only semantic-release has an open issue for multi-package support (issue 193). [S15-S23]
8. Rollback is "deploy an earlier thing again" in most AWS targets: CodeDeploy redeploys an old revision as a new deployment; the ECS circuit breaker rolls back to the last `COMPLETED` deployment (rolling-update controller only); a Lambda alias moves back with `update-alias`; CloudFormation rolls back automatically on failed updates unless disabled, and can roll back on CloudWatch alarms (max 5 alarms, 0 to 180 minutes). [S28-S33]
9. Protection write APIs differ in replace behaviour. Branch protection `PUT` needs `required_status_checks`, `enforce_admins`, `required_pull_request_reviews` and `restrictions` in the body (each may be `null`). Ruleset `enforcement` can be `disabled`, `active` or `evaluate`, but `evaluate` is only on GitHub Enterprise. No endpoint has a dry-run flag. [S46-S48]
10. `act` cannot do OIDC ("Openid Connect url is not defined"), ignores `job.environment`, `concurrency` and `job.permissions`, and has an incomplete `github` context. It does run service containers and has `--dryrun` (validates workflow only, no containers). Several AWS actions and tools have native previews: `aws-lambda-deploy` `dry-run`, CloudFormation action `no-execute-changeset` / `mode: create-only`, `terraform plan`, `cdk diff`, `aws s3 sync --dryrun`. [S37, S38, S41, S42, S45, S49, S50]

---

## 1. Environments and deployment protection

Protection rules [S1, S2]:

- Required reviewers: up to 6 users or teams. Reviewers need at least read access. One approval is enough. "Prevent self-review" stops the person who started the deployment from approving it. [S2]
- Wait timer: integer from 1 to 43,200 minutes (30 days). The wait does not count toward billable time. [S2]
- Deployment branches and tags: three options. "No restriction". "Protected branches only" (if no branch has a protection rule, all branches can deploy). "Selected branches and tags" (name patterns, added one by one per branch or tag). [S2]
  - The rule is matched against the `GITHUB_REF` of the run. `releases/*` allows `GITHUB_REF` names that start with `releases/`. Wildcards do not match `/`. Adding `refs/pull/*/merge` lets `pull_request` runs deploy. [S2]
  - Note in docs: runs triggered by tags with the same name as a protected branch, and forks with branches that match the protected branch name, cannot deploy under "Protected branches only". [S2]
- Allow administrators to bypass: on by default. Admins can force deployments. It can be turned off per environment. [S2]
- Custom deployment protection rules: built from GitHub Apps. They work through the `deployment_protection_rule` webhook. Any number of apps can be installed on a repository. At most 6 rules can be enabled on one environment. The feature carries a "beta" note in the source. [S2, S3]
- A job that references an environment does not start until all rules pass. It cannot read environment secrets before that. [S3]
- A job that waits for approval shows "Waiting". If not approved in 30 days, it fails. [S3]
- Plans: on GitHub Free, environments (and their secrets) work only for public repositories. Required reviewers, wait timers, the admin-bypass setting and custom rules are also available only in public repositories on Free, Pro and Team. Deployment branches and tags: public repositories, plus private repositories on Pro and Team. Environment variables: public repositories, plus private on Pro and Team. If a repository goes from public to private, configured protection rules and secrets are ignored. [S1, S2]
- Self-hosted runners: "not run in an isolated container, even if they use environments." Treat environment secrets like repository secrets. [S2]

Environment secrets and variables [S1, S2]:

- Environment secrets and variables are available only to jobs that reference the environment. Secrets are not readable until protection rules pass. Variables are read through the `vars` context. [S2]
- A workflow that references an environment that does not exist creates it, with no protection rules or secrets. Anyone who can edit workflows can create environments this way. Only repository admins can configure them. [S1]
- Deleting an environment deletes its secrets and rules. Jobs that wait because of its rules fail. [S1]
- Newer option `environment: { name: ..., deployment: false }` (default `true`): no deployment object is created. Wait timer and required reviewers still apply. A custom protection rule app makes the job fail immediately when `deployment: false` is set. [S3]

How `environment:` changes OIDC [S4, S5]:

- Subject form when the job references an environment: `repo:ORG-NAME/REPO-NAME:environment:ENVIRONMENT-NAME`. Colons in a name become `%3A` (example `Production%3AV1`). [S4]
- Branch form (`...:ref:refs/heads/BRANCH`) and tag form (`...:ref:refs/tags/TAG`) apply "only if the job doesn't reference an environment", and for branch and tag also only when the workflow is not triggered by a pull request. [S4]
- `pull_request` form (`repo:ORG/REPO:pull_request`) applies "only if the job doesn't reference an environment". [S4]
- The `environment` claim is also in the token. If `environment` is added to the `sub` template through `include_claim_keys`, an environment is required. [S4]
- GitHub's AWS page recommends adding protection rules when environments are used in OIDC policies, for example to limit which branches and tags can deploy. [S5]

How `environment:` relates to concurrency [S3]:

- Quote: "Note that `concurrency` and `environment` are not connected. The concurrency value can be any string; it does not need to be an environment name. Additionally, if another workflow uses the same environment but does not specify concurrency, that workflow will not be subject to any concurrency rules." [S3]
- Conflict inside one page. The intro (as rendered for github.com in the docs source) says concurrency gives "a maximum of one deployment in progress" and omits "and one deployment pending". The source has a version switch `actions-nga` for that phrase; the feature file says it is enabled for `fpt` and `ghec`. The example text just below still says "there will be a maximum of one running and one pending job or workflow". Which one is current for github.com: unverified. [S3, S3b]
- Group-level `concurrency: production` at workflow level is documented. A job-level `concurrency` lets other jobs in the workflow proceed while the job is pending. `cancel-in-progress: true` cancels the running run. [S3]
- For the general concurrency rules (case-insensitive groups, default replace-pending), see 335, S8.

REST: environments can be created and configured through the REST API (see section 7). [S1]

---

## 2. OIDC to AWS

Workflow side:

- `permissions: id-token: write` is required. "Without `id-token: write`, the OIDC JWT ID token cannot be requested." It does not grant write access to other resources. This settles the open item in 335 ("`id-token: write` wording"). [S4]
- `actions/checkout` also needs `contents: read` when `permissions` is set at workflow level. [S5]
- Reusable workflows from the same user, organization or enterprise: the token is available from the caller's context. Reusable workflows outside them: set `id-token` to `write` explicitly at the caller workflow or job. [S4]
- The step: `aws-actions/configure-aws-credentials` with `role-to-assume` and `aws-region`. README examples pin `@v6.3.0`. GitHub's AWS page example pins the full SHA `e3dd6a42...` (an older commit). [S5, S6]
- Inputs seen in `action.yml` (README table): `role-to-assume`, `aws-region`, `role-session-name` (default `GitHubActions`), `role-duration-seconds` (default 3600; 900 to 43200), `role-chaining`, `audience` (default `sts.amazonaws.com`), `allowed-account-ids`, `mask-aws-account-id`, `output-credentials`, `output-env-credentials`, `unset-current-credentials`, `inline-session-policy`, `managed-session-policies`, `role-skip-session-tagging`, `transitive-tag-keys`, `custom-tags`, `use-existing-credentials`, `force-skip-oidc`, `special-characters-workaround`, `sts-endpoint`, `translate-env-variables`, `action-timeout-s`, `retry-max-attempts` (default 12), `disable-retry`, `http-proxy`, `no-proxy`, `aws-profile`. [S6]
- `custom-tags`: "not usable with OIDC or web identity token authentication." [S6]
- The README says naming a role "GitHubActions" has been reported to not work (issue 953). [S6]
- The action versioning: from 5.0.0 on it uses immutable releases and a floating `vN` tag. [S6]

AWS side:

- Create an IAM OIDC identity provider: URL `https://token.actions.githubusercontent.com`, audience `sts.amazonaws.com` (when using the official action). [S5, S6]
- Thumbprints: AWS uses its trusted root CA library to verify the JWKS endpoint certificate and falls back to thumbprints only if the CA is not trusted, or TLS 1.3 blocks retrieval. The action README says a thumbprint, "if specified, will be ignored." [S6, S7]
- An IAM OIDC provider can have up to 5 thumbprints and up to 100 audiences. Each provider URL must be unique in the account. The OIDC provider used in a role trust policy must be in the same account as the role. [S7]
- Trust policy: action `sts:AssumeRoleWithWebIdentity`, principal `Federated` = the provider ARN, conditions on `token.actions.githubusercontent.com:aud` and `:sub`. [S5, S6]
- Quote from GitHub: "To control how your cloud provider issues access tokens, you **must** define at least one condition, so that untrusted repositories can't request access tokens for your cloud resources." [S4]
- Quote from the action README: "Without any condition, any GitHub user or repository could potentially assume the role." [S6]
- Quote from GitHub's AWS page: AWS IAM "recommends that users evaluate the IAM condition key `token.actions.githubusercontent.com:sub`". [S5]

`sub` forms for the trust policy (legacy name-only format) [S4, S5]:

| Case | `sub` value |
|---|---|
| Branch | `repo:ORG/REPO:ref:refs/heads/BRANCH` |
| Tag | `repo:ORG/REPO:ref:refs/tags/TAG` |
| Environment | `repo:ORG/REPO:environment:ENV` |
| Pull request | `repo:ORG/REPO:pull_request` |

- Immutable form for repositories created after 2026-07-15 (and others, see Summary 2): `repo:OWNER@OWNER-ID/REPO@REPO-ID:ref:refs/heads/BRANCH`. The `@` is used because it cannot appear in user or repository names. Older repositories keep the old format unless they opt in at organization or repository level (settings UI or REST API). [S4]
- Failure mode (action README): old-format policy plus immutable claim gives `Not authorized to perform sts:AssumeRoleWithWebIdentity`. [S6]
- Customised `sub` (REST API, `include_claim_keys`): for immutable repositories `owner_id` and `repo_id` stay in the `repo` segment and cannot be removed. Create the matching condition in AWS before changing the template. [S4]
- GitHub's AWS page example uses `StringLike` with `repo:octo-org/octo-repo:*` to allow any branch, pull request merge ref or environment of one repository. [S5]
- Action README warning: avoid `ForAllValues:` in `Allow` statements. These return true when the claim is absent or misspelled. Use `StringEquals` or `StringLike`. [S6]

Conflict on custom claims in AWS:

- GitHub: "Support for custom claims for OIDC is unavailable in AWS." [S5 reusable note]
- Action README (newer): "AWS IAM and GitHub have since added support for `sub` claim customization and a variety of additional claims", and links an AWS announcement from 2026-01 about STS validating identity-provider claims. I did not open that AWS page. Which page is current: unverified. [S6]

Role chaining:

- Action: second `configure-aws-credentials` step with `role-chaining: true`. The second role's trust policy must allow `sts:AssumeRole` and `sts:TagSession` for the first role. `TagSession` can be left out if the second step sets `role-skip-session-tagging: true`. [S6]
- Session tags are used by default except for OIDC or web identity token authentication. `transitive-tag-keys` forwards tags down a chain. All later roles in the chain must set `role-skip-session-tagging: true`. [S6]
- AWS: "Role chaining limits your AWS Management Console, AWS CLI or AWS API role session to a maximum of one hour." A `DurationSeconds` over one hour in a chained call fails. This applies "regardless of the maximum session duration configured for individual roles." [S8]
- A trust policy cannot use a wildcard `*` as part of an ARN in the `Principal` element. [S8]

Least privilege guidance (primary sources):

- Action README: grant least privilege, monitor activity, use temporary credentials, be careful with `pull_request_target`. Session policies (`inline-session-policy`, `managed-session-policies`) can narrow the assumed role further. [S6]
- ECS deploy action README lists a minimum permission set (see section 6). [S34]
- Debug: the README points to `github/actions-oidc-debugger` and advises running it only in a private repository. [S6]

---

## 3. npm publish

Trusted publishing (OIDC) [S9, S12]:

- Requirements: npm CLI 11.5.1 or later and Node 22.14.0 or later (npm docs). The setup-node docs say npm 11.5.1 or later is required and Node 24 or later is recommended because it includes a compatible npm. [S9, S12]
- Providers: GitHub Actions (GitHub-hosted runners), GitLab CI/CD (GitLab.com shared runners), CircleCI (cloud). Self-hosted runners are not supported. [S9]
- GitHub fields on npmjs.com: organization or user, repository, workflow filename (file name only, with `.yml` or `.yaml`, file must be in `.github/workflows/`), optional environment name, allowed actions. All fields are case-sensitive. [S9]
- Workflow needs `permissions: id-token: write` (and `contents: read` in the npm example). No npm token is needed to publish. [S9]
- The npm CLI detects the OIDC environment and uses it before falling back to tokens. [S9]
- npm does not validate the entry when you save it. Errors show only at publish time ("ENEEDAUTH"). setup-node docs add that a mismatch can show as "E404 Not Found". [S9, S12]
- `repository.url` in `package.json` must exactly match the GitHub repository. [S9]
- An entry must finish its first successful publish within 2 days or it expires. Existing entries cannot be edited; delete and recreate. [S9]
- Limits: "up to 10 trusted publishers per package" in the multi-publisher variant of the page. The single-publisher variant of the same page says "Each package can only have one trusted publisher configured at a time." The page source holds both variants (`TrustedPublisherOption`). Which one applies to a given package: unverified. [S9]
- Allowed actions (newer): `npm stage publish` is always allowed. Direct `npm publish` and `npm dist-tag` are separate options. Entries created before 2026-05-20 allow `npm publish` only. The multi-publisher text adds that entries created after 2026-09-03 default to `npm stage publish`. [S9]
- Reusable workflows and `workflow_dispatch`: validation checks the calling workflow's name, not the workflow that holds `npm publish`. `id-token: write` must be set in parent and child. [S9]
- Private dependencies: trusted publishing is not used for `npm install` or `npm ci`; use a read-only granular token for installs. [S9]
- Hardening on npm: in package Settings, "Require two-factor authentication and disallow tokens". Trusted publishers keep working. A stage-only entry plus no tokens is the strictest option in the page. Staged publishing needs npm CLI 11.15.0 or later and Node 22.14.0 or later; `npm stage publish` needs no 2FA; approval needs 2FA. A stage of a new package publishes a placeholder `0.0.0-stage`. [S9, S11]
- Changesets docs: "At the moment, Staged Publishing does not work with Changesets". [S16]
- Extra measures listed on the npm page: deployment environments with approvals, tag protection rules, audit entries, remove unused tokens. [S9]
- The `npm trust` command appears in npm's CLI index. I did not read its options: unverified. [S9]

Provenance [S9, S10]:

- With trusted publishing from GitHub Actions or GitLab, provenance is generated automatically, with no `--provenance` flag, only when all are true: publishing through OIDC, public repository, public package. Not for CircleCI. Not for private repositories "even when publishing public packages". [S9]
- Opt out with `provenance=false` in `.npmrc`, `NPM_CONFIG_PROVENANCE=false`, or `publishConfig.provenance: false`. [S9]
- Token-based publishing: `npm publish --provenance` needs `id-token: write`, a cloud-hosted runner, npm 9.5.0 or later, and a public `repository` in `package.json` that matches (case-sensitive). First publish of a scoped public package also needs `--access public`. Third-party tools can use `NPM_CONFIG_PROVENANCE=true` or `publishConfig.provenance: true`. [S10]
- Signing uses Sigstore public good servers and a public transparency ledger. Verify with `npm audit signatures`. Provenance "does not guarantee the package has no malicious code". [S10]
- Provenance for a package that lives in a monorepo (subdirectory `repository.directory`): not covered on the pages I read; unverified. [S9, S10]

`setup-node` for publishing [S12]:

- `registry-url`: "Optional registry to set up for auth. Will set the registry in a project level .npmrc and .yarnrc file, and set up auth to read in from env.NODE_AUTH_TOKEN." Both npm's trusted-publishing example and the setup-node example set `registry-url: 'https://registry.npmjs.org'`. [S9, S12]
- The dummy `NODE_AUTH_TOKEN` fallback was removed. With `registry-url` and no `NODE_AUTH_TOKEN`, Yarn Classic and older npm may fail and pnpm may warn. `always-auth` was removed. [S12]
- `package-manager-cache: false`: default is `true`. Caching turns on automatically when `packageManager` or `devEngines.packageManager` names npm. The advanced-usage doc says to set it to `false` in publishing workflows because "a poisoned cache may expose credentials (including OIDC tokens) to attacker-controlled code." npm's own example repeats it with the comment "never use caching in release builds". [S9, S12] (see also 335, S6)
- zizmor `cache-poisoning` names `package-manager-cache: false` for setup-node, and for release workflows says first to disable caching with GitHub's `cache-mode: none`. [S52]
- Conflict: the semantic-release GitHub Actions recipe says "Don't set `registry-url` in `actions/setup-node`, since it can cause `EINVALIDNPMTOKEN` errors. Configure a custom registry in `.npmrc` instead." [S19]
- Version seen in setup-node `action.yml`: runtime `node24`. [S12]

Monorepo publishing:

- Changesets: `changeset publish` goes into each package, checks whether its `package.json` version is published, and runs `npm publish` (or the detected package manager's publish command) if not. It creates git tags per package, `pkg-name@X.X.X` (single-package repos: `vX.X.X`); `--no-git-tag` turns tags off. It assumes the last commit is the version commit. Warning in docs: it can publish a never-versioned new package by accident, so set `"private": true` on packages that must not be published. `--tag` sets the dist-tag. `access` in `.changeset/config.json` defaults to `restricted`. [S16]
- pnpm: `publish` is in the commands that `-r` runs in every project, and (unlike `run`, `exec`, `test`, `add`) it includes the root project. Recursive publish publishes "all the packages that have versions not yet published to the registry"; `--force` tries anyway. Default git checks: clean working tree, publish branch, up to date; `--no-git-checks` skips them; in CI a detached `HEAD` skips the branch check. `--dry-run` does everything except upload. Under trusted publishing, pnpm attaches provenance on its own for a public package from a public repository; `--no-provenance` opts out. The `pnpm publish` page does not use the word OIDC and does not mention `workspace:` replacement. The `-r` page does not state publish ordering and says `publish` rejects `--no-bail`. [S13, S14] (WebFetch summaries of the pnpm pages; not cross-checked in the pnpm source: partly unverified.)
- release-please and semantic-release in monorepos: see section 4.

---

## 4. Release automation

### Changesets [S15, S16]

- Action v2.1.2 (needs Changesets v3). `changesets/action` is the combined action; there are also sub-actions `select-mode`, `version`, `pack`, `publish`, `pr-status`, `pr-comment`. For trusted publishing the README recommends the sub-actions "to tighten publish permissions". [S15]
- Permissions (combined action): `contents: write`, `pull-requests: write`, and `id-token: write` for trusted publishing. Triggers: "_any_". Repository setting needed: "Allow GitHub Actions to create and approve pull requests". [S15]
- Token: custom token only through the `github-token` input; setting `GITHUB_TOKEN` in `env` does not configure the action. With the default API push, commits and tags are signed by GitHub and attributed to the token owner; `push-with-git-cli` uses the Git CLI instead. [S15]
- Inputs: `publish-script`, `version-script` (default `changeset version`), `commit-message` and `pr-title` (default `Version Packages`), `pr-draft`, `pr-base-branch`, `create-github-releases` (default true), `push-git-tags` (default true), `cwd`. Outputs: `published`, `published-packages`, `has-changesets`, `pr-number`. [S15]
- Flow: on push to `main`, if changesets exist the action opens or updates a version pull request; when merged and versions are unpublished, it publishes. [S16]
- Docs example workflow (trusted publishing) splits `select-mode`, `version`, `pack`, `publish` jobs, with `permissions: {}` at top, per-job permissions, and `id-token: write` only on the `publish` job. The docs say this differs from npm's recommendation on purpose. The example also uses `persist-credentials: false`, `package-manager-cache: false`, `concurrency` without cancel, and suggests an environment with required reviewers for the publish job. [S16]
- Pull requests that GitHub Actions creates "do not trigger workflows"; use a personal or GitHub App token to run checks on the version pull request. Token-based publishing (`NPM_TOKEN` with "Bypass two-factor authentication") is "no longer recommended". [S16]
- Monorepo config (`.changeset/config.json`): `fixed` (groups that always share one version), `linked` (groups that share the highest version, only bumped ones), `ignore`, `updateInternalDependencies` (default `patch`), `privatePackages` (`{version:false, tag:false}` default), `access`, `baseBranch`, `bumpVersionsWithWorkspaceProtocolOnly`. `fixed` and `linked` apply only to monorepos. [S16]

### release-please [S17, S18]

- Action: `googleapis/release-please-action`. Latest release tag v5.0.0 (breaking change: Node 24). The README examples still show `@v4`. [S17] (version note: conflict between README text and latest tag)
- Behaviour: reads Conventional Commits and keeps a release pull request up to date. "When you're ready to tag a release, simply merge the release PR." `fix:` gives patch, `feat:` minor, `!` major. [S17]
- Permissions: `contents: write`, `issues: write`, `pull-requests: write`; the repository setting "Allow GitHub Actions to create and approve pull requests" may be needed. Trigger in the example: `push` to `main`. [S17]
- Token: input `token` defaults to `GITHUB_TOKEN`. Resources made with `GITHUB_TOKEN` (release pull request, tag) do not trigger other workflows, and workflows on `release.created` do not run. The README says to use a personal access token if CI must run on release pull requests. [S17]
- Inputs: `release-type`, `config-file` (default `release-please-config.json`), `manifest-file` (default `.release-please-manifest.json`), `target-branch`, `path`, `skip-github-release`, `skip-github-pull-request`, `include-component-in-tag`, `fork`, `versioning-strategy`, `release-as`, others. Outputs include `releases_created`, `prs_created`, `paths_released`, and per-path outputs `<path>--release_created`, `<path>--tag_name`, `<path>--version`. [S17]
- The action itself creates the pull request, tag and GitHub release; publishing to npm is a separate step (the README example gates `npm publish` on `release_created`). [S17] (inferred from the README example, not a stated sentence)
- Monorepo: the manifest releaser was "designed for repositories that contain multiple releasable artifacts"; a combined release pull request is created for all configured packages; config for many packages lives in two files. Options include `separate-pull-requests`, `group-pull-request-title-pattern`, `include-component-in-tag`, `bootstrap-sha`, and plugins `node-workspace` and `cargo-workspace` (`node-workspace` builds a graph of local node packages). [S18]

### semantic-release [S19-S23]

- Needs no pull request; a push to a release branch runs analysis, creates the git tag, publishes, and creates the GitHub release. Default plugins: commit-analyzer, release-notes-generator, npm, github. `tagFormat` default `v${version}`. Default branches include `main`/`master`, `next`, `next-major`, `beta`, `alpha` and maintenance ranges. [S19, S23]
- Version rules (Angular convention by default): `fix` patch, `feat` minor, `BREAKING CHANGE:` footer major. [S23]
- GitHub Actions recipe: top-level `contents: read`; the release job needs `contents: write`, `issues: write`, `pull-requests: write`, `id-token: write`. Checkout with `fetch-depth: 0`. Example installs with `npm clean-install`, runs `npm audit signatures`, then `npx semantic-release`. Triggers: push to `master` or `main`; also `workflow_dispatch` and `repository_dispatch` of type `semantic-release`. The recipe site "has been discontinued"; current docs are at semantic-release.org. [S19]
- Token: `GITHUB_TOKEN` or `GH_TOKEN` is required. Minimum permissions with `GITHUB_TOKEN`: `contents: write`, `issues: write`, `pull-requests: write`. Releases made with `GITHUB_TOKEN` do not trigger other workflows. [S21]
- npm: `NPM_TOKEN`, or trusted publishing (recommended where supported). Trusted publishing needs `id-token: write` on the job and generates provenance automatically. Configure the npm trusted publisher with the caller workflow, not a downstream reusable workflow. [S19, S20]
- `dryRun` defaults to `false` in CI and `true` otherwise. The dry run "verifies the repository push permission, even though nothing will be pushed". `ci` option default `true`. [S19]
- Pushing `package.json` changes needs `@semantic-release/git` and is "discouraged"; the default `GITHUB_TOKEN` cannot push to a protected branch. [S19]
- FAQ: "You deliberately cannot trigger a specific version release." Undo: push a fix or revert; "do not remove the Git tag associated with the buggy version". The FAQ does not cover monorepos. [S19]
- Monorepo: no native support in the pages I read. Issue 193 "Multi-package repositories support" is open (last updated 2026-07-10). Third-party monorepo tools: not read; unverified. [S22]

---

## 5. Rollback patterns

GitHub side:

- Re-run: re-runs use the privileges of the actor who started the original run and the same `GITHUB_SHA` and `GITHUB_REF`. Limit: a run can be re-run up to 50 times, and up to 30 days after its first run. Re-running failed or single jobs also re-runs dependent jobs; other jobs keep outputs from the previous attempt. [S24] (A re-run replays the old commit; it does not pick up a newer workflow file for the same SHA: inferred, unverified.)
- `workflow_dispatch`: `GITHUB_SHA` is the last commit on the chosen ref; `GITHUB_REF` is the "Branch or tag that received dispatch". The "Run workflow" button needs the workflow file on the default branch. A run from the API or CLI can target any branch or tag once the workflow has run at least once. Input types include `choice`, `boolean`, `environment`. Limits: 25 top-level input properties (10 on some non-github.com versions) and 65,535 characters of payload. `gh workflow run FILE -f name=value` passes inputs. [S25, S26]
- `workflow_run`: runs "regardless of the conclusion" of the first workflow; only if the workflow file is on the default branch; at most three levels of chaining. [S25]
- Artifacts: `upload-artifact` retention is 1 to 90 days (default 90 unless the repository sets another default). v4+ artifacts are immutable and names must be unique per run. `download-artifact` can fetch from another run or repository with `github-token`, `run-id`, and `repository` inputs. Without those, it reads only the current run. [S27]
- Container and package registries, S3 object versions, and release assets as rollback stores: not covered here except as listed below. GitHub immutable releases lock the tag to a commit and lock assets; a deleted immutable release's tag name cannot be reused. [S54]

AWS-native [S28-S33]:

- ECS deployment circuit breaker: only for services that use the rolling update (`ECS`) deployment controller. When a deployment fails it rolls back to the most recent deployment in `COMPLETED` state if `rollback` is enabled. With no `COMPLETED` deployment, it launches no new tasks and the deployment stalls. Threshold type `BOUNDED_PERCENT` (default): value (default 50) times desired count, minimum 3, maximum 200, rounded up. Other types: `UNBOUNDED_PERCENT`, `COUNT`. `resetOnHealthyTask` default `true` (only consecutive failures count). CLI form: `--deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true}"`. Health checks counted: load balancer, Cloud Map, container. AWS recommends an EventBridge rule on `SERVICE_DEPLOYMENT_FAILED`. The CloudWatch alarm option needs the console or CLI. [S28]
- CodeDeploy: a rollback is a new deployment of a previous revision with a new deployment ID. Automatic rollback can trigger on failure or on a monitoring alarm. Manual rollback = create a new deployment with any earlier revision. For EC2/on-premises, the agent first removes files from the last successful install using a cleanup file; files created by scripts remain. With overwrite mode, a failed deployment can delete files that the rollback needed. [S29]
- Lambda: a published version is a fixed snapshot; an alias is a pointer you can update. `aws lambda update-alias --function-version N` moves it (back). A weighted alias can point to at most two versions; both must have the same execution role and dead-letter queue configuration; both must be published (not `$LATEST`). Setting `function-version` with an empty `AdditionalVersionWeights` resets routing. SAM `AutoPublishAlias` plus `DeploymentPreference` uses CodeDeploy for gradual shifts and rollback. [S30, S31]
- CloudFormation: by default an updating stack that fails rolls back resources to the last known state. "Preserve successfully provisioned resources" (`--disable-rollback`) stops that; `rollback-stack` later rolls back a stack in `CREATE_FAILED` or `UPDATE_FAILED` (it deletes a stack that has no last stable state). Change sets cannot start from a stack in `UPDATE_ROLLBACK_FAILED`. Rollback triggers: up to 5 CloudWatch alarms or composite alarms, monitoring time 0 to 180 minutes; a missing alarm fails and rolls back the operation; CloudFormation does not watch triggers during a rollback. Express mode disables rollback by default. [S32, S33]
- CDK: `cdk deploy` rolls back by default; `--no-rollback` leaves a failed paused state and then `cdk rollback` can undo it; `--rollback-trigger-alarm-arns` and `--monitoring-time-minutes` mirror CloudFormation triggers. `--express` does no automatic rollback. `--hotswap` "deliberately introduces drift" and is for development. [S43]
- CloudFront: AWS recommends versioned file names over invalidation for frequently changed files; versioning "simplifies rolling forward and back between file revisions". [S44]
- ECS manual rollback = register or select an older task definition revision and update the service; the deploy action registers a task definition from a file and updates a service. The AWS pages I read did not include a dedicated "manual rollback" page for ECS: partly unverified. [S34]

---

## 6. AWS deploy steps (workflow steps only)

All AWS actions below run on Node 24 (`using: node24` in `action.yml`) unless noted. Pin the full SHA from the version table. README examples often show older major tags.

ECS [S34-S36, S56]:

- `aws-actions/amazon-ecr-login` v2.1.7: inputs `registries`, `registry-type`, `mask-password`, `skip-logout`, `http-proxy`. Outputs `registry`. Has a post step that logs out. Needs a prior credentials step. [S36]
- `aws-actions/amazon-ecs-render-task-definition` v1.9.1: inputs `task-definition` (path), `container-name`, `image`, `environment-variables`, `log-configuration-*`, `docker-labels`, `command`, `task-role-arn`, `execution-role-arn`, `env-files`, `secrets`. Output: `task-definition` (path to the rendered file). Creates a new file. [S35]
- `aws-actions/amazon-ecs-deploy-task-definition` v2.6.4: inputs `task-definition` (required), `service` (without it the action only registers), `cluster` (default `default`), `wait-for-service-stability` (valid value "true"; default no wait), `wait-for-minutes` (default 30, max 6 hours), `force-new-deployment`, `desired-count`, `codedeploy-appspec`, `codedeploy-application`, `codedeploy-deployment-group`, `codedeploy-deployment-config`, `run-task` and `run-task-*` inputs, `wait-for-task-stopped`, `enable-ecs-managed-tags`, `propagate-tags`, `max-retries`. Output `task-definition-arn`. A warning in the input text: do not expose `run-task-container-overrides` to untrusted input. [S34]
- README minimum permissions for a service: `ecs:RegisterTaskDefinition`, `iam:PassRole` (on the task roles), `ecs:UpdateService`, `ecs:DescribeServices` (scoped to the service ARN). Stand-alone task: `ecs:RunTask`, `ecs:RegisterTaskDefinition`, `ecs:DescribeTasks`, `iam:PassRole`. CodeDeploy-controlled services need CodeDeploy permissions. README examples still show `configure-aws-credentials@v1` and `amazon-ecr-login@v1`. [S34]
- `aws-actions/amazon-ecs-deploy-express-service` v1.2.2 (Express Mode services): I did not read its inputs: unverified. [S56]

Lambda [S37]:

- `aws-actions/aws-lambda-deploy` v1.1.2: inputs `function-name` (required), `package-type` (default `Zip`; `Image` needs `image-uri`), `code-artifacts-dir` (zip package), `handler` (default `index.handler`), `runtime` (default `nodejs20.x`), `s3-bucket` / `s3-key` (S3 deploy; default key `lambda-deployments/{function-name}/{timestamp}-{commit-hash}.zip`), `publish` (publish a new version), `dry-run` (default `false`; validates the request and permissions without changing code; configuration updates are skipped), `revision-id` (update only if it matches), `role` (required to create a function), plus configuration inputs (`memory-size`, `timeout`, `vpc-config`, `environment`, `layers`, `architectures`, `logging-config`, others). Creates the function if it does not exist. [S37]
- `aws-actions/setup-sam` v3: inputs `version`, `python`, `use-installer`, `token`. Output `cache-hit`. [S40]

S3 + CloudFront: no official `aws-actions` action exists for it (checked the non-archived repositories of the `aws-actions` organization on 2026-11-15; the list has no S3 or CloudFront deploy action). Steps use the AWS CLI. [S56]

- `aws s3 sync LOCAL s3://BUCKET`: uploads files whose size differs, whose local modified time is newer, or that are missing. `--delete` removes destination files that are not in the source (files excluded by filters are excluded from deletion). `--dryrun` shows operations without running them. `--cache-control`, `--content-type`, `--exclude`, `--include`, `--size-only`, `--exact-timestamps`, `--no-overwrite` exist. [S45]
- CloudFront: invalidate or use versioned names (see section 5). I did not capture invalidation limits (free paths per month, wildcard counting) from the fetch: unverified. [S44]

CloudFormation [S38]:

- `aws-actions/aws-cloudformation-github-deploy` v2.2.0: inputs `name` (stack), `template` (path or URL), `mode` (`create-and-execute` default, `create-only`, `execute-only`), `capabilities` (default `CAPABILITY_IAM`), `parameter-overrides`, `no-execute-changeset` (default false), `no-delete-failed-changeset`, `fail-on-empty-changeset`, `disable-rollback` (stack creation only), `timeout-in-minutes` (creation only), `role-arn`, `notification-arns`, `tags`, `termination-protection` (creation only), `change-set-name` (default `<stack-name>-CS`), `execute-change-set-id`, `include-nested-stacks-change-set`, `s3-bucket` / `s3-prefix` (template over the 51,200-byte inline limit), `deployment-mode` (`REVERT_DRIFT`). Outputs: `stack-id`, stack outputs, and for review mode `change-set-id`, `change-set-name`, `has-changes`, `changes-count`, `changes-summary`, `changes-markdown`. README examples show `@v2.0.0`. [S38]

CDK [S42, S43]:

- No official GitHub Action for CDK among `aws-actions` repositories. Steps call the CDK CLI. [S56]
- `cdk diff`: `--fail` exits with code 1 when differences exist; `--method` `auto` (default, builds a change set), `change-set`, or `template`; `--security-only`; `--quiet`. [S42]
- `cdk deploy`: `--require-approval` (`broadening` default, `any-change`, `never`), `--method` (`change-set` default, `direct`, `prepare-change-set`, `execute-change-set`), `--change-set-name`, `--outputs-file`, `--concurrency` (default 1), `--rollback` / `--no-rollback`, `--force`. If the environment is not bootstrapped, only stacks without assets and with templates under 51,200 bytes deploy. [S43]

Terraform [S39, S41]:

- `hashicorp/setup-terraform` v4.0.1: inputs `terraform_version` (default `latest`; accepts constraints such as `<1.13.0`), `terraform_wrapper` (default `true`; exposes `stdout`, `stderr`, `exitcode` outputs), `cli_config_credentials_hostname`, `cli_config_credentials_token`. The README notes the wrapper can make a run fail even when the plan succeeded and suggests `GITHUB_STEP_SUMMARY` instead. [S39]
- `terraform plan -detailed-exitcode`: exit 2 means changes present, 1 means error (code 0 text not captured in my fetch). `-out=FILE` saves a plan for `terraform apply FILE`; a saved plan is not encrypted and may hold sensitive data in clear text. `-input=false` for automation. `-lock=false` is "dangerous if others might concurrently run commands". [S41]

CodeBuild: `aws-actions/aws-codebuild-run-build` v1.0.19 exists; inputs not read: unverified. [S56]

---

## 7. Protection write APIs

Method and endpoint list from the GitHub REST OpenAPI description (`github/rest-api-description`, version 1.1.4 seen) [S46]:

| Object | Operations |
|---|---|
| Repository ruleset | `GET/POST /repos/{owner}/{repo}/rulesets`; `GET/PUT/DELETE /repos/{owner}/{repo}/rulesets/{ruleset_id}`; `GET .../rulesets/{ruleset_id}/history` and `/history/{version_id}` |
| Organization ruleset | same shapes under `/orgs/{org}/rulesets` |
| Classic branch protection | `GET/PUT/DELETE /repos/{owner}/{repo}/branches/{branch}/protection` (plus sub-resources such as `/enforce_admins`) |
| Environment | `GET /repos/{owner}/{repo}/environments`; `GET/PUT/DELETE .../environments/{environment_name}` |
| Deployment branch policies | `GET/POST .../environments/{name}/deployment-branch-policies`; `GET/PUT/DELETE .../{branch_policy_id}` |
| Custom protection rules | `GET/POST .../deployment_protection_rules`; `GET/DELETE .../{protection_rule_id}`; `GET .../deployment_protection_rules/apps` |

Payloads [S46]:

- Ruleset create: required `name`, `enforcement`; optional `target`, `bypass_actors`, `conditions`, `rules`. Update (`PUT`): no field is marked required (same fields). `target` enum: `branch`, `tag`, `push`, `repository`. `enforcement` enum: `disabled`, `active`, `evaluate`. Whether a ruleset `PUT` replaces the whole `rules` array or merges: not stated in the OpenAPI text or on the REST pages I read: unverified. [S46, S48]
- Rule types in the schema include `required_deployments` (parameter `required_deployment_environments`: "environments that must be successfully deployed to before branches can be merged"), `required_status_checks`, `pull_request`, `required_signatures`, `non_fast_forward`, `creation`, `update`, `deletion`, `tag_name_pattern`, `workflows`, `merge_queue`, `code_scanning`, and others. [S46]
- Ruleset `evaluate` mode: "`evaluate` allows admins to test rules before enforcing them... (`evaluate` is only available with GitHub Enterprise)". Rule Insights shows results. [S46]
- Ruleset history endpoints return earlier versions (`version_id`). [S46]
- Branch protection `PUT`: body keys `required_status_checks`, `enforce_admins`, `required_pull_request_reviews`, `restrictions` are all required (each can be `null`); optional `required_linear_history`, `allow_force_pushes`, `allow_deletions`, `block_creations`, `required_conversation_resolution`, `lock_branch`, `allow_fork_syncing`. "Passing new arrays of `users` and `teams` replaces their previous values." Users, apps and teams together are limited to 100. User/app/team restrictions are only for organization-owned repositories. [S46, S48]
- Environment `PUT`: `wait_timer` (0 to 43,200), `prevent_self_review`, `reviewers` (up to 6; each `type` `User` or `Team` and `id`), `deployment_branch_policy` (`null` = all branches; else `protected_branches` and `custom_branch_policies` are both required and must be opposite; same value returns 422). The page does not say whether omitted fields reset: unverified. [S46, S48]
- Branch or tag name patterns for an environment are set through the deployment-branch-policies endpoints, not the environment `PUT`. Secrets are set through the Actions secrets API. [S46]

Scopes and permissions [S47, S48]:

- Fine-grained token or GitHub App permission (from GitHub's autogenerated permission data): rulesets create/update/delete and history: repository "Administration" write; `GET` of repository rulesets: "Metadata" read. Branch protection `GET`: Administration read; `PUT` and `DELETE`: Administration write. Environments: `GET` environment and list and deployment-branch-policy reads: "Actions" read; `PUT`/`DELETE` environment, deployment branch policy writes, and custom protection rule writes: Administration write. Organization rulesets: organization "Administration" write (even for `GET`). The repository "Environments" permission covers environment secrets only. [S47]
- Classic tokens: environment `PUT`/`DELETE` need `repo`; `GET` needs `repo` for private repositories only. Classic scopes for rulesets and branch protection: not stated on the pages I read: unverified. Branch protection: "requires admin or owner permissions to the repository". [S48]
- Plans: protected branches are available in public repositories on Free, and in public and private repositories on Pro, Team and Enterprise. [S46]

Previewing a change before writing:

- No REST endpoint has a dry-run flag (none in the OpenAPI path list for these objects). [S46]
- Read the current object first with the `GET` of the same path; the `PUT` shapes above are the same objects the `GET` returns for branch protection and environments (the response schema was not compared field by field: unverified). Ruleset history can be read after a write. `evaluate` enforcement is the only built-in "try without blocking" mode, and only on GitHub Enterprise. [S46]
- `gh api` sends a `POST` when you pass `-f` or `-F` fields (GitHub CLI behaviour; the `gh api` manual page was not read: unverified).

---

## 8. Dry run

`act` (nektos/act v0.2.97; repository pushed 2026-11-14) [S49-S51]:

- Not supported or partial, quoted from the "not supported" page: "Openid Connect url is not defined"; "`job.environment` ignored and scoping secrets by deployment environment is not supported"; "Incomplete `github` context"; "`concurrency` is ignored"; "`job.permissions` ignored"; "`job.timeout-minutes` ignored"; "`job.continue-on-error` ignored"; run step cancellation not implemented; `GITHUB_STEP_SUMMARY` values discarded; problem matchers and annotations ignored; Node actions need `node` in the container PATH. [S49]
- The page does not mention services, reusable workflows or artifacts. The source shows service-container code in `pkg/runner/run_context.go` (`ServiceContainers`, `pullServicesImages`, `waitForServiceContainer`) and a `reusable_workflow.go` file; the docs do not describe their limits: reusable workflow support level unverified. [S49, S51]
- Flags (from `cmd/root.go` and the usage page): `-n`/`--dryrun` ("disable container creation, validates only workflow correctness"), `-j` job, `-W` workflow file or directory, `-l` list, `-e` event payload file, `workflow_dispatch -e payload.json`, `--input NAME=value`, `-s NAME=value` / `--secret-file`, `--var`, `--env-file` (default `.env`), `--matrix`, `-P` platform image, `--container-architecture`, `--artifact-server-path`, `--action-offline-mode`, `--local-repository` (replace a repository and ref with a local folder), `--insecure-secrets` ("NOT RECOMMENDED"). `.actrc` holds default arguments. GITHUB_TOKEN is passed as a secret (`-s GITHUB_TOKEN`). [S49, S50]
- `act` runs on Docker. A Docker requirement statement was not on the usage page I read; the README says it uses the Docker API: so Docker is needed. [S49]
- Effect on a CD workflow: a job that needs `id-token` cannot obtain a token in `act`; `configure-aws-credentials` supports a custom `sts-endpoint` ("e.g. MinIO, LocalStack") and `force-skip-oidc`, and static credentials can be passed as secrets. Whether LocalStack covers STS/OIDC login: not read (third party): unverified. [S6]

Other no-cloud or no-op checks that primary docs describe:

- Static: `actionlint` and `zizmor` run offline for most audits (zizmor table column "Works offline"); see 335, S15 and S16. [S52]
- `aws-lambda-deploy` `dry-run: true`. [S37]
- CloudFormation action: `mode: create-only` or `no-execute-changeset: true` creates a change set and outputs `changes-markdown` for review; later `execute-change-set-id`. [S38]
- `cdk diff --fail`; `cdk deploy --method prepare-change-set`. [S42, S43]
- `terraform plan -detailed-exitcode -out`; `setup-terraform` wrapper outputs. [S39, S41]
- `aws s3 sync --dryrun`. [S45]
- `pnpm publish --dry-run`; `semantic-release` dry run (needs push permission); `changeset publish`: no dry-run flag in the sections read. [S13, S16, S19]
- GitHub: `workflow_dispatch` with a custom boolean input is a normal workflow pattern; no GitHub doc page names it a dry-run feature: unverified as official guidance. [S25]
- `terraform apply`, `cdk deploy` and `aws ecs update-service` have no dry-run flag in the pages I read. ECS `deploy-task-definition` `service` input empty means "register only, do not deploy". [S34]

---

## 9. Security of CD triggers

GitHub documentation (see also 335, S32-S34 for `pull_request_target` and `workflow_run`) [S25]:

- `push` tags: runs when a commit or tag is pushed. Events are not created for tags if more than three tags are pushed at once, and not if more than 5,000 branches are pushed at once. `tags` filter example `v1.**`. Path filters are not evaluated for tag pushes (335, S1). [S25]
- `release`: types `published`, `unpublished`, `created`, `edited`, `deleted`, `prereleased`, `released`. `GITHUB_REF` is `refs/tags/<tag_name>`; `GITHUB_SHA` is the last commit in the tagged release. No runs for `created`, `edited`, `deleted` of draft releases; `prereleased` does not trigger for pre-releases published from drafts, but `published` does. Releases or tags created with `GITHUB_TOKEN` do not start workflows (see 335, S32; release-please and semantic-release docs repeat this). [S17, S21, S25]
- `workflow_dispatch`: see section 5. Any user with write access can start it (the docs page I read does not state the permission level: unverified). Inputs are an untrusted-input source for `${{ }}` in `run:` (see 335, S34 for contexts); the `inputs` context is in the zizmor `template-injection` scope as far as the audit text says "attacker-controllable expression contexts" (specific `inputs` mention not found in the lines read: unverified). [S25, S52]
- `workflow_run`: runs with access to secrets and write tokens "even if the previous workflow was not"; runs regardless of the triggering conclusion; must exist on the default branch; `GITHUB_SHA` is the last commit on the default branch; GitHub warns about untrusted code and cache poisoning. [S25]
- `deployment` and `deployment_status`: `deployment` runs when someone creates a deployment; `GITHUB_SHA` is the commit to deploy and `GITHUB_REF` is the branch or tag (empty if created with a SHA). `deployment_status`: runs when a third party provides a status; a state of `inactive` does not trigger a run. [S25]
- Environment deployments through a workflow create deployment objects and `deployment_status` objects with the environment name and URL. [S2 reusable text via S1]
- GitHub's OIDC page: tokens requested for Dependabot update jobs have `event_name` of `dynamic`; the page advises allowing only expected event names in trust policies when the cloud provider supports an `event_name` condition. [S4]
- npm doc extra measures for release triggers: use environments with approvals; enable tag protection rules. GitHub rulesets can target tags (`target: tag`) and have `tag_name_pattern`, `creation`, `update`, `deletion` rules. [S9, S46]
- Immutable releases: once published, the tag is locked to a commit and cannot be moved or deleted while the release exists; assets cannot be changed; a release attestation is generated. Recommended order: create a draft, attach assets, publish. [S54]

zizmor (v1.32.0) [S52]:

- `use-trusted-publishing`: "Detects packaging workflows that could use Trusted Publishing." The page lists PyPI, RubyGems, crates.io, npm ("Trusted publishing for npm packages"), and NuGet. The table shows "Works offline" yes, auto-fix no, configurable no. The persona (regular, pedantic, auditor) for this audit is not shown in the table: unverified. [S52]
- `cache-poisoning`: flags (a) reads from caches in release workflows and (b) writes to caches through privileged triggers when `cache-mode: write` or `write-only` is explicit (needs zizmor 1.31.0 or later). It is aware of GitHub's `cache-mode` and suppresses findings when `cache-mode: none` is effective. Remedies listed: `cache-mode: none`, remove cache actions, disable by trigger (`!startsWith(github.ref, 'refs/tags/')`), setup-node `package-manager-cache: false`. [S52]
- GitHub `cache-mode` values: `read`, `write`, `write-only`, `none`; job-level override; default depends on trigger; explicit `write` or `write-only` on low-trust triggers can reintroduce poisoning risk. Availability: docs source shows the feature for `fpt` and `ghec` only (not GitHub Enterprise Server). [S26, S3b]
- `dangerous-triggers`: `pull_request_target`, `workflow_run`, and (since 1.31.0) `issue_comment`. It does not list `push` tags, `release`, `workflow_dispatch` or `deployment` events. [S52]
- `secrets-outside-env`: flags use of the `secrets` context in jobs without an environment (not `GITHUB_TOKEN`); since zizmor 1.24.0 shown only in the "auditor" persona. [S52]
- `artipacked`: credential persisted by `actions/checkout` (below v6.0.0 in `.git/config`; v6.0.0 and later under `$RUNNER_TEMP`). Other audits in the list that apply to CD: `excessive-permissions`, `unpinned-uses`, `overprovisioned-secrets`, `secrets-inherit`, `template-injection`, `github-env`, `known-vulnerable-actions`, `impostor-commit`, `ref-confusion`, `dependabot-cooldown` (names only; see 335, S16). [S52]
- I found no zizmor audit that targets the `release`, push-tag, or `workflow_dispatch` triggers as such: based on the audit headings and the trigger lists read. [S52]

OpenSSF Scorecard (v5.6.0) [S53]:

- Signed-Releases (risk High): looks in the last five release assets for `*.minisig`, `*.asc`, `*.sig`, `*.sign`, `*.sigstore`, `*.sigstore.json`, `*.intoto.jsonl`. A signature per release scores 8; a SLSA provenance file (`*.intoto.jsonl`) per release scores 10. The check looks at the 30 most recent releases for an artifact, ignores source-only automatic releases, and "does not verify the signatures". GitHub only. [S53]
- Packaging (risk Medium): looks for GitHub packaging workflows and language-specific actions that upload to a hub such as npm. GitHub only. [S53]
- Token-Permissions (High): best score with read-only top-level permissions and writes declared at job level. One point lost when jobs define permissions but top-level is not defined. Warns on sensitive job-level scopes such as `actions` and `checks`. (see 335, S19 for Pinned-Dependencies and Dangerous-Workflow). [S53]
- Whether `npm publish --provenance` or npm trusted-publishing provenance counts for Signed-Releases: the check reads release assets only; npm provenance does not add a release asset. Attaching `actions/attest` output as a release asset: not stated: unverified. [S53]

---

## Unverified or open items

- Which one of the two npm trusted-publisher variants (up to 10 entries per package vs one entry) applies today (section 3).
- The `npm trust` CLI options (section 3).
- Provenance for a monorepo package with `repository.directory` (section 3).
- The pnpm `publish` and `-r` details come from fetch summaries, not from the pnpm docs source: `workspace:` replacement, publish order, skip rules for a single package (section 3).
- `registry-url` conflict: npm and setup-node docs vs the semantic-release recipe (section 3). Not tested by running a workflow.
- Which concurrency statement is current on github.com ("one pending" present or not) (section 1).
- Whether AWS now supports custom OIDC claims (GitHub AWS page vs action README) (section 2). The AWS announcement page was not opened.
- Classic PAT scopes for rulesets and branch protection (section 7).
- Whether a ruleset `PUT` replaces or merges `rules`; whether an environment `PUT` resets omitted fields (section 7).
- Whether `evaluate` enforcement is limited to Enterprise today (OpenAPI text says so; not cross-checked on the docs page) (section 7).
- `act`: reusable workflow support level; whether Docker is documented as required on the usage page; LocalStack/STS behaviour (section 8).
- Inputs of `amazon-ecs-deploy-express-service` and `aws-codebuild-run-build` (section 6).
- CloudFront invalidation limits and cost rules, and exact `create-invalidation` syntax (section 6).
- ECS manual rollback guidance page (section 5).
- GitHub permission level needed to run `workflow_dispatch` (section 9).
- zizmor `use-trusted-publishing` persona; whether `template-injection` names `inputs` explicitly (section 9).
- The WebFetch tool returns model-made summaries. For these pages, the text came through WebFetch, not from a repository source: pnpm `publish` and `recursive`, semantic-release configuration and FAQ and recipe, nektos `not_supported` and `usage`, AWS pages (ECS circuit breaker, CodeDeploy rollback, Lambda aliases, CloudFormation pages, CDK pages, CloudFront, `aws s3 sync`, IAM OIDC), Terraform `plan`. Quotes from them are as the tool returned them; I did not check them against the page source.

## Sources

- S1 https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments (read from source `content/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments.md` in https://github.com/github/docs via `gh api`)
- S2 https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments (source file `content/actions/reference/workflows-and-actions/deployments-and-environments.md`; reusables `custom-deployment-protection-rules-limits.md`, `branch-and-tag-deployment-rules-configuration.md`, `environment-deployment-event.md` under `data/reusables/actions/`)
- S3 https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments (source file `.../control-deployments.md`)
- S3b https://github.com/github/docs/blob/main/data/features/actions-nga.yml and `actions-environments-without-deployments.yml`, `actions-cache-mode.yml` (feature version files, `versions: fpt, ghec`)
- S4 https://docs.github.com/en/actions/reference/security/oidc (source `content/actions/reference/security/oidc.md`)
- S5 https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws (source file `.../oidc-in-aws.md`; reusables `oidc-deployment-protection-rules.md`, `oidc-custom-claims-aws-restriction.md`)
- S6 https://github.com/aws-actions/configure-aws-credentials (README.md and action.yml at v6.3.0; release API)
- S7 https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html
- S8 https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_terms-and-concepts.html
- S9 https://docs.npmjs.com/trusted-publishers (source https://github.com/npm/documentation/blob/main/content/packages-and-modules/securing-your-code/trusted-publishers.mdx)
- S10 https://docs.npmjs.com/generating-provenance-statements
- S11 https://docs.npmjs.com/staged-publishing (source `.../staged-publishing.mdx`)
- S12 https://github.com/actions/setup-node (action.yml, README.md, docs/advanced-usage.md section "Publishing to npm with Trusted Publisher (OIDC)")
- S13 https://pnpm.io/cli/publish
- S14 https://pnpm.io/cli/recursive
- S15 https://github.com/changesets/action (README.md, action.yml)
- S16 https://changesets.dev/guide/automating and source https://github.com/changesets/changesets/tree/main/docs/guide (`automating.md`, `versioning-and-publishing.md`, `cli.md`, `config.md`)
- S17 https://github.com/googleapis/release-please-action (README.md, action.yml, release v5.0.0 notes)
- S18 https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md
- S19 https://semantic-release.gitbook.io/semantic-release/recipes/ci-configurations/github-actions (discontinued site) and https://semantic-release.org/usage/configuration and https://semantic-release.org/support/faq
- S20 https://github.com/semantic-release/npm (README.md)
- S21 https://github.com/semantic-release/github (README.md)
- S22 https://github.com/semantic-release/semantic-release/issues/193
- S23 https://github.com/semantic-release/semantic-release (README.md)
- S24 https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs (source `content/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs.md`)
- S25 https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows (source `content/actions/reference/workflows-and-actions/events-that-trigger-workflows.md`; reusables `workflow-run-permissions-warning.md`, `branch-requirement.md`, `inputs-vs-github-event-inputs.md`)
- S26 https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax (source `content/actions/reference/workflows-and-actions/workflow-syntax.md`, section `cache-mode`)
- S27 https://github.com/actions/upload-artifact and https://github.com/actions/download-artifact (README.md)
- S28 https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html
- S29 https://docs.aws.amazon.com/codedeploy/latest/userguide/deployments-rollback-and-redeploy.html
- S30 https://docs.aws.amazon.com/lambda/latest/dg/configuration-aliases.html
- S31 https://docs.aws.amazon.com/lambda/latest/dg/configuring-alias-routing.html
- S32 https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/using-cfn-rollback-triggers.html
- S33 https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/stack-failure-options.html
- S34 https://github.com/aws-actions/amazon-ecs-deploy-task-definition (README.md, action.yml)
- S35 https://github.com/aws-actions/amazon-ecs-render-task-definition (action.yml)
- S36 https://github.com/aws-actions/amazon-ecr-login (action.yml)
- S37 https://github.com/aws-actions/aws-lambda-deploy (action.yml)
- S38 https://github.com/aws-actions/aws-cloudformation-github-deploy (README.md, action.yml)
- S39 https://github.com/hashicorp/setup-terraform (README.md, action.yml)
- S40 https://github.com/aws-actions/setup-sam (action.yml)
- S41 https://developer.hashicorp.com/terraform/cli/commands/plan
- S42 https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-diff.html
- S43 https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-deploy.html
- S44 https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Invalidation.html
- S45 https://docs.aws.amazon.com/cli/latest/reference/s3/sync.html
- S46 https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.json (OpenAPI 3.0.3, info version 1.1.4; paths, request bodies, `repository-rule-enforcement`, `repository-rule-required-deployments`)
- S47 https://github.com/github/docs/blob/main/src/github-apps/data/fpt-2022-11-28/fine-grained-pat-permissions.json (data behind https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens)
- S48 https://docs.github.com/en/rest/repos/rules and https://docs.github.com/en/rest/branches/branch-protection and https://docs.github.com/en/rest/deployments/environments (read through WebFetch)
- S49 https://nektosact.com/not_supported.html and https://nektosact.com/usage/index.html
- S50 https://github.com/nektos/act/blob/master/cmd/root.go (flag definitions) and https://github.com/nektos/act (README.md)
- S51 https://github.com/nektos/act/blob/master/pkg/runner/run_context.go and `pkg/runner/reusable_workflow.go` (file listing)
- S52 https://docs.zizmor.sh/audits/ (source https://github.com/zizmorcore/zizmor/blob/main/docs/audits.md)
- S53 https://github.com/ossf/scorecard/blob/main/docs/checks.md
- S54 https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases (source `content/code-security/concepts/supply-chain-security/immutable-releases.md`)
- S56 Release and commit lookups through the GitHub REST API (read-only GETs): `gh api repos/<owner>/<repo>/releases/latest` and `.../commits/<tag>` for each action in the version table; non-archived repository list of https://github.com/aws-actions
