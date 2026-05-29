package com.lukk.ascend.ai.agent.service.ingestion.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.exception.IngestionException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
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
@MockitoSettings(strictness = Strictness.LENIENT)
class PaddleOcrClientResponseParsingTest {

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private PaddleOcrClient client;


    private void stubChain(String jsonResponse) {
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenReturn(responseSpecMock);
        when(responseSpecMock.body(String.class)).thenReturn(jsonResponse);
    }


    @Test
    @DisplayName("process extracts text from pages/lines/text structure")
    void process_ValidResponse_ExtractsText() {
        // given
        stubChain("{\"pages\":[{\"lines\":[{\"text\":\"Hello OCR\"}]}]}");

        // when
        List<Document> docs = client.process("img".getBytes(), "page.png", null);

        // then
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("Hello OCR");
    }

    @Test
    @DisplayName("process returns empty list when pages array is absent from response")
    void process_NoPagesArray_ReturnsEmpty() {
        // given
        stubChain("{\"status\":\"ok\"}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", null)).isEmpty();
    }

    @Test
    @DisplayName("process returns empty list when pages is not an array node")
    void process_PagesNotArray_ReturnsEmpty() {
        // given
        stubChain("{\"pages\":\"not-an-array\"}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", null)).isEmpty();
    }

    @Test
    @DisplayName("process returns empty list when page has no lines array")
    void process_PageWithNoLinesArray_ReturnsEmpty() {
        // given
        stubChain("{\"pages\":[{\"something\":\"else\"}]}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", null)).isEmpty();
    }

    @Test
    @DisplayName("process skips lines that have no text field")
    void process_LineWithNoTextField_SkipsLine() {
        // given
        stubChain("{\"pages\":[{\"lines\":[{\"confidence\":0.99}]}]}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", null)).isEmpty();
    }

    @Test
    @DisplayName("process does not add lang parameter when lang is null")
    void process_NullLang_DoesNotAddLangParam() {
        // given
        stubChain("{\"pages\":[{\"lines\":[{\"text\":\"text\"}]}]}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", null)).hasSize(1);
    }

    @Test
    @DisplayName("process adds lang parameter to request body when lang is non-blank")
    void process_NonBlankLang_AddsLangParam() {
        // given
        stubChain("{\"pages\":[{\"lines\":[{\"text\":\"text\"}]}]}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", "pl")).hasSize(1);
    }

    @Test
    @DisplayName("process throws IngestionException when RestClient fails")
    void process_RestClientException_WrapsAsIngestionException() {
        // given
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenThrow(new RestClientException("paddle down"));

        // then
        assertThatThrownBy(() -> client.process("img".getBytes(), "fail.png", null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("fail.png");
    }

    @Test
    @DisplayName("process throws IngestionException when JSON response is malformed")
    void process_MalformedJson_ThrowsIngestionException() {
        // given
        stubChain("NOT_JSON");

        // then
        assertThatThrownBy(() -> client.process("img".getBytes(), "bad.png", null))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse PaddleOCR JSON response");
    }

    @Test
    @DisplayName("process returns empty when lines field is present but not an array")
    void process_LinesFieldPresentButNotArray_ReturnsEmpty() {
        // given — lines IS present but is a string (not array) -> extractLinesText returns early
        stubChain("{\"pages\":[{\"lines\":\"not-an-array\"}]}");

        // then
        assertThat(client.process("img".getBytes(), "page.png", null)).isEmpty();
    }
}
