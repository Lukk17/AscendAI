## Purpose

Signs the user in with a Keycloak account of the realm `ascend-ai` through the public client `ascend-flutter`, using the authorization code flow with PKCE on every platform, and sends the access token as a bearer token on every request to the agent. Owner decision 65.2 of 2026-10-04.

## ADDED Requirements

### Requirement: Sign-in uses the authorization code flow with PKCE
The app SHALL sign the user in through the authorization code flow with PKCE method `S256` against the issuer `ASCEND_AUTH_ISSUER` and the client `ASCEND_AUTH_CLIENT_ID` (default `ascend-flutter`), with a random `state` per sign-in that is checked on return. The app SHALL NOT ask for the password itself, SHALL NOT use a password grant and SHALL NOT hold a client secret.

#### Scenario: Password typed only on the Keycloak page
- **WHEN** a signed-out user opens the app and taps "Sign in"
- **THEN** the app opens the Keycloak login page of the realm with `code_challenge_method=S256` and a `state` value
- **AND** no screen of the app has a password field

#### Scenario: Wrong state is refused
- **WHEN** the redirect comes back with a `state` that differs from the one the app sent
- **THEN** the app does not exchange the code and shows a sign-in error

### Requirement: Each platform uses its own redirect address
The app SHALL use `http://127.0.0.1:<port>/callback` on Windows, macOS and Linux, where `<port>` is a random free port of a one-time listener bound to `127.0.0.1`, `com.lukk.ascend:/callback` on Android and iOS, and the exact hosting address of the web build followed by `/callback` on web.

#### Scenario: Desktop login through a random local port
- **WHEN** a user signs in on desktop
- **THEN** the app binds a listener on `127.0.0.1` with port 0, sends the redirect address with the port the system chose, receives the code on `/callback`, closes the listener and exchanges the code for tokens

#### Scenario: Mobile login through the app scheme
- **WHEN** a user signs in on Android or iOS
- **THEN** the redirect address is `com.lukk.ascend:/callback` and the code arrives back in the app

#### Scenario: Web login on the hosting address
- **WHEN** a user signs in on the web build hosted at `https://chat.example.com`
- **THEN** the redirect address is `https://chat.example.com/callback` and the `/callback` route finishes the exchange

### Requirement: Every request carries the bearer token
After sign-in the app SHALL send `Authorization: Bearer <access token>` on every REST call and every stream to the agent, and SHALL NOT send `X-User-Id`. It SHALL refresh an access token that expires within `ASCEND_TOKEN_REFRESH_MARGIN_SECONDS` seconds (a build-time setting, default 30) before a request. On a 401 it SHALL refresh once and retry once, and when the refresh fails or the retry answers 401 it SHALL show the sign-in screen.

#### Scenario: Bearer token on a stream
- **WHEN** a signed-in user sends a prompt
- **THEN** the `POST /api/v1/ai/prompt/stream` request carries `Authorization: Bearer` and no `X-User-Id` header

#### Scenario: Expired session goes back to sign-in
- **WHEN** a request answers 401 and the refresh is refused by Keycloak
- **THEN** the app shows the sign-in screen and keeps no token

### Requirement: Tokens are stored safely and sign out clears them
On Android, iOS and desktop the app SHALL keep the refresh token only in the platform secure storage. On web the app SHALL keep tokens in memory only and write none to browser storage. Sign out SHALL call the realm's end session endpoint and clear every stored token.

#### Scenario: Sign out clears the tokens
- **WHEN** the user signs out
- **THEN** the secure storage holds no token and the next request needs a new sign-in

#### Scenario: Web build keeps no token in storage
- **WHEN** a user is signed in on the web build
- **THEN** `localStorage` and `sessionStorage` hold no access or refresh token
