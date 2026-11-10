# Create steps

Create a CI workflow for a repo from a template, with every rule applied and the intake facts filled in. The result passes actionlint where actionlint is installed, and its self-review has no critical and no required finding.

Read only the intake JSON (see [SKILL.md](SKILL.md)) for the repo facts. The one exception is step 5: it reads the Dependabot file and `security-audit.yml` with the Read and Glob tools, as SEC-02 does in the review steps. Never edit branch protection or rulesets.

## Steps

1. Run the intake through the router and read its JSON.
   - When the `existing_workflows` fact holds the path `.github/workflows/ci.yml` or `.github/workflows/ci.yaml`, write nothing, say that a CI workflow exists, and offer a review ([review.md](review.md)).
   - When the `package_manager` fact has `lockfile: null`, write nothing, say that a lockfile is needed first (COST-05), and offer a review.
2. Pick the template. Use [templates/monorepo.yml](templates/monorepo.yml) when the `monorepo` fact has `monorepo: true`. Otherwise use [templates/single-package.yml](templates/single-package.yml).
3. Fill the template from the intake facts with the fill table below. Change only the values that the table names. Keep the job ids, the job names, the `timeout-minutes` values, the pins and the structure. When the table removes a job, remove it from the `needs:` of `ci-passed` too, and name the removed job and the reason in the `## Created` section.
4. Load and apply every rule file: [rules/naming.md](rules/naming.md), [rules/job-graph.md](rules/job-graph.md), [rules/cost.md](rules/cost.md), [rules/security.md](rules/security.md) and [rules/maintainability.md](rules/maintainability.md). Load [rules/monorepo.md](rules/monorepo.md) only for a monorepo. Create mode starts with no shards (GRAPH-05) and uses the create values of COST-04: 5 for `changes` and `ci-passed`, 10 for `lint`, `typecheck`, `build` and `audit`, and 15 for `test`. Create mode never uses `pull_request_target` or `workflow_run` (SEC-07).
5. Write the files.
   - Write `.github/workflows/ci.yml`.
   - Glob `.github/dependabot.yml` and `.github/dependabot.yaml`. When neither exists, write `.github/dependabot.yml` with the Dependabot block below. When one exists and has no `github-actions` entry, add only that entry under `updates:`, and leave every other entry as it is. When one exists and has the entry, leave it unchanged.
   - Take the `existing_workflows` fact: when it holds `.github/workflows/security-audit.yml` or `.github/workflows/security-audit.yaml`, leave that file unchanged. Otherwise write `.github/workflows/security-audit.yml` with the security audit block below, filled with the same package manager and Node version.
6. Run actionlint when the `installed_tools` fact has `installed: true` for it. Run it in the repo root as `actionlint -format '{{json .}}'` (see [tools.md](tools.md)), as its own call, never chained with another command. When it reports errors, fix the file and run it again, up to 3 runs in all. Only the findings whose `filepath` is a file that this run wrote count. A finding in another file is named in the `## Created` section and is not a finding of the self-review. Errors that remain after the third run become findings `actionlint-<kind>` (suggestions) in the self-review, as the merge rules of [tools.md](tools.md) say. When actionlint is not installed, say so and give the install hint of [tools.md](tools.md). Never install a tool.
7. Self-review the files that you wrote against the same rules, as [review.md](review.md) does. The final message has this order:
   - `## Created`. One line for each file that the run wrote or left unchanged: the path and the word `written` or `unchanged`. A file that the run edited (a Dependabot file with an added entry) is `written`. A line for each removed job, and for a missing test runner. The actionlint output of step 6 when it has errors.
   - For each written file, a heading `### <path>` and the file text in a fenced `yaml` block.
   - The report of the review report contract in [review.md](review.md), starting with the title line `# ci-pipelines review: .github/workflows/ci.yml (created)` and the `**Result:` line right after it. Its section 2 names the defaults that the run used. Its job graph section sketches the created jobs.

## Fill table

| Fact | What changes |
|---|---|
| `package_manager` | The setup step, the `cache:` value, the install command, the audit command and the lockfile name in the `changes` filter, as the package manager table says. |
| `node_version_app`, `engines`, `supported_node_majors` | The Node versions, as "Node versions" says. |
| `scripts` | The script of each job. A job whose script does not count is removed. |
| `test_runners` | Without a runner, the `test` job is removed. With `@playwright/test`, the `test` job gets the Playwright steps below. |
| `os_claims` | The OS legs of the `test` job, as "OS legs" says. |
| `monorepo` | The affected-only steps, as "Monorepo tools" says. |

The script names are exactly `lint`, `typecheck`, `test` and `build`. A script with another name (such as `test:unit`) does not count. A script counts when the `scripts` entry of the root package, or of any workspace package in a monorepo, lists it.

### Package manager table

| Manager | Setup step before `Set up Node` | `cache:` | Install | Run a script | Audit | Run a tool |
|---|---|---|---|---|---|---|
| npm | none | `npm` | `npm ci` | `npm run <script>` | `npm audit --audit-level=high` | `npx` |
| pnpm | `Set up pnpm` with `pnpm/action-setup` (no `version:` input, it reads `packageManager`) | `pnpm` | `pnpm install --frozen-lockfile` | `pnpm run <script>` | `pnpm audit --audit-level=high` | `pnpm exec` |
| yarn | none | `yarn` | `yarn install --immutable` | `yarn run <script>` | `yarn npm audit --audit-level=high` | `yarn` |

The lockfile names for the `changes` filter are `package-lock.json`, `pnpm-lock.yaml` and `yarn.lock`. Never cache `node_modules` or the Playwright browsers (COST-05). The two templates use npm. For pnpm, put this step before `Set up Node` in every job that sets up Node:

```yaml
      - name: Set up pnpm
        uses: pnpm/action-setup@73e46992e05b19abd31f2f3c20e0e7370d762115 # v6.1.1
```

### Node versions

- An app uses one version, from `node_version_app`. Raw text such as `20.11.0` or `v22` gives its leading integer major (20, 22), even when that major is not in `supported_node_majors` (the repo's own pin). The text `lts/*`, `lts/<name>` or `node` gives the newest LTS of `supported_node_majors`. A range gives the newest major in `supported_node_majors` that the range allows.
- A published package uses each major in `supported_node_majors` that its `engines` range allows. An `engines` entry with the status `default` counts as the newest LTS only.
- A monorepo uses the union of the majors that the `engines` ranges of its published packages allow (their widest range), and the newest LTS when it has no published package.
- The `test` job lists these in `matrix.node`. The other jobs use the newest major of that list in `node-version`. An app has a matrix with one value.

### OS legs

When the `os_claims` fact lists `darwin` or `win32`, the `test` job gets an `os` matrix key with one pinned label for each claimed value, in the order of the fact. `linux` gives `ubuntu-24.04`, `darwin` gives `macos-15` and `win32` gives `windows-2025`. So `["darwin"]` alone gives only `macos-15`, and any other `os` string is ignored. The job then has `runs-on: ${{ matrix.os }}` and the name `Test (${{ matrix.os }}, node ${{ matrix.node }})`. A fact with only `linux`, or with `linux` and strings that map to nothing (such as `aix` or `!win32`), gets no `os` key. Every other job uses `ubuntu-24.04`.

### Monorepo tools

The monorepo template uses Turborepo. For another tool, change only the two steps of each task in `lint`, `typecheck`, `test` and `build`.

| `monorepo` tool | Step on a PR | Step on a push |
|---|---|---|
| `turbo` | `<run a tool> turbo run <task> --affected` | `<run a tool> turbo run <task>` |
| `nx` | `<run a tool> nx affected -t <task>`, with a step `nrwl/nx-set-shas` before it, pinned as [tools.md](tools.md) says | `<run a tool> nx run-many -t <task>` |
| `pnpm` | `pnpm --filter "...[origin/main]" run <task>` | `pnpm -r run <task>` |
| `workspaces` | none: one step runs every package (a deliberate narrowing of MONO-01: there is no `pnpm-workspace.yaml`, so MONO-02 does not apply). npm: `npm run <task> --workspaces --if-present`. yarn: `yarn workspaces foreach --all run <task>`. pnpm: `pnpm -r run <task>`. | the same step |

`<run a tool>` is the "Run a tool" cell of the package manager table: `npx` for npm (the template default), `pnpm exec` for pnpm and `yarn` for yarn. Every job with an affected-only step keeps `fetch-depth: 0` (and `filter: blob:none` for Turborepo) on its checkout. For the tool `workspaces`, replace the two steps of each task by the one step of the table, and remove `fetch-depth: 0` and `filter: blob:none` from the checkouts (COST-08).

### Playwright steps

Put these two steps after the unit test step of the `test` job. Never cache the browsers, and use one worker (COST-06).

```yaml
      - name: Install Playwright browsers
        run: npx playwright install --with-deps chromium
      - name: Run end-to-end tests
        run: npx playwright test --workers=1
```

Replace `npx` with the "Run a tool" cell of the package manager table.

## Support files

### Dependabot block

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Security audit block

The cron minute is odd. Fill the setup step, the install command, the audit command and the Node version as for `ci.yml`.

```yaml
name: Security audit
on:
  schedule:
    - cron: '17 6 * * 1'
  workflow_dispatch:
permissions:
  contents: read
jobs:
  audit:
    name: Audit
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - name: Check out the repo
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - name: Set up Node
        uses: actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0
        with:
          node-version: 26
          cache: npm
      - name: Install dependencies
        run: npm ci
      - name: Audit dependencies
        run: npm audit --audit-level=high
```
