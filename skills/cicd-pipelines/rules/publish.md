# Publish rules (PUBLISH-*)

How the publish job of a release workflow publishes a package to npm: trusted publishing with no stored token, a frozen install with no cache, dependency order in a monorepo, a safe re-run and a stable workflow file name. This file is the single source of truth for these rules. Both branches of the skill load it by need (see "Loading by need" in [SKILL.md](SKILL.md)).

- "Mechanical" means a script or a regex can check the rule. "Judgement" means you decide. "Measured" means the rule reads measured run times of the intake.
- The severity is fixed for each rule. The first word of the Severity bullet is the level (`critical`, `required` or `suggestion`).
- No publish rule is critical. The SEC rules cover the exploitable security problems in CD files.
- Provenance is not a rule: npm adds it for a public package of a public repo, and the report shows it as an intake fact.
- "The publish job" is the job with a publish step: `changeset publish`, `pnpm -r publish`, `npm publish`, `semantic-release`, or `changesets/action` with a `publish:` input.

### PUBLISH-01
- **Severity:** required
- **Rule:** npm uses trusted publishing (OIDC): the publish job has `permissions: id-token: write`, runs on a GitHub-hosted runner (no `self-hosted` label), uses Node 22.14.0 or later, and has npm 11.5.1 or later. The check reads only a literal `node-version` of the publish job, as an exact version, a major, or `<major>.x`. A major or `<major>.x` resolves to the latest release of its line. A version below 22.14.0 is a finding. A major `24` or later passes both checks. A version from 22.14.0 up to, but not including, major 24 (`22`, `22.x`, `23`) passes the Node check, and it is a finding for the npm check unless a step `npm install -g npm@<11.5.1 or later>` or `npm@latest` runs in the job. `lts/*`, a `node-version-file`, a range such as `^22`, a matrix expression and a missing `node-version` are not read, so they give no Node finding and no npm finding. A `runs-on` that is a group or an expression is not read. The job also uses no `NPM_TOKEN` secret (`secrets.NPM_TOKEN`, or `NODE_AUTH_TOKEN` from a secret). The sources conflict on `registry-url` of `actions/setup-node`: the npm and setup-node docs set it, and the semantic-release recipe says not to set it. The rule takes no side, so `registry-url` or its absence is never a finding. The conflict does not affect Changesets, and a repo that keeps semantic-release follows the semantic-release recipe for this key.
- **Check:** mechanical: the publish job has `id-token: write`, a GitHub-hosted runner, a readable `node-version` of 22.14.0 or later with npm 11.5.1 or later, and no `NPM_TOKEN` secret.
- **Fix:** Give the publish job `id-token: write`, a GitHub-hosted runner, Node 24 (or Node 22.14.0 or later with `npm install -g npm@latest`) and no `NPM_TOKEN`, and set the trusted publisher of each package on npm.

### PUBLISH-02
- **Severity:** required
- **Rule:** The publish job installs from the frozen lockfile (`npm ci`, `pnpm install --frozen-lockfile` or `yarn install --immutable`) with no cache: `actions/setup-node` sets `package-manager-cache: false` and no `cache:` input, and the job has no `actions/cache` step, so a poisoned cache cannot reach the registry. COST-05 owns the CI install and its cache.
- **Check:** mechanical: the publish job has a frozen install, `package-manager-cache: false` on `actions/setup-node`, no `cache:` input and no `actions/cache` step.
- **Fix:** Use the frozen install command, set `package-manager-cache: false` on `actions/setup-node` and remove every cache from the publish job.

### PUBLISH-03
- **Severity:** required
- **Rule:** A monorepo with two or more published packages (the `monorepo` fact, and at least two `package_kind` entries with the value published) publishes in dependency order, with a tool that does this: `changeset publish`, `pnpm -r publish` (also `pnpm publish -r` and `--recursive`), or `changesets/action` whose `publish:` input is one of them. A loop, a matrix or `npm publish --workspaces` is a finding.
- **Check:** mechanical: the publish step of a monorepo with two or more published packages is one of the listed tool forms.
- **Fix:** Publish with `changeset publish` or `pnpm -r publish` in one step, and remove the loop or the matrix.

### PUBLISH-04
- **Severity:** suggestion
- **Rule:** The publish job skips a version that is already on the registry, so a re-run is safe. It passes when it runs `changeset publish`, `pnpm -r publish` or `semantic-release` (they skip a published version), or when a step checks `npm view <name>@<version>` before `npm publish`. A plain `npm publish` with no check is a finding.
- **Check:** judgement: the publish job is a plain `npm publish` with no published-version check.
- **Fix:** Publish with `changeset publish` or `pnpm -r publish`, or check `npm view <name>@<version>` before `npm publish`.

### PUBLISH-05
- **Severity:** suggestion
- **Rule:** The npm trusted-publisher entry names `release.yml` exactly, so a rename breaks publishing. The workflow file that holds the publish job is `release.yml`. Another name is a finding, and its row gets the ⚑ mark, because the skill cannot read the npm settings and the admin must change the entry by hand. The skill never renames the file: the fix is manual, and an approved row is listed as skipped.
- **Check:** mechanical: the workflow file that holds the publish job is named `release.yml`.
- **Fix:** After the merge, an admin renames the file to `release.yml` and sets the trusted-publisher entry of each package on npm to `release.yml`, as the ⚑ section shows.
