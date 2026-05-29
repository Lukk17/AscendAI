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

/**
 * Extra branch coverage for DoclingClient: empty extraction, fallback text-key walker,
 * JSON parse failure, RestClient exception, normalizePath edge cases.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class DoclingClientExtraTest {

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private DoclingClient client;

    // ------------------------------------------------------------------ helpers

    private RestClient.RequestBodySpec stubChain(String jsonResponse) {
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        RestClient.RequestBodySpec bodySpecMock = mock(RestClient.RequestBodySpec.class);
        RestClient.ResponseSpec responseSpecMock = mock(RestClient.ResponseSpec.class);

        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenReturn(bodySpecMock);
        when(bodySpecMock.contentType(MediaType.MULTIPART_FORM_DATA)).thenReturn(bodySpecMock);
        when(bodySpecMock.body(any(Object.class))).thenReturn(bodySpecMock);
        when(bodySpecMock.retrieve()).thenReturn(responseSpecMock);
        when(responseSpecMock.body(String.class)).thenReturn(jsonResponse);

        return bodySpecMock;
    }

    // ------------------------------------------------------------------ tests

    @Test
    @DisplayName("process returns document with extracted md_content on success")
    void process_ValidMdContentResponse_ReturnsDocument() {
        stubChain("{\"document\":{\"md_content\":\"Hello from Docling\"}}");

        List<Document> docs = client.process("data".getBytes(), "test.pdf");

        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).isEqualTo("Hello from Docling");
    }

    @Test
    @DisplayName("process throws IngestionException when RestClient fails")
    void process_RestClientException_WrapsAsIngestionException() {
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenThrow(new RestClientException("connection refused"));

        assertThatThrownBy(() -> client.process("data".getBytes(), "fail.pdf"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("fail.pdf");
    }

    @Test
    @DisplayName("process returns empty list when all content fields are blank")
    void process_AllContentFieldsBlank_ReturnsEmptyList() {
        stubChain("{\"document\":{\"md_content\":\"\"}}");

        List<Document> docs = client.process("data".getBytes(), "empty.pdf");

        assertThat(docs).isEmpty();
    }

    @Test
    @DisplayName("process falls back to text-key walker when document node is absent")
    void process_NoDocumentNode_FallsBackToTextWalker() {
        stubChain("[{\"text\":\"legacy text\"}]");

        List<Document> docs = client.process("data".getBytes(), "legacy.pdf");

        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("legacy text");
    }

    @Test
    @DisplayName("process throws IngestionException when JSON is malformed")
    void process_MalformedJson_ThrowsIngestionException() {
        stubChain("not-json-at-all");

        assertThatThrownBy(() -> client.process("data".getBytes(), "bad.pdf"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse Docling JSON response");
    }

    @Test
    @DisplayName("process uses text_content when md_content is absent but text_content is present")
    void process_TextContentPresent_ReturnsTextContent() {
        stubChain("{\"document\":{\"text_content\":\"plain text content\"}}");

        List<Document> docs = client.process("data".getBytes(), "text.pdf");

        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).isEqualTo("plain text content");
    }

    @Test
    @DisplayName("process falls back to text-key walker with array containing objects with text fields")
    void process_ArrayOfObjectsWithText_FallsBackToWalker() {
        // Response is an array of objects with "text" fields -> walkForTextKeys array path
        stubChain("[{\"text\":\"page one\"},{\"text\":\"page two\"}]");

        List<Document> docs = client.process("data".getBytes(), "old.pdf");

        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("page one").contains("page two");
    }

    @Test
    @DisplayName("process handles object where text field is non-textual (e.g. numeric)")
    void process_TextFieldIsNumeric_SkippedByWalker() {
        // Object with a "text" field that IS present but NOT a string -> isTextual() = false -> skip
        stubChain("{\"text\": 42, \"other\": \"hello\"}");

        List<Document> docs = client.process("data".getBytes(), "test.pdf");

        // text field is numeric, not textual -> walkForTextKeys skips it
        // "other" has no "text" key equivalent -> nothing extracted -> empty docs
        assertThat(docs).isEmpty();
    }

    @Test
    @DisplayName("process walks object with text field plus non-text non-array child node")
    void process_ObjectWithMixedChildren_WalksAllNodes() {
        // JSON with an object containing text AND a numeric field (non-text, non-array node)
        // The numeric child hits the "not object, not array" branch in walkForTextKeys
        stubChain("{\"items\":[{\"text\":\"extracted text\",\"page\":1}]}");

        List<Document> docs = client.process("data".getBytes(), "test.pdf");

        // document extracted from the text field
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("extracted text");
    }

}
