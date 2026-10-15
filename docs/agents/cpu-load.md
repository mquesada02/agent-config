# CPU load

Other sessions and the user share this PC. Parallel test runners and artificial CPU load (busy loops, `stress-ng`, "burners") slow it down, and burners keep running after the session ends.
- Run test runners with at most 2 workers, for example `vitest --maxWorkers=2`, `stryker run --concurrency 2`, `playwright test --workers=2`, `jest --maxWorkers=2`. Pass the limit on the command line; do not change committed config for it. If the committed config already sets a lower limit (such as `workers: 1`, `maxWorkers: 1`, or `fileParallelism: false`), pass no worker flag and no `VITEST_*` variable: they override the config and can make a serial suite run in parallel.
- Use at most half of the cores for burners: start at most `nproc / 2` burners, one per core, pinned with `taskset -c` to cores `0` to `nproc / 2 - 1`. Pin the code under test to the same cores: a host process with `taskset -c`, a container with `--cpuset-cpus`. The other cores stay free.
- Wrap each burner in `timeout` of at most 30 minutes. Start new burners if you need more time. A short timeout stops orphaned burners if your session dies.
- Write the PIDs that you start to a file in your scratchpad: each Bash call starts a new shell, so `$!` is lost. Before you finish, kill only the PIDs whose command (`ps -o args= -p <PID>`) is still your burner. Then check again the same way that none of them is still your burner. Do not use `pgrep -f` for this check: it also matches the shell that runs it.
- If the problem does not reproduce at this load, ask the user. Never raise the load by yourself.
