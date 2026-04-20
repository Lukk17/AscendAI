package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
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
class DoclingClientTest {

    private static final String FILENAME = "report.docx";
    private static final byte[] BYTES = "content".getBytes();

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private DoclingClient doclingClient;

    @Test
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
        assertThat(result.get(0).getText())
                .contains("Extracted text")
                .contains("Nested page text");
        assertThat(result.get(0).getMetadata())
                .containsEntry("source", FILENAME)
                .containsEntry("type", "docling");
    }

    @Test
    void process_WhenRestClientFails_ThenThrowsIngestionException() {
        // given
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        
        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenThrow(new RestClientException("Connection Refused"));

        // when / then
        assertThatThrownBy(() -> doclingClient.process(BYTES, FILENAME))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to process document with Docling");
    }

    @Test
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

        // when / then
        assertThatThrownBy(() -> doclingClient.process(BYTES, FILENAME))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse Docling JSON response");
    }
}
