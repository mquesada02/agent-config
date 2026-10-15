# Docker containers

Docker containers and volumes are durable. They stay on disk after the session ends. `CLAUDE.md` section 13 covers files; this document covers Docker objects.
- Start one-off and test containers with `docker run --rm`.
- Start containers that run browsers or spawn many processes with `--init`.
- When a long-running container is no longer needed, stop and remove it with `docker rm -fv <name>`.
- Stop a test or throwaway `docker compose` stack that you started with `docker compose down -v`. For a long-lived development stack (for example, a local dev database), use `docker compose stop`, or leave it running. Do not use `down` on it: `-v` deletes its data, and without `-v` its volumes lose their containers, so `docker compose ls -a` can no longer find them.
- Before you remove any worktree, run `docker compose ls -a` and remove each stack whose config files are in that worktree with `docker compose -p <NAME> down -v`, where `<NAME>` is the stack name from that list. Compose names the stack after the folder by default, so no later run uses its volumes. If the stack can hold data that the user wants, ask first.
- Before you finish, check with `docker ps -a` and `docker volume ls -f dangling=true` that you left no container or volume behind. Exception: a long-lived development stack that you left running or stopped with `docker compose stop`.
- Remove only the containers and volumes that you created, or that belong to a worktree you remove. Never run any `docker ... prune` command.
