package com.lukk.ascend.ai.agent.integration;

import io.qdrant.client.QdrantClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.HeadBucketRequest;
import software.amazon.awssdk.services.s3.model.HeadBucketResponse;

import javax.sql.DataSource;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Smokes the Spring context end-to-end against real Postgres / Redis / Qdrant / MinIO
 * containers. Verifies that every {@code @Bean} factory in {@code AppConfig} (S3 client,
 * Qdrant client, RestClient builder, metadata store) actually produces a working bean
 * once the Testcontainers URLs are wired in.
 *
 * <p>The MCP client and chat providers are disabled in {@link TestcontainersBase}, so
 * these tests don't touch external networks — only the data layer.
 */
class BackingServicesIT extends TestcontainersBase {

    @MockitoBean
    org.springframework.ai.mcp.SyncMcpToolCallbackProvider toolCallbackProvider;

    @Autowired
    DataSource dataSource;

    @Autowired
    StringRedisTemplate redisTemplate;

    @Autowired
    QdrantClient qdrantClient;

    @Autowired
    S3Client s3Client;

    @Autowired
    RestClient restClient;

    @Test
    void postgres_isReachableAndSchemaInitialized() {
        JdbcTemplate jdbc = new JdbcTemplate(dataSource);
        Integer one = jdbc.queryForObject("SELECT 1", Integer.class);
        assertThat(one).isEqualTo(1);

        // Liquibase changelog should have run on context startup
        List<String> tables = jdbc.queryForList(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
                String.class);
        assertThat(tables).isNotEmpty();
    }

    @Test
    void redis_isReachableViaTemplate() {
        redisTemplate.opsForValue().set("it:smoke:key", "hello");
        String value = redisTemplate.opsForValue().get("it:smoke:key");
        assertThat(value).isEqualTo("hello");
        redisTemplate.delete("it:smoke:key");
    }

    @Test
    void qdrant_isReachableAndCollectionsExist() throws Exception {
        List<String> collections = qdrantClient.listCollectionsAsync().get();
        // initVectorStore CommandLineRunner should have created both
        assertThat(collections).contains("ascendai-768", "ascendai-1536");
    }

    @Test
    void minio_isReachableAndBucketCreated() throws Exception {
        // app.s3.bucket = knowledge-base; BucketInitConfig (a separate startup runner)
        // creates it at boot. If the runner ran successfully, the HeadBucket call returns 200.
        HeadBucketResponse response = s3Client.headBucket(
                HeadBucketRequest.builder().bucket("knowledge-base").build());
        assertThat(response.sdkHttpResponse().statusCode()).isEqualTo(200);
    }

    @Test
    void restClientBuilder_producesUsableClient() {
        assertThat(restClient).isNotNull();
    }
}
