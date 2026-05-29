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
class DoclingClientResponseParsingTest {

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private DoclingClient client;


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


    @Test
    @DisplayName("process returns document with extracted md_content on success")
    void process_ValidMdContentResponse_ReturnsDocument() {
        // given
        stubChain("{\"document\":{\"md_content\":\"Hello from Docling\"}}");

        // when
        List<Document> docs = client.process("data".getBytes(), "test.pdf");

        // then
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).isEqualTo("Hello from Docling");
    }

    @Test
    @DisplayName("process throws IngestionException when RestClient fails")
    void process_RestClientException_WrapsAsIngestionException() {
        // given
        RestClient.RequestBodyUriSpec postMock = mock(RestClient.RequestBodyUriSpec.class);
        when(restClient.post()).thenReturn(postMock);
        when(postMock.uri(anyString())).thenThrow(new RestClientException("connection refused"));

        // then
        assertThatThrownBy(() -> client.process("data".getBytes(), "fail.pdf"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("fail.pdf");
    }

    @Test
    @DisplayName("process returns empty list when all content fields are blank")
    void process_AllContentFieldsBlank_ReturnsEmptyList() {
        // given
        stubChain("{\"document\":{\"md_content\":\"\"}}");

        // then
        assertThat(client.process("data".getBytes(), "empty.pdf")).isEmpty();
    }

    @Test
    @DisplayName("process falls back to text-key walker when document node is absent")
    void process_NoDocumentNode_FallsBackToTextWalker() {
        // given
        stubChain("[{\"text\":\"legacy text\"}]");

        // when
        List<Document> docs = client.process("data".getBytes(), "legacy.pdf");

        // then
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("legacy text");
    }

    @Test
    @DisplayName("process throws IngestionException when JSON is malformed")
    void process_MalformedJson_ThrowsIngestionException() {
        // given
        stubChain("not-json-at-all");

        // then
        assertThatThrownBy(() -> client.process("data".getBytes(), "bad.pdf"))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to parse Docling JSON response");
    }

    @Test
    @DisplayName("process uses text_content when md_content is absent but text_content is present")
    void process_TextContentPresent_ReturnsTextContent() {
        // given
        stubChain("{\"document\":{\"text_content\":\"plain text content\"}}");

        // when
        List<Document> docs = client.process("data".getBytes(), "text.pdf");

        // then
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).isEqualTo("plain text content");
    }

    @Test
    @DisplayName("process falls back to text-key walker with array containing objects with text fields")
    void process_ArrayOfObjectsWithText_FallsBackToWalker() {
        // given — response is an array of objects with "text" fields -> walkForTextKeys array path
        stubChain("[{\"text\":\"page one\"},{\"text\":\"page two\"}]");

        // when
        List<Document> docs = client.process("data".getBytes(), "old.pdf");

        // then
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("page one").contains("page two");
    }

    @Test
    @DisplayName("process handles object where text field is non-textual (e.g. numeric)")
    void process_TextFieldIsNumeric_SkippedByWalker() {
        // given — "text" field IS present but NOT a string -> isTextual() = false -> skip
        stubChain("{\"text\": 42, \"other\": \"hello\"}");

        // when
        List<Document> docs = client.process("data".getBytes(), "test.pdf");

        // then — text field is numeric -> walkForTextKeys skips it -> empty docs
        assertThat(docs).isEmpty();
    }

    @Test
    @DisplayName("process walks object with text field plus non-text non-array child node")
    void process_ObjectWithMixedChildren_WalksAllNodes() {
        // given — JSON with object containing text AND a numeric field (non-text, non-array node)
        // The numeric child hits the "not object, not array" branch in walkForTextKeys
        stubChain("{\"items\":[{\"text\":\"extracted text\",\"page\":1}]}");

        // when
        List<Document> docs = client.process("data".getBytes(), "test.pdf");

        // then
        assertThat(docs).hasSize(1);
        assertThat(docs.getFirst().getText()).contains("extracted text");
    }

}
