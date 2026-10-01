## Why

A review of the ascend-ai-agent tests on 2026-10-01 found four tests that pass without proving what their names say. Each one stops short of the branch it is named after, so a defect in that branch would ship with a green build:

- `StartupLogConfigTest.onReadinessChange_AscendMemoryNon200_LogsWarning` only reaches the connection refused path. Its own comments say the non-200 branch needs a live server, and its assertion checks `[FAILED]`, which is the connection refused outcome.
- `AppConfigVectorStoreInitTest.initVectorStore_ListCollectionsInterrupted_HandledGracefully` never reaches the `InterruptedException` branch. `Futures.immediateFailedFuture(new InterruptedException(...))` makes `get()` throw `ExecutionException` with the interruption as its cause, so the test runs the execution failure branch a second time.
- `StartupLogConfigTest.onReadinessChange_SslConfigured_UsesHttps` asserts only the `https://localhost:` prefix. An `anyString()` stub leaves the server port null, so the test cannot check the full address a user would copy.
- `ChatModelResolverProviderRegistrationTest.buildRequestFactory_Http1Required_CreatesHttp1Factory` and `buildRequestFactory_NullTimeoutSeconds_UsesDefaultTimeout` only check the type of the returned chat model. Neither proves that the HTTP/1.1 setting or the read timeout reaches the wire.

## What Changes

- Add a real test of the AscendMemory non-200 branch against a local fake HTTP server built on the JDK `com.sun.net.httpserver.HttpServer` (no new dependency), and rename the existing test so its name says it covers connection refused.
- Rewrite the interrupted test with a future whose `get()` throws `InterruptedException` itself, and assert the thread's interrupt flag is restored.
- Narrow the SSL banner test's port stub so the port resolves, and assert the full address with the port.
- Replace the two type-only request factory tests with behaviour tests against a local `HttpServer`: one records the protocol version of the request and expects `HTTP/1.1`, one delays longer than the configured timeout and expects a timeout. No test reads private Spring or JDK internals.
- Every test marks `// given`, `// when`, `// then` and ends with a real assertion.
- No production code changes. If a test exposes a real defect, the defect is reported to the owner before any production change.

Build order: this change runs right after group A (owner, 2026-10-01), before group B.

## Capabilities

### New Capabilities

- `ascend-agent-test-coverage`: the startup banner, the vector store start-up and the provider request factory have tests that reach each named branch and assert its observable result.

### Modified Capabilities

(none)

## Impact

- Tests only, all in `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/`: `config/StartupLogConfigTest.java`, `config/AppConfigVectorStoreInitTest.java`, `service/provider/ChatModelResolverProviderRegistrationTest.java`.
- No production code, no dependency, no configuration and no documentation outside this change.
- Gate: `./gradlew test` with the module's coverage gate, run from `apps/ascend-agent`.

## Relevant Skills

- `tdd-workflow` for proving each test fails on the branch it names before it passes
- `java-coding-standards` for test naming and structure
- `springboot-patterns` for the JUnit 5 and Mockito tests of Spring components
- `code-formatter` for the `// given`, `// when`, `// then` layout
- `code-reviewer` for the review of the finished tests
