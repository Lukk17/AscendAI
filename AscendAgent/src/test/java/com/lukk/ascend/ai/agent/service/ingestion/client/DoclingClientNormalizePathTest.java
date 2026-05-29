package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

/**
 * Targets the {@code normalizePath} branches that aren't reachable via the @Autowired wiring path:
 * legacy-auto-correct, missing-leading-slash, trailing-slash, and null configured value.
 */
class DoclingClientNormalizePathTest {

    private final RestClient restClient = mock(RestClient.class);
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void normalizePath_WhenLegacyEndpoint_ThenAutoCorrects() {
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/v1/convert");

        String configured = (String) ReflectionTestUtils.getField(client, "doclingApiPath");
        assertThat(configured).isEqualTo("/v1/convert/file");
    }

    @Test
    void normalizePath_WhenMissingLeadingSlash_ThenAddsIt() {
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "v1/convert/file");

        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @Test
    void normalizePath_WhenTrailingSlash_ThenStripsIt() {
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/v1/convert/file/");

        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @Test
    void normalizePath_WhenNull_ThenReturnsCorrectDefault() {
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", null);

        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @Test
    void normalizePath_PreservesCustomPath_WhenAlreadyValid() {
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/custom/path");

        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/custom/path");
    }

    @Test
    void normalizePath_WhenSingleSlash_ThenKeepsSlash() {
        // length == 1 -> trimmed.length() > 1 is false -> trailing slash NOT stripped -> "/" returned
        // "/" != LEGACY_PATH (/v1/convert) so no auto-correct
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/");

        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/");
    }

    @Test
    void logConfiguredEndpoint_DoesNotThrow() {
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/v1/convert/file");

        // package-private — invoke via reflection to cover the @PostConstruct line
        ReflectionTestUtils.invokeMethod(client, "logConfiguredEndpoint");
    }
}
