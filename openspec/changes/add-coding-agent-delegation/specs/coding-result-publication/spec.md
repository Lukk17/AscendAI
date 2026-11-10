## Purpose

Publishes the work of a coding project to the remote repository as a new branch, later fast-forwarded, and optionally a pull request, only after the owner approves exactly that action, and makes sure nothing ever reaches the default branch and nothing is ever merged.

## ADDED Requirements

### Requirement: Publishing is requested, never done on its own

The agent SHALL offer a tool named `coding_publish` to the main chat with the input `project_id`, `open_pull_request` (boolean), and, when a pull request is asked for, `pull_request_title` (1 to 200 characters) and an optional `pull_request_body` (at most 20000 characters). `POST /api/v1/coding-projects/{id}/publish` SHALL take the same fields. Both SHALL only submit one approval of kind `coding_push` to the approval service and SHALL answer with its approval id. Neither SHALL push or open a pull request before that approval is approved. A request SHALL be refused when the project has no repository, because it is a new project or a project of source `seed` (`coding_not_publishable`), is `in_progress`, `deleting` or `deleted` (`coding_project_busy`), has nothing that is not pushed (`coding_nothing_to_publish`), is of another tenant (404 on the endpoint), or already has a pending publish approval (`coding_publish_pending`).

#### Scenario: Request a push

- **WHEN** the model calls `coding_publish` for a `done` project with two commits not pushed and `open_pull_request` false
- **THEN** the tool result holds an approval id and says that nothing was pushed yet
- **AND** the remote repository has no new branch

#### Scenario: Second request while one is pending

- **WHEN** a publish of the same project is requested again while the first approval is pending
- **THEN** the answer names the existing approval id and no second approval is created

#### Scenario: Nothing to publish

- **WHEN** a publish is requested for a project in state `pushed`
- **THEN** it is refused with code `coding_nothing_to_publish`

#### Scenario: A new project cannot be published

- **WHEN** a publish is requested for a `done` project made with `new_project`
- **THEN** it is refused with code `coding_not_publishable`, the same code a project of source `seed` gets

### Requirement: The owner sees exactly what will be published

The approval of kind `coding_push` SHALL carry, in its stored action and its preview: the repository, the base branch, the work branch, the head commit that will be pushed, the commit already on the remote branch when there is one, the list of commits since then with their messages, the diff statistics, the first part of the diff up to the configured preview size, and, when asked, the pull request title, body, base and head. The category SHALL be `code_publish`, which can never be remembered as an allow. The stored action SHALL NOT change after it is created.

#### Scenario: Preview of a push with a pull request

- **WHEN** the owner reads the approval of a publish that asked for a pull request
- **THEN** its preview shows the repository, the work branch, each commit message, the diff statistics, the start of the diff and the pull request title

#### Scenario: Remember is not offered

- **WHEN** the owner approves a `coding_push` approval with `remember: true`
- **THEN** the answer is 400 with code `approval_not_rememberable` and the approval stays pending

### Requirement: An approved publish pushes the project's work branch and nothing else

After approval, the agent SHALL push the approved head commit of the project's work branch, whose name the server made under the configured branch prefix with the project id. The first publish SHALL create that branch on the remote. A later publish SHALL only fast-forward it from the commit the previous publish pushed. The push SHALL be refused, and nothing pushed, when the work branch equals the repository's default branch (`branch_is_default`), when the local branch head differs from the approved head (`branch_changed`), when the project changed since the approval (`project_changed`), or when the remote branch exists on a first publish or holds another commit than the one last pushed on a later publish (`branch_moved`). The push SHALL never be forced and SHALL never update any other reference. When the approval asked for a pull request and none is open for the project, the agent SHALL open exactly one pull request from the work branch to the base branch with the approved title and body, only after the push succeeded. No code path of the agent SHALL merge a pull request, push to the default branch, delete a branch, or change repository settings. The publish SHALL run at most once per approval, and its outcome (`pushed`, `pull_request_opened` with its URL, or `failed` with a reason) SHALL be stored on the project and returned as the approval's execution result. A successful push SHALL move the project to `pushed`.

#### Scenario: Approved first push

- **WHEN** the owner approves the first publish of project `p1` without a pull request
- **THEN** the remote has one new branch named with the configured prefix and the project id, holding the project's commits on top of the base commit
- **AND** the default branch of the remote is unchanged
- **AND** the project is `pushed`

#### Scenario: Later publish fast-forwards

- **WHEN** a follow-up run adds one commit to a pushed project and the owner approves its publish
- **THEN** the remote work branch moves forward by that commit without a force push

#### Scenario: Remote branch moved

- **WHEN** someone pushed another commit to the remote work branch after the last publish and a new publish runs
- **THEN** nothing is pushed and the execution result is `failed` with reason `branch_moved`

#### Scenario: Approved pull request

- **WHEN** the owner approves a publish that asked for a pull request
- **THEN** after the push one pull request is open from the work branch to the base branch with the approved title
- **AND** the pull request is not merged

#### Scenario: Denied publish

- **WHEN** the owner denies a publish or the approval expires
- **THEN** nothing is pushed and no pull request is opened

### Requirement: The publish step uses its own short-lived credentials and its own workspace

The push SHALL run in a new short-lived sandbox workspace that mounts the project's folder, with no network except its own credential gateway, which reaches only the project's repository on the git host. The git token used SHALL be minted for that one step, limited to the one repository with write access to its contents and nothing else, and SHALL NOT be stored. The pull request SHALL be opened with a separate token limited to the one repository with write access to pull requests and nothing else. A coding run's workspace SHALL never hold a token with write access. The publish workspace SHALL be destroyed when the publish ends in any outcome, and the project folder SHALL be kept.

#### Scenario: The coding run never had write access

- **WHEN** OpenCode tries to push to the repository during a run
- **THEN** the push is refused because the run's gateway refuses `git-receive-pack` and the run's token is read only

#### Scenario: Publish workspace is removed

- **WHEN** an approved publish ends
- **THEN** no workspace of that publish exists any more
- **AND** the project folder still exists
