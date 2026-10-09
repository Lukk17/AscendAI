## Purpose

Provides the pending approvals screen where the owner sees and decides every approval that waits for him, from any conversation, background run or scheduled job, using the approval endpoints of `add-action-approvals`.

## ADDED Requirements

### Requirement: Pending approvals screen lists every waiting approval
The app SHALL offer a pending approvals screen reachable from the conversation list, filled from `GET /api/v1/approvals?state=pending`. Each item SHALL use the approval card of the core chat spec, with the kind, preview, exact arguments, expiry time, Approve, Deny and the "Remember this choice" switch when `rememberable` is true, and SHALL decide through the same calls with `channel` `app`. Approvals of every kind SHALL be shown through their preview, including staged self-improvement changes (kind `self_change`), coding publish and cleanup approvals and credential approvals, with no code specific to a kind. A decided approval SHALL leave the list. The list SHALL be read when the app starts, when it returns to the foreground, on pull to refresh, after every `approval_required`, `run_started` or `subagent_status` stream event, and at the refresh interval while the app is in the foreground.

#### Scenario: Approval from a background run
- **WHEN** a background run waits for approval and the owner opens the app
- **THEN** the pending approvals screen SHALL list that approval with its preview and its expiry time

#### Scenario: Deciding removes it from the list
- **WHEN** the owner approves an item on the pending approvals screen and the agent answers success
- **THEN** the item SHALL leave the list and the badge count SHALL drop by one

#### Scenario: Empty list
- **WHEN** no approval is pending
- **THEN** the screen SHALL show an empty state that says nothing waits for a decision

### Requirement: Pending approvals badge
The conversation list app bar SHALL show a badge with the number of pending approvals on the first page of `GET /api/v1/approvals?state=pending`, with a plus sign when the page says more exist, and no badge when none is pending.

#### Scenario: Badge after a new approval
- **WHEN** a chat stream sends an `approval_required` event
- **THEN** the pending approvals list SHALL be read again and the badge SHALL include the new approval
