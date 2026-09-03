package com.lukk.ascend.ai.agent.integration;

import org.junit.jupiter.api.Tag;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.qdrant.QdrantContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * Shared base class for AscendAgent integration tests that need real backing services.
 *
 * <p>Spins up Postgres, Redis, Qdrant, and Floci (S3-compatible object store) via
 * Testcontainers and wires them into the Spring context via {@link DynamicPropertySource}
 * before the application boots. Tests extending this class get a fully real data layer, no
 * mocks for backing infrastructure, so they exercise the {@code @Bean} factories in
 * {@code AppConfig}, {@code VectorStoreConfig}, etc., that unit tests can't reach.
 *
 * <p>Tagged {@code @Tag("integration")} so the default {@code gradle test} skips them.
 * Run via {@code ./gradlew integrationTest}; requires Docker.
 *
 * <p>The MCP client is disabled, and the chat-model providers point at unreachable URLs
 * so the context starts without an external network. It's that exercise the chat path
 * should mock {@code ChatModelResolver} or use {@code @MockBean} for {@code AscendChatService}.
 *
 * <p>The containers are started once, in the static initializer below, and never stopped
 * by this class: only Testcontainers' Ryuk reaper stops them, at JVM exit. This is the
 * documented Testcontainers "singleton container" pattern for a container meant to be
 * shared across every test class in one run, not just across the test methods of one class.
 * The {@code @Container} annotation is deliberately not used here: Testcontainers' JUnit 5
 * extension stops an {@code @Container}-annotated field in {@code afterAll} of whichever
 * test class happens to run it, even when the field is {@code static} and declared in a
 * shared superclass, so every subclass after the first would tear down the previous
 * subclass's containers and start fresh ones on new ports. Spring's test-context cache does
 * not know that, so it kept reusing the first subclass's {@code ApplicationContext}, with
 * beans still wired to the ports the {@code @DynamicPropertySource} method below captured
 * for the first container instances, which by then had already been stopped. That mismatch,
 * not host load, was the actual cause of the connection timeouts this class used to produce
 * partway through a full {@code integrationTest} run.
 */
// Container fields are intentionally not try-with-resources: they live for the whole JVM,
// closed only by Ryuk at JVM exit, which the IDE's resource inspection can't detect.
@SuppressWarnings("resource")
@SpringBootTest(properties = "spring.ai.mcp.client.enabled=false")
@Tag("integration")
public abstract class TestcontainersBase {

    protected static final int FLOCI_EDGE_PORT = 4566;

    protected static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(
            DockerImageName.parse("postgres:16-alpine"))
            .withDatabaseName("ascend_ai")
            .withUsername("postgres")
            .withPassword("local");

    protected static final GenericContainer<?> REDIS = new GenericContainer<>(
            DockerImageName.parse("redis:7-alpine"))
            .withExposedPorts(6379);

    protected static final QdrantContainer QDRANT = new QdrantContainer(
            DockerImageName.parse("qdrant/qdrant:v1.13.0"));

    protected static final GenericContainer<?> FLOCI = new GenericContainer<>(
            DockerImageName.parse("floci/floci:2.0.1"))
            .withExposedPorts(FLOCI_EDGE_PORT)
            .waitingFor(Wait.forHttp("/_floci/health").forStatusCode(200));

    static {
        // Started sequentially, once, before any subclass's Spring context is built.
        // A static initializer runs at class-load time, ahead of any JUnit or Spring
        // callback, so every subclass's @DynamicPropertySource call below is guaranteed
        // to see these four containers already running on their final, stable ports.
        POSTGRES.start();
        REDIS.start();
        QDRANT.start();
        FLOCI.start();
    }

    @DynamicPropertySource
    static void wireProperties(DynamicPropertyRegistry registry) {
        // Postgres
        registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        registry.add("spring.datasource.username", POSTGRES::getUsername);
        registry.add("spring.datasource.password", POSTGRES::getPassword);
        registry.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");

        // Redis
        registry.add("spring.data.redis.host", REDIS::getHost);
        registry.add("spring.data.redis.port", () -> REDIS.getMappedPort(6379));

        // Qdrant
        registry.add("spring.ai.vectorstore.qdrant.host", QDRANT::getHost);
        registry.add("spring.ai.vectorstore.qdrant.port", QDRANT::getGrpcPort);
        registry.add("spring.ai.vectorstore.qdrant.use-tls", () -> false);

        // Floci (S3-compatible object store) — credentials are unauthenticated placeholders
        // that match application.yaml, since Floci does not validate them at all.
        registry.add("app.s3.endpoint",
                () -> "http://" + FLOCI.getHost() + ":" + FLOCI.getMappedPort(FLOCI_EDGE_PORT));
        registry.add("app.s3.access-key", () -> "admin");
        registry.add("app.s3.secret-key", () -> "password");
        registry.add("app.s3.bucket", () -> "knowledge-base");

        // AscendMemory sidecar — point at a port that won't bind, so the optional
        // search returns empty rather than blocking. Tests that exercise memory
        // should override this to point at a stub server.
        registry.add("app.memory.semantic.base-url", () -> "http://localhost:1");
        registry.add("app.memory.semantic.enabled", () -> false);

        // Disable Spring AI chat models so the context boots without reaching out to
        // LM Studio / OpenAI / etc. The MCP client is disabled via the class-level
        // @SpringBootTest(properties = ...) above, not here: it must stay a static
        // property rather than a dynamic one, because a dynamic property registered
        // in a subclass's own @DynamicPropertySource method (e.g. McpStartupToleranceIT)
        // is applied before this superclass method runs, so this superclass value would
        // silently win and overwrite any subclass override of the same key.
        registry.add("app.ai.providers.lmstudio.enabled", () -> false);
        registry.add("app.ai.providers.openai.enabled", () -> false);
        registry.add("app.ai.providers.gemini.enabled", () -> false);
        registry.add("app.ai.providers.anthropic.enabled", () -> false);
        registry.add("app.ai.providers.minimax.enabled", () -> false);
    }
}
