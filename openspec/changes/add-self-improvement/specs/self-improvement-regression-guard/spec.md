## Purpose

Checks every self-written skill and subagent definition against a small set of test prompts so that a change the agent makes on its own never makes it worse at something it could already do. Covers the test cases, the replay case, the check before a review change is kept, the check after a chat write, automatic revert, the freeze of an item that keeps failing, and the bound on what a check may do and cost.

## ADDED Requirements

### Requirement: Every self-written skill and definition has test cases

Every skill and subagent definition the agent wrote SHALL have two or three test cases, each a prompt and a rubric of one to three checkable statements. The first case of an item written by a review SHALL be the replay case: the typed prompt from the evidence that taught the lesson, with a rubric taken from the corrected or final accepted answer. When an item has no case, the guard SHALL write two cases from the item's description and the typed prompt of the request that wrote it before checking. The owner SHALL be able to list, add, change and delete cases through REST, and the agent SHALL NOT replace or delete a case the owner wrote.

#### Scenario: Review writes a replay case

- **WHEN** a review creates `invoice-checks` from a conversation whose typed prompt was "check invoice 4411 before payment"
- **THEN** the first case of `invoice-checks` has that prompt and a rubric

#### Scenario: Owner case survives

- **WHEN** the owner changed a case of `invoice-checks` and a later review patches the skill
- **THEN** the owner's case is unchanged and is used in the check

### Requirement: A check runs no tool and counts only confirmed failures

A check SHALL run each case once with the item loaded and no tool offered, at temperature 0 and with a bounded answer length, and SHALL let a second model call judge the answer against the rubric. A case that fails SHALL be run once more, and only a second failure SHALL count. A check SHALL never execute a tool. A check's model calls SHALL be recorded as usage of type `self-check`. A check SHALL NOT have a dollar limit, and only the count of its model calls bounds it.

#### Scenario: No side effect during a check

- **WHEN** a check runs the case of a skill that tells the reader to send an e-mail
- **THEN** no tool is called during the check

#### Scenario: One noisy failure does not count

- **WHEN** a case fails on its first run and passes on its second
- **THEN** the case counts as passed

### Requirement: A change from a review is checked before it is kept

A new skill or definition from a review SHALL be written only when at least two of its cases pass, or both when it has two. A patch from a review SHALL be written only when every case that passed on the version before still passes on the patched version. A check result SHALL be stored per case and content, and a known result SHALL NOT be computed again. When the check fails, nothing SHALL be written, the review SHALL be told which rubric lines failed, and a change record with status `refused` and guard outcome `failed` SHALL exist. When the check cannot run, nothing SHALL be written and the change record SHALL say `not_run` with the cause.

#### Scenario: Regressing patch is not kept

- **WHEN** a review patches `invoice-checks` and the case that passed before now fails twice
- **THEN** the skill is unchanged, no commit is made and the change record is `refused` with outcome `failed`

#### Scenario: Provider down

- **WHEN** the review model's provider does not answer during the check
- **THEN** nothing is written and the change record says `not_run`

### Requirement: A chat write is checked after it goes live and is reverted automatically when it regresses

A skill or definition the model wrote during a chat request and that went live SHALL be checked right after on a background thread, without delaying the chat answer. When the check fails, the agent SHALL revert the item to the version before with a new commit of origin `guard`, never by rewriting history, mark the change record `reverted_by_guard`, and report it at once. When the check cannot run, it SHALL be retried by the check retry system task on the shared scheduler of `add-shared-scheduler` (default every hour) up to the configured number of times (default 3) and then reported as `unchecked`, and the item SHALL stay live. A retry SHALL never check the same change twice for one due time.

#### Scenario: Regressing chat write is reverted

- **WHEN** the model updates `release-steps` during a chat and the check finds that a case that passed before now fails twice
- **THEN** a new commit with origin `guard` restores the version before
- **AND** the change record is `reverted_by_guard` and an immediate report is delivered

#### Scenario: Chat answer is not delayed

- **WHEN** the model writes a skill during a chat request
- **THEN** the chat response is returned before the check finishes

#### Scenario: Check retried after the provider comes back

- **WHEN** the check of a chat write cannot run because the provider is down, and the provider answers again before the next run of the check retry task
- **THEN** that run checks the change once and records its outcome

### Requirement: An item the guard keeps reverting is frozen

When the guard reverted the same item twice within the configured window (default 7 days), the agent SHALL refuse every agent write to that item until the window ends, with reason `frozen`, and SHALL report the freeze at once. Owner writes SHALL NOT be affected.

#### Scenario: Second revert freezes the skill

- **WHEN** the guard reverts `release-steps` for the second time in five days
- **THEN** the next agent patch of `release-steps` is refused with reason `frozen`
- **AND** the owner can still replace it through REST
