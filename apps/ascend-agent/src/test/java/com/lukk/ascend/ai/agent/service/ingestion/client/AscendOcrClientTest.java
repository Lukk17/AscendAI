package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.http.MediaType;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AscendOcrClientTest {

    private static final String FILENAME = "invoice.png";
    private static final byte[] BYTES = "image_data".getBytes();
    private static final String BASE_URL = "http://localhost:7022";
    private static final String API_PATH = "/v1/ocr";

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    private AscendOcrClient ascendOcrClient;

    @BeforeEach
    void setUp() {
        ascendOcrClient = new AscendOcrClient(restClient, objectMapper, BASE_URL, API_PATH);
    }

    @Test
    @DisplayName("process extracts OCR text lines from a valid ascend-ocr JSON response")
    void process_WhenValidResponse_ThenExtractsLinesSuccessfully() {
        // given
        String jsonResponse = "{\"pages\": [{\"lines\": [{\"text\": \"Total: $100\"}, {\"text\": \"Tax: $5\"}]}]}";

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
        List<Document> result = ascendOcrClient.process(BYTES, FILENAME, "en");

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst().getText())
                .contains("Total: $100")
                .contains("Tax: $5");
        assertThat(result.getFirst().getMetadata())
                .containsEntry("source", FILENAME)
                .containsEntry("type", "ascendocr");
    }

    @Test
    @DisplayName("process throws IngestionException when the REST client call fails")
    void process_WhenRestClientFails_ThenThrowsIngestionException() {
        // given
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenThrow(new RestClientException("Socket Timeout"));

        // then
        assertThatThrownBy(() -> ascendOcrClient.process(BYTES, FILENAME, null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to process document with ascend-ocr");
    }

    @Test
    @DisplayName("process throws IngestionException when the API returns malformed JSON")
    void process_WhenInvalidJsonReturned_ThenThrowsIngestionException() {
        // given
        String invalidJson = "<xml>not json</xml>";

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
        assertThatThrownBy(() -> ascendOcrClient.process(BYTES, FILENAME, "pl"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse ascend-ocr JSON response");
    }
}
