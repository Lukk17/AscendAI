package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
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

    @DisplayName("normalize path auto corrects when legacy endpoint")
    @Test
    void normalizePath_WhenLegacyEndpoint_ThenAutoCorrects() {
        // given
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/v1/convert");

        // then
        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @DisplayName("normalize path adds it when missing leading slash")
    @Test
    void normalizePath_WhenMissingLeadingSlash_ThenAddsIt() {
        // given
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "v1/convert/file");

        // then
        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @DisplayName("normalize path strips it when trailing slash")
    @Test
    void normalizePath_WhenTrailingSlash_ThenStripsIt() {
        // given
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/v1/convert/file/");

        // then
        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @DisplayName("normalize path returns correct default when null")
    @Test
    void normalizePath_WhenNull_ThenReturnsCorrectDefault() {
        // given
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", null);

        // then
        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/v1/convert/file");
    }

    @DisplayName("normalize path preserves custom path when already valid")
    @Test
    void normalizePath_PreservesCustomPath_WhenAlreadyValid() {
        // given
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/custom/path");

        // then
        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/custom/path");
    }

    @DisplayName("normalize path keeps slash when single slash")
    @Test
    void normalizePath_WhenSingleSlash_ThenKeepsSlash() {
        // given — length == 1 -> trimmed.length() > 1 is false -> trailing slash NOT stripped -> "/" returned
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/");

        // then
        assertThat((String) ReflectionTestUtils.getField(client, "doclingApiPath"))
                .isEqualTo("/");
    }

    @DisplayName("log configured endpoint does not throw")
    @Test
    void logConfiguredEndpoint_DoesNotThrow() {
        // given
        DoclingClient client = new DoclingClient(restClient, objectMapper, "http://docling", "/v1/convert/file");

        // then — package-private invoked via reflection to cover the @PostConstruct line
        ReflectionTestUtils.invokeMethod(client, "logConfiguredEndpoint");
    }
}
