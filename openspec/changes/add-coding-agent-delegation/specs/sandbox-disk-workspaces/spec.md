## Purpose

Gives coding runs disk-backed workspaces on one shared coding project area, where every project has its own folder that survives its runs, many projects share the space, each workspace sees exactly one project, every project's state is tracked, and no project folder is ever deleted without the owner's approval.

## ADDED Requirements

### Requirement: Coding projects live in their own folders on one shared area

The runner SHALL keep one coding project area, a named volume that in production is bound to a configured host folder. Each coding project SHALL have one folder in it at `tenants/<tenantId>/projects/<projectId>/`, created by the runner before the project's first workspace, owned by the workspace user. The runner SHALL build that path only from a validated tenant id and a validated project id, never from a free path. A project folder SHALL be kept after each run and each publish of the project, so a later run continues on the same files. The runner SHALL refuse to start under the `production` profile when the area is not bound to a configured host folder. Outside the `production` profile the area MAY be a plain named volume, and the runner SHALL then log one WARN line at startup stating that the area has no host folder of its own and is for development only, and SHALL report the area mode in its readiness answer.

#### Scenario: Project folder survives the run

- **WHEN** a coding run of a project writes `repo/notes.md`, ends, and a second run of the same project starts
- **THEN** the second run's workspace finds `repo/notes.md`

#### Scenario: Production refuses the development area

- **WHEN** the runner starts under the `production` profile with the area in development mode
- **THEN** the runner does not start and its log names the setting

### Requirement: A workspace sees exactly one project

A coding workspace SHALL mount exactly one project folder of the area at `/workspace`, as a subfolder mount of the area volume, and no other host path, socket or device. The mount SHALL be built so that no symbolic link inside the area can lead it out of that project folder. At most one workspace SHALL mount a project folder at a time, and a second create for the same project SHALL be answered 409 with code `project_busy`. Every other isolation, limit, network and cleanup rule of the runner SHALL hold for a coding workspace as for any workspace. Area operations (create a folder, measure, delete) SHALL run in short-lived helper containers that have no network and no capability, run no project code, and mount only the area.

#### Scenario: Another project is not visible

- **WHEN** a command in the workspace of project `p1` lists `/workspace/..` and searches every path it can reach for a file that only project `p2` holds
- **THEN** the file is not found

#### Scenario: A link does not escape

- **WHEN** a command in the workspace of project `p1` creates a symbolic link `repo/escape` pointing at `../../p2` and at `/`, and reads through it
- **THEN** it reads only paths inside the workspace container's own view, never a file of `p2` or of the host

#### Scenario: Second workspace for the same project

- **WHEN** a workspace of project `p1` exists and a client creates another workspace for `p1`
- **THEN** the answer is 409 with code `project_busy`

### Requirement: Every project's state is tracked

The agent SHALL keep, for every coding project, its tenant, its repository or new project name, its work branch, the head commit of its work branch, the commit last pushed, its last measured size, its last activity and its state: `in_progress` while a run, a publish or a cleanup of it is active, `done` when no run is active and its work branch holds commits the remote does not have, `pushed` when no run is active and every commit of its work branch is on the remote, `deleting` while an approved cleanup removes it, and `deleted` after. A run SHALL commit every leftover change when it ends, so the state follows from the head commit and the commit last pushed alone. A new project, which has no remote, SHALL never be `pushed`. Only one run, publish or cleanup SHALL hold a project at a time, and a second one SHALL be refused with `coding_project_busy`. After a restart, a project left `in_progress` with nothing active SHALL be set from its commits, and a project left `deleting` SHALL stay `deleting` until the owner decides.

#### Scenario: State after a run and a publish

- **WHEN** a run of a repository project adds a commit and ends, and then the owner approves its publish
- **THEN** the project is `done` after the run and `pushed` after the publish

#### Scenario: A new project is never pushed

- **WHEN** a run of a new project ends with commits
- **THEN** the project is `done`

### Requirement: Free space is checked and the owner is asked before any cleanup

A system task of the shared scheduler SHALL check the free space of the coding project area at a configured interval. When the free share is below the configured warning level (10 percent by default), it SHALL log one WARN line, measure every project's size, and, when no cleanup approval is pending and at least one project is `pushed`, submit one approval of kind `coding_project_cleanup` that proposes `pushed` projects, oldest last activity first, enough to reach the configured target free share. That approval SHALL have source `system` and no user, no conversation and no run, because a timed job starts it, SHALL be decided by the tenant administrator as any other approval, and its stored action SHALL hold the exact list of proposed projects. It SHALL tell the owner through that approval, through one owner notification of source `coding_area` and kind `cleanup` whose only subject id is the approval's id, and through one owner notification of source `coding_area` and kind `low_space` with no subject id, at most once per configured interval while space stays low, which names projects only in its text. The task SHALL be safe to run more than once. Nothing SHALL delete a project folder on its own: no age, size or state rule, no run, no publish and no restart. The owner SHALL also be able to ask for a cleanup of projects he names, through the tool `coding_project_cleanup` or `POST /api/v1/coding-projects/cleanup`, which submits one approval for exactly those projects. A project that is `in_progress` or `deleting` SHALL be refused from any cleanup list with `coding_cleanup_not_allowed`. A `done` project SHALL be cleaned only when the owner named it himself, and the approval's preview SHALL state that its work is not pushed and will be lost. The category SHALL be `workspace_cleanup`, which can never be remembered as an allow.

#### Scenario: Low space asks the owner

- **WHEN** the area has 8 percent free space and the tenant has two `pushed` projects and one `done` project
- **THEN** one `coding_project_cleanup` approval is pending that proposes `pushed` projects only
- **AND** that approval has source `system` and no user, conversation or run
- **AND** one `cleanup` notification names that approval as its only subject id, and one `low_space` notification has no subject id
- **AND** no project folder was deleted

#### Scenario: The check runs again

- **WHEN** the free space check runs again while that approval is still pending
- **THEN** no second approval is created

#### Scenario: Denied cleanup

- **WHEN** the owner denies the cleanup approval or it expires
- **THEN** every project folder still exists

#### Scenario: Unpushed project needs the owner's own choice

- **WHEN** the owner asks to clean a `done` project by its id
- **THEN** the approval's preview says that the project's work is not pushed and will be lost, with the number of commits not pushed

#### Scenario: A project in progress cannot be cleaned

- **WHEN** a cleanup is requested for a project whose run is `running`
- **THEN** the request is refused with code `coding_cleanup_not_allowed`

### Requirement: An approved cleanup deletes only what the owner approved, as it was

When a `coding_project_cleanup` approval is approved, the agent SHALL, for each listed project, check that its state and version are the ones the approval holds, skip it with reason `project_changed` when they are not, and otherwise move it to `deleting`, remove its folder through the runner, and move it to `deleted`. A removal that fails SHALL leave the project `deleting` with reason `cleanup_failed` and SHALL NOT be retried on its own. The execution SHALL run at most once per approval, and its result SHALL list the deleted, skipped and failed projects and the free share after it. A project's rows and stored run results SHALL be kept after its folder is deleted until their own retention.

#### Scenario: Approved cleanup

- **WHEN** the owner approves a cleanup of two `pushed` projects
- **THEN** both folders are gone, both projects are `deleted`, and the execution result names both

#### Scenario: Project changed after the approval

- **WHEN** a new run of a listed project started between the approval request and the approval
- **THEN** that project is skipped with reason `project_changed` and its folder still exists

### Requirement: Runs stop before the area is full

Every poll of a running coding run SHALL read the free space of the area. When it is below the configured stop level (5 percent by default), the agent SHALL stop OpenCode, collect what was committed, and end the run `failed` with reason `DISK_LOW`. A new coding run SHALL be refused with reason `disk_low` below the same level.

#### Scenario: Area fills during a run

- **WHEN** a test OpenCode binary writes until the area's free share is below the stop level
- **THEN** the run ends `failed` with reason `DISK_LOW` and its workspace is destroyed
- **AND** its project folder still exists
