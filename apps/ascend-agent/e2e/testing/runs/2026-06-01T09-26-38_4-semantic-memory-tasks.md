# Semantic memory: run tasks template

Spec: [4-semantic-memory-test.md](4-semantic-memory-test.md)

Copy this file to `runs/<UTC-timestamp>_4-semantic-memory-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] AscendMemory `/health` returns HTTP 200 with `{"status":"ok"}`
- [x] Qdrant `/healthz` returns HTTP 200
- [x] Redis responds to `PING` with `PONG`
- [x] Postgres responds to `SELECT 1` with a row

### Reset state

- [ ] Cleared Redis `chat:frostySemanticMemoryTest` key
- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostySemanticMemoryTest'`
- [ ] Wiped Qdrant `ascend_memory_*` points where `user_id = 'frostySemanticMemoryTest'`

### Run

- [ ] Step 1: sent `memory-test-save.yml` and waited for HTTP 200
- [ ] Step 2: re-cleared Redis `chat:frostySemanticMemoryTest` and Postgres `chat_history` for frostySemanticMemoryTest
- [ ] Step 3: sent `memory-test-retrieve.yml` and waited for HTTP 200

### Expected

- [ ] After step 1: HTTP 200
- [ ] After step 1: Qdrant scroll filtered by `user_id=frostySemanticMemoryTest` returns ≥ 1 point
- [ ] After step 1: at least one Qdrant point's payload contains both `Luke` and `software engineer`
- [ ] After step 3: HTTP 200
- [ ] After step 3: Response `content` contains `Luke`
- [ ] After step 3: Response `content` contains `software engineer`
- [ ] After step 3: Response `content` is NOT a refusal like "I don't know your name"

### Verdict

- [ ] Verdict: FAIL

## Result summary

BLOCKED on prerequisite: AscendMemory container (`ascend-memory`) is in a restart loop (exit code 1, restart count 12+) and never becomes reachable on port 7020. The container crashes during Python module import with `PermissionError: [Errno 13] Permission denied: '/app/.mem0'`. mem0 2.0.4 unconditionally calls `os.makedirs('/app/.mem0', exist_ok=True)` during import (`mem0/memory/setup.py`), but `/app` is owned by root and not writable by the `ascend` container user. Because AscendMemory never starts, all three Run steps and all Expected assertions could not be executed. The other five prerequisites (Bruno 3.4.0, AscendAgent UP, Qdrant UP, Redis PONG, Postgres row) all passed.

Input tokens:

Output tokens:

Start (UTC): 2026-06-01T09:26:38Z

End (UTC): 2026-06-01T09:31:15Z

Duration: 00:04:37

---

## Additional tasks I did

- Ran `docker ps --filter name=ascend-memory` to confirm container status: `Restarting (1) 15 seconds ago`.
- Ran `docker logs ascend-memory --tail 50` to capture the crash traceback: `PermissionError: [Errno 13] Permission denied: '/app/.mem0'` in `mem0/memory/setup.py line 11 os.makedirs(mem0_dir, exist_ok=True)`.
- Ran `docker inspect ascend-memory` to confirm container user (`ascend`) and working dir (`/app`); restart count was 12.
- Root cause: mem0 2.0.4 creates `~/.mem0` (resolved as `/app/.mem0` because HOME is not set and CWD is `/app`) at import time. The Dockerfile sets `USER ascend` but does not `chown /app` or set `HOME` to a writable path, so the directory creation fails. Fix: add `ENV HOME=/tmp` (or `RUN chown ascend /app`) to the AscendMemory Dockerfile, then rebuild the image.
