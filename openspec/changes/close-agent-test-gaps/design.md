## Context

The four gaps were found on 2026-10-01 while checking that every agent test ends with a real assertion. All four are in the unit test suite of `apps/ascend-agent` and need no Docker. The production code under test is `config/StartupLogConfig.java` (the readiness banner and its AscendMemory probe), the vector store start-up in `AppConfig`, and `ChatModelResolver.buildRequestFactory(Long, boolean)`, which is private and builds a `JdkClientHttpRequestFactory` over a `java.net.http.HttpClient` with a connect timeout, an optional `HTTP_1_1` version and a read timeout.

## Goals / Non-Goals

Goals:

- Each test reaches the branch its name describes and asserts the result a user or operator would see.
- No new test dependency.

Non-Goals:

- No production code change. A defect a test exposes is reported to the owner first.
- No coverage work outside these four gaps.

## Decisions

### D1: A local JDK `HttpServer` for every network test

`com.sun.net.httpserver.HttpServer` ships with the JDK, binds to `127.0.0.1` on port 0 (a free port chosen by the system), and lets a handler record the request and choose the answer and its timing. It is started in the test's `// given` step and stopped in an `@AfterEach`, so each test is isolated and repeatable. WireMock was considered and rejected because it is a new dependency for four tests.

### D2: AscendMemory non-200 branch

The fake server answers `500` on the probe path. The test asserts the banner line for AscendMemory carries the status the non-200 branch writes (read from `StartupLogConfig` at implementation time, not guessed here) and not the connection refused text. The existing test keeps its body and is renamed `onReadinessChange_AscendMemoryConnectionRefused_LogsFailed`, with its misleading comments removed, so the name matches what it checks.

### D3: Interrupted vector store start-up

The test stubs the list call with a `ListenableFuture` whose `get()` throws `InterruptedException` directly (a small anonymous subclass of Guava's `AbstractFuture` or a Mockito mock of `ListenableFuture`). After the call the test asserts `Thread.currentThread().isInterrupted()` is true, then clears the flag with `Thread.interrupted()` in the `// then` step so later tests on the same thread are not affected. It also asserts that no collection was created.

### D4: SSL banner port

The `anyString()` stub on the port property is replaced by a stub on the exact property name and default value the code passes, returning `9917`. The test asserts both banner lines contain `https://localhost:9917`.

### D5: Request factory behaviour without reading internals

`buildRequestFactory` is private, so the tests drive it through `ChatModelResolver.initializeProviders()` with a provider whose `baseUrl` points at the local fake server, and make one call through the resolved chat model:

- HTTP/1.1: with `requiresHttp1 = true`, the handler records `HttpExchange.getProtocol()` and answers a minimal valid chat completion body. The test asserts the recorded protocol is `HTTP/1.1`. The JDK `HttpServer` speaks only HTTP/1.1, so the test also asserts the call succeeds, which proves the client did not insist on HTTP/2.
- Timeout: with `timeoutSeconds = 1`, the handler waits 3 seconds before answering. The test asserts the call fails with an exception whose cause chain holds a `java.net.http.HttpTimeoutException`, and that it fails in under 3 seconds.
- Null timeout: with `timeoutSeconds = null`, a server that answers at once must still get a successful call, which proves the null value falls back to `DEFAULT_READ_TIMEOUT_SECONDS` instead of failing. The default itself is long, so the test does not wait for it.

## Risks / Trade-offs

- [A timing test can be flaky on a busy machine] → the margin is 2 seconds above a 1-second timeout, and the assertion is only that the call fails with a timeout before the server answers.
- [The chat model may retry a failed call] → the provider is built with retries off for the test, or the test counts the requests the handler received and asserts the timeout on the first one.

## Open Questions

(none)
