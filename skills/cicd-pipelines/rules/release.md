# Release rules (RELEASE-*)

How a release workflow (`release.yml`) makes a release: one release tool, annotated tags on main, a tag ruleset, a safe token, safe triggers and release notes. This file is the single source of truth for these rules. Both branches of the skill load it by need (see "Loading by need" in [SKILL.md](SKILL.md)).

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide. "Measured" means the rule reads measured run times of the intake.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`).
- No release rule is critical. The SEC rules cover the exploitable security problems in CD files.
- "The release workflow" is `release.yml`, or any workflow that runs a release tool step or a publish step. RELEASE-02, RELEASE-04, RELEASE-05 and RELEASE-06 read it.

### RELEASE-01
- **Severity:** required
- **Rule:** The repo uses one release tool. The skill keeps the existing tool. The `release_tool` fact lists the tools found (`changesets`, `release-please`, `semantic-release`, `release-it`). Two or more values are a finding that names them. An empty value (status `default`) is a finding too, because this file is loaded only for a release repo. When a repo has none, create mode adds Changesets (the owner choice), which works for a single package and for a monorepo and gives each change an explicit version intent.
- **Check:** mechanical: the `release_tool` fact has exactly one value.
- **Fix:** Keep the one tool that the release workflow runs and remove the other tools, or, when the repo has none, add Changesets.

### RELEASE-02
- **Severity:** required
- **Rule:** Release tags are annotated, and the workflow makes them on a commit that is on main. A tag that a step makes with `git tag` has `-a`, `-s` or `-m`, which makes it annotated. The tag step runs on a commit that is on main: its job runs for a push to main alone, or a step checks `git merge-base --is-ancestor <sha> origin/main` before the tag. A job with a `workflow_dispatch` trigger needs that ancestor step, and only a job that runs for a push to main alone passes without it. A tag that a release tool action makes is not read, because the skill cannot read the tag type of the tool.
- **Check:** mechanical: each `git tag` command of the release workflow has `-a`, `-s` or `-m`, and its job runs for a push to main alone or has the ancestor step.
- **Fix:** Make the tag with `git tag -a <tag> -m <message>` and run the tag step only for a push to main, or add the `git merge-base --is-ancestor` check before it.

### RELEASE-03
- **Severity:** required
- **Rule:** A tag ruleset protects the release tags: restricted creation, no update and no delete. The check reads the `rulesets` fact, which holds only the name, the target and the enforcement of each ruleset. With the status `detected` and no ruleset with `target: tag` and `enforcement: active`, it is a finding. With any other status there is no finding. Only the existence of an active tag ruleset is checked, because the fact does not hold the rules. The PROTECT rules give the content of the ruleset and the write flow.
- **Check:** mechanical: the `rulesets` fact has the status `detected` and holds no ruleset with `target: tag` and `enforcement: active`.
- **Fix:** Add an active tag ruleset for the release tag pattern that restricts creation to the release actor and blocks update and delete (the PROTECT rules give its content).

### RELEASE-04
- **Severity:** required
- **Rule:** The release token is `GITHUB_TOKEN` or a GitHub App token that the job gets with `actions/create-github-app-token`, never a personal access token (PAT). The App credentials (`app-id`, `client-id` and `private-key`) are kept in an environment, so the job names an `environment`, and an App token with no `environment` on the job is a finding. A PAT is a finding: a `secrets.*` value, other than `GITHUB_TOKEN` and the App credential inputs, used as a `token:`, `GH_TOKEN` or `GITHUB_TOKEN` value. When `deploy.yml` has a `push: tags` trigger and the release workflow makes the tag with `GITHUB_TOKEN` (a tag that a tool action makes with `GITHUB_TOKEN` counts), that is a finding, because events that `GITHUB_TOKEN` makes start no new workflow run, so the App token is required. The release actor is the identity that creates the tag: the release App when the job uses an App token, and GitHub Actions (`github-actions[bot]`) when it uses `GITHUB_TOKEN`. The tag ruleset of the PROTECT rules reads this definition.
- **Check:** mechanical: no release job uses a PAT, an App token job names an `environment`, and a release that must start `deploy.yml` from a tag uses an App token.
- **Fix:** Use `GITHUB_TOKEN`, or an App token from `actions/create-github-app-token` with the credentials in an environment (the App token is required when the tag must start `deploy.yml`), and remove the PAT.

### RELEASE-05
- **Severity:** required
- **Rule:** The allowed triggers of the release workflow are only `push` to main and `workflow_dispatch`. A `pull_request` trigger is a finding. A tag push trigger (`push: tags:`) in the release workflow is a finding too, because the list is closed. Every other trigger of the release workflow is a finding too (`schedule`, `workflow_run`, `release`, `workflow_call`, or a `push` to a branch other than main, or a `push` with no `branches: [main]` filter).
- **Check:** mechanical: the `on:` block of the release workflow holds only `push` with `branches: [main]` and `workflow_dispatch`.
- **Fix:** Release from a push to main (the release PR flow) or from a dispatch, and remove every other trigger.

### RELEASE-06
- **Severity:** required (a published package), suggestion (an app)
- **Rule:** Each release makes release notes or a changelog. The severity is `required` when any `package_kind` entry is published, and `suggestion` otherwise. Notes exist when the release job creates a GitHub release (`changesets/action` with `createGithubReleases` not `false`, `gh release create`, or a release action), or when the tool writes a changelog (a Changesets `changelog` setting other than `false`, a release-please config with no `skip-changelog`). A release action is `changesets/action`, `softprops/action-gh-release`, `ncipollo/release-action` or `googleapis/release-please-action`. A repo with semantic-release has notes, because its default GitHub plugin creates the release. A release tool outside these lists (for example release-it) is not read and gives no finding.
- **Check:** mechanical: the release job creates a GitHub release, or the tool config writes a changelog.
- **Fix:** Turn on the GitHub release of the release tool (for Changesets, remove `createGithubReleases: false`) or set a changelog in its config.
