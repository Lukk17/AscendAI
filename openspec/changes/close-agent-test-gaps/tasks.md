## 1. Startup banner tests

- [ ] 1.1 In `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/config/StartupLogConfigTest.java`, rename `onReadinessChange_AscendMemoryNon200_LogsWarning` to `onReadinessChange_AscendMemoryConnectionRefused_LogsFailed`, update its `@DisplayName`, and remove the comments that describe the non-200 branch. Acceptance: the test passes and asserts the `[FAILED]` line as before
- [ ] 1.2 Add `onReadinessChange_AscendMemoryNon200_LogsWarning` that starts a `com.sun.net.httpserver.HttpServer` on `127.0.0.1` port 0 answering `500` on the AscendMemory probe path, points `semanticMemoryProperties` at it, and asserts the banner line the non-200 branch writes (design D2). Stop the server in `@AfterEach`. Acceptance: the test fails when the non-200 branch in `StartupLogConfig` is changed to write the connection refused text, and passes on the real code
- [ ] 1.3 In `onReadinessChange_SslConfigured_UsesHttps`, replace the `anyString()` port stub with a stub on the exact property and default the code passes, returning `9917`, and assert both banner lines contain `https://localhost:9917` (design D4). Acceptance: the test fails if the port is dropped from the banner

## 2. Vector store start-up test

- [ ] 2.1 In `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/config/AppConfigVectorStoreInitTest.java`, rewrite `initVectorStore_ListCollectionsInterrupted_HandledGracefully` with a future whose `get()` throws `InterruptedException` directly (design D3), assert `Thread.currentThread().isInterrupted()` is true and that no collection was created, then clear the flag. Acceptance: the test fails when the `InterruptedException` catch block stops restoring the interrupt flag, and passes on the real code

## 3. Request factory tests

- [ ] 3.1 In `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/service/provider/ChatModelResolverProviderRegistrationTest.java`, replace `buildRequestFactory_Http1Required_CreatesHttp1Factory` with `buildRequestFactory_Http1Required_SendsHttp11` against a local `HttpServer` that records `HttpExchange.getProtocol()` and answers a minimal chat completion (design D5). Acceptance: the recorded protocol is `HTTP/1.1` and the call succeeds
- [ ] 3.2 Replace `buildRequestFactory_NullTimeoutSeconds_UsesDefaultTimeout` with `buildRequestFactory_TimeoutExceeded_FailsWithTimeout`, a provider with `timeoutSeconds = 1` against a server that waits 3 seconds. Acceptance: the call fails with `HttpTimeoutException` in its cause chain, in under 3 seconds, after exactly one request reached the server
- [ ] 3.3 Add `buildRequestFactory_NullTimeoutSeconds_CallSucceeds`, a provider with `timeoutSeconds = null` against a server that answers at once. Acceptance: the call succeeds, which proves the null timeout falls back to a default instead of failing

## 4. Verification

- [ ] 4.1 Check every new or changed test marks `// given`, `// when`, `// then` and ends with an assertion. Acceptance: a review of the three files finds none without
- [ ] 4.2 Run `./gradlew test` from `apps/ascend-agent`. Acceptance: all tests pass, the coverage gate passes, and no new dependency appears in `./gradlew dependencies --configuration testRuntimeClasspath`
- [ ] 4.3 Report to the owner any defect a test exposed in production code, without changing that code. Acceptance: the report lists each one, or says there were none
