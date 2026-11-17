# Sandboxes with shared, capped resources for agent runs

Research for ticket 772 of map 752. Date of reading: 2026-11-17. Marks: **FACT** = read in a source (named) or a command output. **INFERENCE** = our reading. **UNTESTED** = needs a run that this research did not do (no slice, container or test runner was started). The owner decides; this file makes no decision.

## Question

Can sandboxes with a shared pool of dedicated, capped resources (CPU and memory) replace the rule that caps test runners at 2 workers per agent, keep the owner's PC responsive, and let test runs go parallel inside the pool? Compare open-source agent sandboxes (for example agent-substrate/substrate), a systemd user slice with `CPUQuota` and `MemoryMax` (cgroups v2), and containers. Also state what the audit check S2 needs when a wrapper command is used.

## Short answer

1. A systemd user slice is the best fit. One slice gets one `CPUQuota` and one `MemoryMax`. The kernel enforces both for all processes below it, so many agents and worktrees share one budget. FACT (man `systemd.resource-control`); the "sum of all children" reading is INFERENCE from cgroups v2 (the quota sits on the parent).
2. This PC (8 cores, 30 GB) already delegates the `cpu`, `memory` and `pids` controllers to the user manager. FACT (`cat .../user@1000.service/cgroup.subtree_control` printed `cpu memory pids`). No root step is needed for these three. `cpuset` is not delegated, so `AllowedCPUs=` (core pinning) is not available to a user unit. FACT (same file; the user slice lists `cpu memory pids` only).
3. Docker works too, but its containers run under the root daemon, outside the user slice. A user slice cannot cap them. Only `--cpus` and `--memory` per container, or a system-level parent cgroup (`--cgroup-parent`), can. Each container then needs its own limit or the same parent. FACT (docker 29.9.3, rootful, `docker run --help`); INFERENCE for the placement.
4. agent-substrate/substrate does not fit: it needs a Kubernetes cluster and refuses plain containers. FACT (README). The other projects found cap CPU and memory per sandbox (microsandbox, `--cpus` per sandbox) or not at all (sandbox-runtime). No project found shares one budget across agents on one PC.
5. Replacing the 2-worker rule is possible in principle. A cap protects the PC. The runner's worker count then controls speed inside the cap. INFERENCE. A runner that reads `nproc` sees all 8 cores and starts too many workers inside a small cap. This needs a test. UNTESTED.
6. S2 does not accept a wrapper in front of the declared command. It needs the declared text, with at most a leading `cd <worktree> &&`. FACT (`check_s2`). Three ways out: run the whole agent or terminal inside the slice (command text unchanged), declare the wrapper as the test command, or change S2.
7. Best fit with the S2 rule: put the Orca terminals (or the agent processes) in the slice, not each test command. INFERENCE. Whether Orca can start terminals in a slice is not known. UNTESTED.
8. The CPU cap is a quota, not a guarantee. A quota set below the owner's need leaves the owner's session untouched only when the pool cap is lower than the whole PC. The owner's own work stays outside the slice. INFERENCE.
9. Memory: `MemoryMax` kills processes (OOM killer inside the unit) when usage cannot stay under it. `MemoryHigh` throttles first. A test run can die with no clear message. FACT (man page); the effect on a test run is INFERENCE.
10. Cost: low for a slice (no image, no daemon, no volume to clean). Higher for containers (image, volumes, cleanup rules in docker.md). Highest for Kubernetes-based tools.

## Findings

### F1. Local state of the PC

- FACT: `systemctl --user --version` printed systemd 255 (255.4-1ubuntu8.18), default hierarchy unified (cgroups v2).
- FACT: `cat /sys/fs/cgroup/cgroup.controllers` printed `cpuset cpu io memory hugetlb pids rdma misc dmem`. The user slice file `user-1000.slice/cgroup.controllers` printed `cpu memory pids`. The user manager file `user@1000.service/cgroup.subtree_control` printed `cpu memory pids`.
- FACT: `nproc` printed 8. `free -g` printed 30 GB total.
- FACT: `docker --version` printed 29.9.3. `docker info` printed cgroup driver `systemd`, cgroup version 2, and security options with no `rootless`, so the daemon is rootful. `podman` is not installed.
- FACT: the user manager cgroup has a `cpu.max` file (listing of `user@1000.service/`).

### F2. systemd slice with `CPUQuota` and `MemoryMax`

- FACT (man `systemd.resource-control`): `CPUQuota=` sets `cpu.max` on the unified hierarchy. A value above 100% gives time on more than one CPU. Example: 400% means up to 4 CPUs.
- FACT (same page): `MemoryMax=` is the absolute limit. When usage cannot stay below it, the out-of-memory killer runs inside the unit. The page recommends `MemoryHigh=` as the main control and `MemoryMax=` as the last line of defence. `MemoryHigh=` slows the processes heavily instead of killing them.
- FACT (same page): `TasksMax=` sets `pids.max`, a cap on the number of tasks.
- FACT (same page, example tree): slices form a tree. Controllers are enabled for the parents of a unit that sets a limit. A user manager (`user@1000.service`) has `Delegate=yes`.
- FACT (man `systemd-run`): `--slice=` puts the new unit in the named slice. In `--user` mode the default is the root slice of the user manager. `--wait` waits for the unit to end and prints runtime and exit status. `--pipe` connects stdin, stdout and stderr to the caller. `--collect` unloads the unit after it ends, even after a failure.
- INFERENCE: a limit set on a slice unit applies to the sum of its children (this is how cgroups v2 `cpu.max` and `memory.max` work on a parent). All commands started with the same `--slice=` share one budget, whatever worktree or agent starts them. The slice must have its limits set once (a unit file in `~/.config/systemd/user/`, or `systemctl --user set-property`). `systemd-run` alone cannot set slice properties for a slice that other runs also use. UNTESTED here (no slice was created).
- INFERENCE: limits are kernel-enforced. An agent cannot pass a flag that removes them, but a process of the same user can run `systemd-run --user` without `--slice=` and escape the pool. The cap is hard only for processes that start inside it.
- INFERENCE: start cost is small (a transient unit, one D-Bus call). UNTESTED.
- INFERENCE: fit with git worktrees is complete. The process runs on the host with the host file system. No bind mount and no volume. Orca terminals are normal host terminals.
- INFERENCE: cleanup is automatic. A transient service ends with its command. `--collect` also unloads a failed unit. No volume, no image.
- INFERENCE: how load is shared inside the pool: two quotas never conflict, but 3 test runs each with 8 workers inside a 400% quota each get a part of it. Total speed is capped. The runs may time out. UNTESTED.

### F3. Containers (Docker, rootful)

- FACT (https://docs.docker.com/engine/containers/resource_constraints/): `--cpus` caps CPU use (for example 1.5 of 2 CPUs). `-m/--memory` is the maximum memory. Docker "modifies the settings for the container's cgroup on the host machine". By default the kernel kills processes in a container on OOM.
- FACT (`docker run --help`, local): `--cgroup-parent`, `--cpus`, `--cpuset-cpus`, `--memory` exist. The Docker page above does not describe `--cgroup-parent`.
- INFERENCE: a container of a rootful daemon is placed by the daemon, not under the user's slice. One budget for many containers needs a shared parent cgroup (`--cgroup-parent` with a slice that the daemon can use) or a per-container limit that the agent must pass. A per-container flag is the same weakness as today's `--maxWorkers=2`: the agent passes it. UNTESTED.
- FACT (local `docs/agents/docker.md`): `docker run --rm`, `--init` for browsers, remove with `docker rm -fv`, never `prune`, check `docker ps -a` and `docker volume ls -f dangling=true` before finishing, remove compose stacks before removing a worktree (the cleanup command refuses otherwise).
- FACT (local `CLAUDE.md` section 15 via `docs/agents/cpu-load.md`): burners pin with `taskset -c`, and the code under test with `--cpuset-cpus`. `--cpuset-cpus` is the same pin idea for containers.
- INFERENCE: start cost is higher (image present, bind mount of the worktree, user ID mapping, `node_modules` and caches in volumes). Fit with worktrees is good if the worktree is bind mounted. Files created by the container may belong to root unless the user ID is passed. UNTESTED.
- INFERENCE: a Docker daemon group member has root rights on the PC. A sandbox that talks to this daemon gives the agent more power than the host shell does. This weakens the isolation goal, not the CPU goal.

### F4. agent-substrate/substrate

- FACT (GitHub API, 2026-11-17): Apache-2.0, 7179 stars, created 2026-05-13, last push 2026-11-17, not archived. Releases: v1.0.0 on 2026-11-05 (also rc.2 and rc.3 the days before).
- FACT (README): "Zero-trust sandboxing for millions of agents on Kubernetes." Each actor runs in gVisor (`runsc`) or a Cloud Hypervisor microVM. "Plain Linux containers are not supported." It maps many actors onto a smaller pool of warm worker pods and snapshots idle actors. It "runs on standard Kubernetes". Pools are `WorkerPool` custom resources.
- FACT (README): the project says it is "VERY young" and may not merge outside contributions.
- INFERENCE: the pool idea matches the question (many agents, one pool of workers). The cost does not match one PC with Orca terminals: it needs a Kubernetes cluster, snapshot and restore of agent state, and a pod per worker. CPU and memory caps come from Kubernetes pod limits, which the cluster admin sets. The README does not describe a worktree mount. The docs folder has `get-started`, `guides`, `concepts` and `security`; this research did not read them all. UNTESTED.

### F5. Other open-source projects found

Found with `gh search repos` and by name. Data from the GitHub API on 2026-11-17.

| Project | License | Last push | Latest release | Cap on CPU and memory |
| --- | --- | --- | --- | --- |
| anthropics/sandbox-runtime (`srt`) | Apache-2.0 | 2026-11-13 | v0.0.83 (2026-11-13) | none found |
| superradcompany/microsandbox | Apache-2.0 | 2026-11-17 | v0.7.15 (2026-11-12) | per sandbox (`cpus`, `memory`) |
| schmitthub/clawker | MIT | 2026-11-16 | v2026.11.1 (2026-11-05) | none found in README |
| containers/bubblewrap | not set by API | 2026-10-14 | v0.13.1 (2026-10-14) | none (namespaces only) |
| netblue30/firejail | GPL-2.0 | 2026-11-17 | 0.9.82.2 (2026-11-03) | not checked |
| google/gvisor | Apache-2.0 | 2026-11-17 | not checked | via the host container runtime |
| Docker Sandboxes (`sbx`) | not named | not checked | not checked | "Not covered" on the docs page |

- FACT (sandbox-runtime README): "enforcing filesystem and network restrictions on arbitrary processes at the OS level, without requiring a container". A search of the README for `cpu`, `memory`, `cgroup`, `resource` and `limit` found no CPU or memory option. It limits file and network access, not load. INFERENCE: it can run inside a slice, and the two are independent.
- FACT (microsandbox README): a microVM runtime. Each sandbox is created with `cpus(1)` and `memory(512)` (and in other languages). `msb metrics` shows live CPU and memory. It supports snapshots and forks. INFERENCE: the cap is per sandbox, so a pool budget needs an outer cgroup or a count of sandboxes. Start cost of a microVM was not measured. UNTESTED.
- FACT (clawker README): runs agents in containers, has a `--worktree` flag that creates a git worktree and bind mounts it, and a firewall. A search for CPU and memory found no resource option. Its own worktree folder differs from Orca's (`~/.local/share/clawker/worktrees/`). INFERENCE: it would fight Orca for worktree control.
- FACT (Docker Sandboxes docs page, https://docs.docker.com/ai/sandboxes/): isolated environments for coding agents, "microVM isolation" in the architecture link, `sbx` CLI and local compute "free to use". The page does not cover CPU or memory limits, worktrees or a license. No source repository was found at `docker/sandboxes`.
- GAP: `e2b-dev/E2B`, Firecracker and Apptainer were not read. A Firecracker proof of concept (`tyrchen/firecracker-poc`) appeared in search. They are cloud or microVM tools; the same size of setup as substrate applies. INFERENCE.

### F6. What S2 needs with a wrapper command

- FACT (`hooks/workflow-audit/audit`, `check_s2`, and the ticket 756 file F1): a Bash call counts as a run when the declared text is inside the command and the command, after removing one leading `cd <worktree> &&`, equals the declared text. No other prefix is removed. If there is no `cd` prefix, the row's working directory must be inside the worktree. Every Edit or Write inside the worktree must come before the run. A foreground run needs a non-error result whose last output line is not the failure line of the redact hook. A background run needs a task notice with status `completed` and exit code 0.
- FACT (same): `systemd-run --user --slice=agents.slice --wait --pipe <declared>` fails the equality test (`normalised(call) == declared`), so the run does not count and S2 reports "the declared command did not run".
- FACT (man `systemd-run`): `--wait` shows the exit code and status of the main process. Whether `systemd-run` itself returns that exit code is not in the lines read. UNTESTED: S2 needs a non-zero exit to show as failure (for a foreground run, the redact hook appends its failure line from the exit code of the shell command).
- FACT (man `systemd-run`): `--pipe` inherits stdin, stdout and stderr. A pipe or a redirect inside the declared command is not a problem for this check, but S2 does not accept a pipe around the declared command (ticket 756 file F1).
- INFERENCE, three ways out:
  - W1. Run the terminal or the agent inside the slice. The command text stays the same, so S2 needs no change. The 2-worker rule can go once the runner cap is real. This needs a way to start Orca terminals under a slice. UNTESTED.
  - W2. Declare the wrapper as the test command in the `### Test command` block. S2 then matches the wrapper text. Cost: the block is longer, and every agent must copy it exactly. The cap holds only when the agent uses this exact text. A run of the old unwrapped command would still be honoured by the agent, not by the kernel, so it is not blocked.
  - W3. Change S2 to accept a defined wrapper prefix (like it accepts `cd <worktree> &&`). Cost: a code change and a new test in `hooks/workflow-audit`. It also needs a rule so the prefix cannot hide a changed command.
- INFERENCE: a wrapper script in the repo as the declared command (the "option C" of the ticket 756 file) gives one fixed text, so S2 holds. The script would call `systemd-run`.

### F7. Does a parallel test runner fit in the pool

- FACT (`docs/agents/cpu-load.md`): the current rule caps runners at 2 workers (`--maxWorkers=2`, `--concurrency 2`, `--workers=2`), by command-line flag, and passes no flag when the committed config is lower.
- FACT (ticket 756 file, via `orca-inbox-tests.md`): the declared test command runs many test files in one process (the Python `unittest` command in `.claude/CLAUDE.md`). It is serial by design. See that file (F3) for size and duration.
- INFERENCE: this repo's declared command is a single-process `unittest` run. A pool cap does not make it parallel. Parallel test runs would come from several agents running several suites at once, each in the pool, or from splitting the command (a change in `.claude/CLAUDE.md`, and then S2 sees a new declared text). The 2-worker rule applies to runners like vitest in other repos.
- INFERENCE: a runner inside a quota sees 8 cores (`nproc` and `os.cpus()` ignore `cpu.max`). With `CPUQuota=400%` and 8 workers, each worker gets half a core and the memory use of 8 workers adds up. The user still needs a worker flag, or a runner that reads cgroup limits. UNTESTED.
- INFERENCE: memory is the main risk for parallel runs. `MemoryMax` kills the biggest process, which may be the test runner or an agent. Use `MemoryHigh` below `MemoryMax`.

### F8. Link to ticket 756 and the load file

- FACT (`orca-inbox-tests.md`): S2 never looks at which file changed, a foreground call stops at 600 s, and a docs-only run is not special. A pool does not change these. It makes a slow run no heavier on the PC, but not shorter. INFERENCE.
- FACT: `orca-inbox-load.md` is the load research (not re-read here). This file does not repeat it.

## Options for the owner

### O1. Keep the 2-worker rule (no change)

Cost: none. The limit stays agent-honoured, and each agent passes the flag. A parallel gain stays small.

### O2. One systemd user slice for all agent work, terminals started inside it (W1)

- Gain: kernel-enforced cap (`CPUQuota`, `MemoryHigh`, `MemoryMax`, `TasksMax`), one budget for all agents and worktrees, no image, no cleanup, no S2 change.
- Cost: a one-time unit file in the owner's user config; a way to start Orca and its terminals under the slice (not researched); the owner's own work must stay outside the slice; worker flags may still be needed for runners that read `nproc`. A process that starts itself outside the slice escapes the cap.
- Needs a test before use: a slice, a 2-process load, and `systemd-cgtop`. UNTESTED.

### O3. Wrap each test run with `systemd-run --user --slice=... --wait --pipe`, declared as the test command (W2)

- Gain: no Orca change. The cap holds for the declared run.
- Cost: S2 matches the longer text; each agent must copy it; the first `systemd-run` needs the slice limits already set; other commands (builds, agents) stay uncapped; exit-code behaviour needs a test.

### O4. Wrap with `systemd-run` and change S2 to accept a defined prefix (W3)

- Gain: the declared text stays short.
- Cost: a code change and tests in the audit; a new prefix rule that needs review for evasion.

### O5. Containers with `--cpus` and `--memory` (or a shared `--cgroup-parent`)

- Gain: isolation of files and network as well as load.
- Cost: image and volumes, cleanup rules of `docs/agents/docker.md`, user ID mapping, a root-equivalent daemon, per-container flags (the same weakness as today) unless a shared parent cgroup is set up with root rights. A command wrapper changes the declared text (see F6).

### O6. A Kubernetes-based pool (substrate)

- Gain: the pool model exists, with gVisor or microVM isolation.
- Cost: a Kubernetes cluster on or beside the PC, snapshot and pod concepts, no documented worktree mount, a young project. It solves a larger problem than one PC with a few agents.

### O7. Per-sandbox tools (microsandbox, sandbox-runtime) with an outer slice

- Gain: file and network isolation plus the O2 cap.
- Cost: two tools; microVM start cost not measured; Orca terminal fit not researched. Only worth it if isolation is a goal, which this ticket does not ask for.

INFERENCE on order: O2 first (as a measured trial), with O3 as the fallback if Orca cannot start terminals in a slice. O5 to O7 add cost for isolation that this ticket does not need.

## Gaps and open questions

- Can Orca start its terminals, or the coding agent process, under a systemd slice? Not researched. This decides O2.
- Does `systemd-run --user --wait --pipe` return the exit code of the command? The man page says it shows it. A run is needed. S2 and the redact hook rely on it. UNTESTED.
- Does a quota on a user slice, set through a unit file, work without root on this PC? The delegated controllers say yes. A test is needed. UNTESTED.
- How do the test runners used in other repos (vitest, jest, playwright) pick their worker count inside a quota? Not tested.
- How would `MemoryMax` kills show in the agent and in the audit? Not tested.
- Is a docs-only or a lighter test path wanted? That is ticket 756, not this one.
- Docker Sandboxes (`sbx`), E2B, Firecracker, Apptainer: no primary source read for resource caps.
- Not researched, per option: substrate: cleanup of its sandboxes and volumes, and the fit with Orca terminals. microsandbox: cleanup of its sandboxes, and the fit with git worktrees. sandbox-runtime, bubblewrap, firejail, gVisor: cleanup and the fit with Orca terminals.
- Orca itself may offer a limit on workers or terminals (see `orca-inbox-orca.md` if it exists); not read here.

## Sources read and sources that failed

Read:
- GitHub API: `agent-substrate/substrate` (repo data, releases, README, `docs/concepts/architecture.md`, docs folder list). `anthropics/sandbox-runtime` (repo, latest release, README). `superradcompany/microsandbox` (repo, latest release, README). `schmitthub/clawker` (README, latest release). `containers/bubblewrap`, `netblue30/firejail`, `google/gvisor` (repo data; firejail README search for cgroup, cpu, rlimit found no match in the lines shown).
- `gh search repos` queries: "coding agent sandbox", "sandbox claude code" (the two others returned nothing).
- Man pages on this PC: `systemd.resource-control` (CPUQuota, MemoryMax, MemoryHigh, TasksMax, slice example tree, delegation), `systemd-run` (`--slice`, `--wait`, `--pipe`, `--collect`, `--scope`), `systemd.slice` (header).
- https://docs.docker.com/engine/containers/resource_constraints/ (read through a fetch tool that summarises).
- https://docs.docker.com/ai/sandboxes/ (same tool; the summary says CPU, memory, worktrees and license are not covered).
- Local files: `CLAUDE.md` rules (sections 10, 13, 14, 15 as given in the task), `docs/agents/docker.md`, `docs/agents/cpu-load.md`, `hooks/workflow-audit/audit` (`check_s2`), and the sibling file `orca-inbox-tests.md`.
- Local commands: `systemctl --user --version`, `cat /sys/fs/cgroup/cgroup.controllers`, the user slice and user manager `cgroup.controllers` and `cgroup.subtree_control`, `nproc`, `free -g`, `docker --version`, `docker info --format`, `docker run --help`.

Failed or not read:
- `gh api repos/docker/sandboxes` returned 404 (no such repository).
- The Docker pages above came through a summarising fetch tool, not the raw page; the `--cgroup-parent` text was not in the summary.
- `orca-inbox-load.md` and `orca-inbox-orca.md` were not re-read.
- The `docs` pages of substrate beyond `architecture.md`, the microsandbox docs site and the E2B, Firecracker and Apptainer sources were not read.
- No container, slice, unit or test runner was started. Every UNTESTED mark needs such a run.
