package com.lukk.ascend.ai.agent.integration;

import org.junit.jupiter.api.Tag;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.MinIOContainer;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.qdrant.QdrantContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * Shared base class for AscendAgent integration tests that need real backing services.
 *
 * <p>Spins up Postgres, Redis, Qdrant, and MinIO via Testcontainers and wires them into
 * the Spring context via {@link DynamicPropertySource} before the application boots.
 * Tests extending this class get a fully real data layer — no mocks for backing
 * infrastructure — so they exercise the {@code @Bean} factories in {@code AppConfig},
 * {@code VectorStoreConfig}, etc., that unit tests can't reach.
 *
 * <p>Tagged {@code @Tag("integration")} so the default {@code gradle test} skips them.
 * Run via {@code ./gradlew integrationTest}; requires Docker.
 *
 * <p>The MCP client is disabled, and the chat-model providers point at unreachable URLs
 * so the context starts without an external network. It's that exercise the chat path
 * should mock {@code ChatModelResolver} or use {@code @MockBean} for {@code AscendChatService}.
 */
// Container fields are intentionally not try-with-resources — the @Testcontainers + @Container
// annotations manage the lifecycle (start before all tests, close after the class), which the
// IDE's resource inspection can't detect on its own.
@SuppressWarnings("resource")
@SpringBootTest
@Tag("integration")
@Testcontainers
public abstract class TestcontainersBase {

    @Container
    protected static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(
            DockerImageName.parse("postgres:16-alpine"))
            .withDatabaseName("ascend_ai")
            .withUsername("postgres")
            .withPassword("local");

    @Container
    protected static final GenericContainer<?> REDIS = new GenericContainer<>(
            DockerImageName.parse("redis:7-alpine"))
            .withExposedPorts(6379);

    @Container
    protected static final QdrantContainer QDRANT = new QdrantContainer(
            DockerImageName.parse("qdrant/qdrant:v1.13.0"));

    @Container
    protected static final MinIOContainer MINIO = new MinIOContainer(
            DockerImageName.parse("minio/minio:RELEASE.2024-12-18T13-15-44Z"))
            .withUserName("admin")
            .withPassword("password123");

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

        // MinIO
        registry.add("app.s3.endpoint", MINIO::getS3URL);
        registry.add("app.s3.access-key", MINIO::getUserName);
        registry.add("app.s3.secret-key", MINIO::getPassword);
        registry.add("app.s3.bucket", () -> "knowledge-base");

        // AscendMemory sidecar — point at a port that won't bind, so the optional
        // search returns empty rather than blocking. Tests that exercise memory
        // should override this to point at a stub server.
        registry.add("app.memory.semantic.base-url", () -> "http://localhost:1");
        registry.add("app.memory.semantic.enabled", () -> false);

        // Disable MCP client + Spring AI chat models so the context boots without
        // reaching out to LM Studio / OpenAI / etc.
        registry.add("spring.ai.mcp.client.enabled", () -> false);
        registry.add("app.ai.providers.lmstudio.enabled", () -> false);
        registry.add("app.ai.providers.openai.enabled", () -> false);
        registry.add("app.ai.providers.gemini.enabled", () -> false);
        registry.add("app.ai.providers.anthropic.enabled", () -> false);
        registry.add("app.ai.providers.minimax.enabled", () -> false);
    }
}
