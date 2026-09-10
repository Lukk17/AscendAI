package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.DoclingProperties;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.io.IOException;
import java.time.Duration;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DoclingClientTest {

    private static final String FILENAME = "report.docx";
    private static final byte[] BYTES = "content".getBytes();

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private DoclingProperties doclingProperties;

    @InjectMocks
    private DoclingClient doclingClient;

    @Test
    @DisplayName("process extracts text from a valid Docling JSON response")
    void process_WhenValidResponse_ThenExtractsTextSuccessfully() {
        // given
        String jsonResponse = "{ \"text\": \"Extracted text\", \"pages\": [ { \"text\": \"Nested page text\" } ] }";

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenReturn(responseSpecMock);
        when(responseSpecMock.body(String.class)).thenReturn(jsonResponse);

        // when
        List<Document> result = doclingClient.process(BYTES, FILENAME);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getText())
                .contains("Extracted text")
                .contains("Nested page text");
        assertThat(result.getFirst().getMetadata())
                .containsEntry("source", FILENAME)
                .containsEntry("type", "docling");
    }

    @Test
    @DisplayName("process throws IngestionException when the REST client call fails with a non-transport error")
    void process_WhenRestClientFails_ThenThrowsIngestionException() {
        // given
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenThrow(new RestClientException("Connection Refused"));

        // then: a non-transport RestClientException must fail fast, never retry
        assertThatThrownBy(() -> doclingClient.process(BYTES, FILENAME))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to process document with Docling");
        verify(restClient, times(1)).post();
    }

    @Test
    @DisplayName("process throws IngestionException when the API returns malformed JSON")
    void process_WhenInvalidJsonReturned_ThenThrowsIngestionException() throws Exception {
        // given
        String invalidJson = "{ invalid: j!son }";

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenReturn(responseSpecMock);
        when(responseSpecMock.body(String.class)).thenReturn(invalidJson);

        // then
        assertThatThrownBy(() -> doclingClient.process(BYTES, FILENAME))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse Docling JSON response");
    }

    @Test
    @DisplayName("process retries on transient connection failures and succeeds once the upstream recovers")
    void process_WhenTransientConnectionFailureThenRecovers_ThenSucceedsOnRetry() {
        // given: Docling Serve worker dies mid-request twice, then a respawned worker completes the call
        when(doclingProperties.getRetryAttempts()).thenReturn(2);
        when(doclingProperties.getRetryDelay()).thenReturn(Duration.ZERO);

        String jsonResponse = "{ \"document\": { \"md_content\": \"Recovered text\" } }";

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve())
                .thenThrow(new ResourceAccessException("I/O error", new IOException("Unexpected end of file from server")))
                .thenThrow(new ResourceAccessException("I/O error", new IOException("Unexpected end of file from server")))
                .thenReturn(responseSpecMock);
        when(responseSpecMock.body(String.class)).thenReturn(jsonResponse);

        // when
        List<Document> result = doclingClient.process(BYTES, FILENAME);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getText()).contains("Recovered text");
        verify(restClient, times(3)).post();
    }

    @Test
    @DisplayName("process throws the original exception type after every retry also fails with a transport error")
    void process_WhenConnectionFailsOnEveryAttempt_ThenPropagatesOriginalExceptionAfterBoundedRetries() {
        // given: every attempt hits a dying Docling Serve worker
        when(doclingProperties.getRetryAttempts()).thenReturn(2);
        when(doclingProperties.getRetryDelay()).thenReturn(Duration.ZERO);

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve())
                .thenThrow(new ResourceAccessException("I/O error", new IOException("Unexpected end of file from server")));

        // then
        assertThatThrownBy(() -> doclingClient.process(BYTES, FILENAME))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to process document with Docling")
                .hasCauseInstanceOf(ResourceAccessException.class);
        verify(restClient, times(3)).post();
    }

    @Test
    @DisplayName("process does not retry an HTTP error response carrying a body")
    void process_WhenHttpErrorResponse_ThenDoesNotRetry() {
        // given: even with retries configured, a 422 response is a completed exchange, not a transport failure
        when(doclingProperties.getRetryAttempts()).thenReturn(2);

        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenThrow(HttpClientErrorException.create(
                HttpStatus.UNPROCESSABLE_ENTITY, "Unprocessable Entity", HttpHeaders.EMPTY,
                "{\"detail\":\"invalid file\"}".getBytes(), null));

        // then
        assertThatThrownBy(() -> doclingClient.process(BYTES, FILENAME))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to process document with Docling")
                .hasCauseInstanceOf(HttpClientErrorException.class);
        verify(restClient, times(1)).post();
    }
}
