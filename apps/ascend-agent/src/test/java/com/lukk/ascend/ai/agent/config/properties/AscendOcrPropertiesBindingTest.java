package com.lukk.ascend.ai.agent.config.properties;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.boot.context.properties.source.MapConfigurationPropertySource;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(classes = AscendOcrPropertiesBindingTest.BindingConfig.class)
class AscendOcrPropertiesBindingTest {

    // ascend-ocr refuses a submission with QUEUE_FULL beyond OCR_JOB_QUEUE_MAX_DOCUMENTS waiting
    // documents, which is 8 at its own default.
    private static final int OCR_JOB_QUEUE_MAX_DOCUMENTS = 8;

    @Autowired
    private AscendOcrProperties properties;

    @Value("${app.document-router.pdf-parallel-pages}")
    private int pdfParallelPages;

    @Test
    @DisplayName("the shipped configuration points the client at the job endpoint with its polling window")
    void shippedConfiguration_BindsFromApplicationYaml() {
        assertThat(properties.getBaseUrl()).isEqualTo("http://localhost:7022");
        assertThat(properties.getApiPath()).isEqualTo("/v1/ocr/jobs");
        assertThat(properties.getPollMinInterval()).isEqualTo(Duration.ofSeconds(1));
        assertThat(properties.getPollMaxInterval()).isEqualTo(Duration.ofSeconds(30));
        assertThat(properties.getPollTimeout()).isEqualTo(Duration.ofMinutes(15));
        assertThat(properties.getSubmitRetryAttempts()).isEqualTo(3);
        assertThat(properties.getSubmitRetryMaxDelay()).isEqualTo(Duration.ofSeconds(30));
    }

    @Test
    @DisplayName("every property key binds to its own field, so a renamed key cannot pass unnoticed")
    void everyKey_BindsToItsField() {
        MapConfigurationPropertySource source = new MapConfigurationPropertySource(Map.of(
                "app.ascend-ocr.base-url", "http://ascend-ocr.test:7022",
                "app.ascend-ocr.api-path", "/v2/ocr/jobs",
                "app.ascend-ocr.poll-min-interval", "2s",
                "app.ascend-ocr.poll-max-interval", "40s",
                "app.ascend-ocr.poll-timeout", "20m",
                "app.ascend-ocr.submit-retry-attempts", "7",
                "app.ascend-ocr.submit-retry-max-delay", "45s"));

        AscendOcrProperties bound = new Binder(source).bind("app.ascend-ocr", AscendOcrProperties.class).get();

        assertThat(bound.getBaseUrl()).isEqualTo("http://ascend-ocr.test:7022");
        assertThat(bound.getApiPath()).isEqualTo("/v2/ocr/jobs");
        assertThat(bound.getPollMinInterval()).isEqualTo(Duration.ofSeconds(2));
        assertThat(bound.getPollMaxInterval()).isEqualTo(Duration.ofSeconds(40));
        assertThat(bound.getPollTimeout()).isEqualTo(Duration.ofMinutes(20));
        assertThat(bound.getSubmitRetryAttempts()).isEqualTo(7);
        assertThat(bound.getSubmitRetryMaxDelay()).isEqualTo(Duration.ofSeconds(45));
    }

    @Test
    @DisplayName("every property has a default, so a deployment that configures none still reaches ascend-ocr")
    void everyProperty_HasADefault() {
        AscendOcrProperties defaults = new AscendOcrProperties();

        assertThat(defaults.getBaseUrl()).isEqualTo("http://localhost:7022");
        assertThat(defaults.getApiPath()).isEqualTo("/v1/ocr/jobs");
        assertThat(defaults.getPollMinInterval()).isEqualTo(Duration.ofSeconds(1));
        assertThat(defaults.getPollMaxInterval()).isEqualTo(Duration.ofSeconds(30));
        assertThat(defaults.getPollTimeout()).isEqualTo(Duration.ofMinutes(15));
        assertThat(defaults.getSubmitRetryAttempts()).isEqualTo(3);
        assertThat(defaults.getSubmitRetryMaxDelay()).isEqualTo(Duration.ofSeconds(30));
    }

    @Test
    @DisplayName("the per-page fan-out stays within the number of documents ascend-ocr will queue")
    void pdfParallelPages_StaysWithinTheServiceDocumentBound() {
        assertThat(pdfParallelPages).isBetween(1, OCR_JOB_QUEUE_MAX_DOCUMENTS);
    }

    @Configuration
    @EnableConfigurationProperties(AscendOcrProperties.class)
    static class BindingConfig {
    }
}
