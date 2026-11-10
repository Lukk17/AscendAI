## Purpose

Keeps a live, two-way copy of an Obsidian vault inside the stack with Obsidian's official headless client, and reports whether that copy is really being kept current.

## ADDED Requirements

### Requirement: The sync container runs the pinned official client for one vault

The stack SHALL provide an `obsidian-sync` container built from the repository's own image definition. The image SHALL install the npm package `obsidian-headless` at one exact pinned version with its integrity hash checked at build time, SHALL run on Node.js 22 or later, and SHALL run as a fixed non-root user. One container SHALL sync exactly one vault, continuously, into a folder on a named volume laid out per tenant and vault. The service SHALL belong to the deployment module `obsidian` of `add-deployment-modules` through the compose profile of that name, and SHALL start only when `obsidian` is in `COMPOSE_PROFILES` in the root `.env`. No documented command SHALL pass `--profile` on the command line. The service SHALL run only on the server host, never on a machine where Obsidian desktop with Sync runs, and development and tests SHALL use a separate test vault or a fake vault folder, never the owner's real vault.

#### Scenario: Container syncs its vault continuously

- **WHEN** the `obsidian-sync` container starts with a valid token and a vault that was set up
- **THEN** it runs the client in continuous mode against the folder `tenants/<tenantId>/<vaultName>/vault` of the vault volume
- **AND** a note changed on another of the owner's devices appears in that folder without any further action

#### Scenario: Default stack does not start it

- **WHEN** the owner runs `docker compose up -d` while `COMPOSE_PROFILES` in `.env` does not hold `obsidian`
- **THEN** the `obsidian-sync` image is not built and the container is not started

#### Scenario: Module switched on in .env

- **WHEN** the owner adds `obsidian` to `COMPOSE_PROFILES` in `.env` and runs `docker compose up -d`
- **THEN** the `obsidian-sync` container starts
- **AND** the agent receives `obsidian` in `ASCEND_MODULES` and registers the note tools

#### Scenario: Image pins the client version

- **WHEN** the image is built
- **THEN** the installed `obsidian-headless` version equals the pinned version exactly
- **AND** the build fails when the downloaded package does not match the locked integrity hash

### Requirement: Secrets come only from the environment

The Obsidian session token SHALL reach the container only through the environment variable `OBSIDIAN_AUTH_TOKEN`, sourced from `.env`. No token, password or encryption password SHALL appear in the image, its build arguments, `compose.yaml` or any repository file. The container SHALL refuse to start, with a message naming the missing item, when the token is missing or the vault has not been set up. The end-to-end encryption password SHALL be entered only interactively during the one-time vault setup, and only the key the client derives from it SHALL be stored, in a state volume that the agent container does not mount.

#### Scenario: Missing token refuses to start

- **WHEN** the container starts without `OBSIDIAN_AUTH_TOKEN`
- **THEN** it exits with a non-zero status and a message naming `OBSIDIAN_AUTH_TOKEN` and the setup document
- **AND** it does not contact Obsidian

#### Scenario: Missing vault setup refuses to start

- **WHEN** the container starts with a token but no vault was set up at its configured path
- **THEN** it exits with a non-zero status and a message naming the setup command

#### Scenario: Agent cannot read the client state

- **WHEN** the mounts of the `ascend-agent` container are inspected
- **THEN** the sync state volume holding the derived encryption key is not among them

### Requirement: One-time login and setup without persisting the token

The container SHALL offer a `login` command that runs the client's interactive login (e-mail, password and two-factor code) in a folder that is not on any volume, prints the resulting token once for the owner to put into `.env`, and leaves nothing on any volume. It SHALL offer a command to list the account's remote vaults and a `setup` command that sets up one named vault at the configured folder, prompting for the end-to-end encryption password when the vault has one. Renewing an expired token SHALL need only the login command, an edit of `.env` and a recreate of the container, and SHALL NOT ask for the encryption password again.

#### Scenario: Login prints a token and keeps nothing

- **WHEN** the owner runs the `login` command and completes the prompts
- **THEN** the token is printed once
- **AND** no file holding the token exists on the vault volume or the state volume afterwards

#### Scenario: Token renewal keeps the vault setup

- **WHEN** the owner runs `login` again, replaces `OBSIDIAN_AUTH_TOKEN` in `.env` and recreates the container
- **THEN** the container syncs the same vault again
- **AND** it does not ask for the encryption password

### Requirement: Sync settings are enforced on every start

On every start, before syncing, the container SHALL apply these client settings: two-way sync mode, the `merge` conflict strategy, attachment types empty unless attachments are enabled for the vault, config syncing limited to the core plugin categories, the excluded folders from its non-secret configuration, and its configured device name.

#### Scenario: A drifted setting is restored

- **WHEN** the conflict strategy in the client state was changed to `conflict` and the container restarts
- **THEN** the client syncs with the `merge` strategy

#### Scenario: Owner-excluded folder is never downloaded

- **WHEN** the container is configured to exclude the folder `Private`
- **THEN** no file of `Private` is written into the vault folder

### Requirement: Health check and sync status file report real connectivity

The container SHALL have a health check that is healthy only while the client process runs and its newest connection state is connected, or not connected for less than a configured grace period (default 300 seconds). Each check SHALL write, atomically, a status file `status/sync-status.json` beside the vault folder holding the state (`connected`, `connecting` or `down`), when that state began, the last time the client was connected, the check time and the client version. An invalid or expired token, a revoked session or an expired subscription SHALL end as state `down` once the grace period has passed.

#### Scenario: Connected client is healthy

- **WHEN** the client reports a successful connection and the check runs
- **THEN** the health check passes
- **AND** the status file says `connected` with the current check time

#### Scenario: Expired token turns the status down

- **WHEN** the token is no longer accepted and the client has not connected for longer than the grace period
- **THEN** the health check fails
- **AND** the status file says `down` with the last connected time

#### Scenario: Short network drop is not a failure

- **WHEN** the client loses its connection and reconnects within the grace period
- **THEN** the health check never fails during that time

### Requirement: The proprietary client is never redistributed

The sync image SHALL be built locally only. It SHALL NOT be pushed to any registry, built by any CI workflow, or included in any published release artifact or installer bundle, because the client's licence is `UNLICENSED`. The documentation SHALL state the licence position, that the client is in open beta, and that a customer builds the image with their own Obsidian account.

#### Scenario: Release artifacts exclude the image

- **WHEN** the release and CI configuration of the repository is inspected
- **THEN** no workflow or release step builds, tags for a registry, or pushes the `obsidian-sync` image
