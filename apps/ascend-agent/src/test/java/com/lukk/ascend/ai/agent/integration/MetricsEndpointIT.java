package com.lukk.ascend.ai.agent.integration;

import com.lukk.ascend.ai.agent.service.cache.AnthropicPromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.OpenAiPromptCacheStrategy;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.junit.jupiter.api.Test;
import org.springframework.ai.anthropic.api.AnthropicApi;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalManagementPort;
import org.springframework.http.ResponseEntity;

import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Verifies the Prometheus scrape endpoint exposes every custom metric the
 * observability change defines, including the three prompt-cache counters.
 *
 * <p>The prompt-cache counters and the gen_ai usage counter are recorded
 * through the real strategy implementations. The remaining meters are
 * recorded once with the exact names and spec-defined tags the production
 * code uses; their per-path behaviour is covered by the unit metric tests.
 *
 * <p>The actuator lives on the internal management port (see
 * {@code management.server.port} in application.yaml), so this test boots a
 * real web environment with a random management port and scrapes it over
 * HTTP rather than through MockMvc, which only sees the application port.
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {"spring.ai.mcp.client.enabled=false", "management.server.port=0"})
@AutoConfigureObservability(metrics = true)
class MetricsEndpointIT extends TestcontainersBase {

    @LocalManagementPort
    int managementPort;

    @Autowired
    TestRestTemplate restTemplate;

    @Autowired
    MeterRegistry meterRegistry;

    @Test
    void prometheusEndpoint_exposesEveryCustomMetricDefinedByObservabilityChange() {
        // given
        recordPromptCacheMetersThroughStrategies();
        recordRemainingChangeMetersOnce();

        // when
        ResponseEntity<String> response = restTemplate.getForEntity(
                "http://localhost:" + managementPort + "/actuator/prometheus", String.class);

        // then
        assertThat(response.getStatusCode().is2xxSuccessful()).isTrue();
        String body = response.getBody();
        assertThat(body).isNotNull();
        assertThat(body).contains("memory_extraction_parse_failed_total");
        assertThat(body).contains("memory_insert_failed_total");
        assertThat(body).contains("memory_search_duration_seconds");
        assertThat(body).contains("rag_retrieval_hits_total");
        assertThat(body).contains("rag_retrieval_duration_seconds");
        assertThat(body).contains("rag_top_score_bucket");
        assertThat(body).contains("mcp_tool_duration_seconds");
        assertThat(body).contains("ingestion_upload_bytes_total");
        assertThat(body).contains("prompt_cache_tokens_read_total");
        assertThat(body).contains("prompt_cache_tokens_creation_total");
        assertThat(body).contains("gen_ai_client_token_usage_total{");
        assertThat(body).contains("gen_ai_system=\"anthropic\"");
        assertThat(body).contains("gen_ai_system=\"openai\"");

        List<String> sampleLines = body.lines()
                .filter(line -> !line.isBlank() && !line.startsWith("#"))
                .toList();
        assertThat(sampleLines).isNotEmpty();
        assertThat(sampleLines).allSatisfy(line ->
                assertThat(line).contains("service=\"ascend-agent\""));
    }

    private void recordPromptCacheMetersThroughStrategies() {
        AnthropicApi.Usage anthropicNative = new AnthropicApi.Usage(612, 100, 0, 487);
        Usage anthropicUsage = new DefaultUsage(612, 100, 712, anthropicNative);
        new AnthropicPromptCacheStrategy(meterRegistry)
                .recordOutcome("metrics-endpoint-it", chatResponse(anthropicUsage));

        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 512);
        OpenAiApi.Usage openaiNative = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage openaiUsage = new DefaultUsage(1024, 100, 1124, openaiNative);
        new OpenAiPromptCacheStrategy("openai", meterRegistry)
                .recordOutcome("metrics-endpoint-it", chatResponse(openaiUsage));
    }

    private void recordRemainingChangeMetersOnce() {
        Counter.builder("memory.extraction.parse_failed")
                .tag("provider", "openai")
                .tag("model", "gpt-4o-mini")
                .register(meterRegistry)
                .increment();
        Counter.builder("memory.insert.failed")
                .tag("embedding_provider", "openai")
                .tag("reason", "5xx")
                .register(meterRegistry)
                .increment();
        Timer.builder("memory.search.duration")
                .tag("embedding_provider", "openai")
                .tag("outcome", "ok")
                .register(meterRegistry)
                .record(Duration.ofMillis(5));
        Counter.builder("rag.retrieval.hits")
                .tag("provider", "openai")
                .tag("embedding_provider", "openai")
                .tag("above_threshold", "true")
                .register(meterRegistry)
                .increment();
        Timer.builder("rag.retrieval.duration")
                .tag("provider", "openai")
                .tag("outcome", "ok")
                .register(meterRegistry)
                .record(Duration.ofMillis(5));
        DistributionSummary.builder("rag.top_score")
                .tag("provider", "openai")
                .register(meterRegistry)
                .record(0.91);
        Timer.builder("mcp.tool.duration")
                .tag("tool", "weather")
                .tag("outcome", "ok")
                .register(meterRegistry)
                .record(Duration.ofMillis(5));
        Counter.builder("ingestion.upload.bytes")
                .tag("source_type", "markdown")
                .tag("outcome", "ok")
                .register(meterRegistry)
                .increment(128);
    }

    private static ChatResponse chatResponse(Usage usage) {
        ChatResponseMetadata metadata = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(metadata);
        return response;
    }
}
