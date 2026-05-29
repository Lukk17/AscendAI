package com.lukk.ascend.ai.agent.service.ingestion;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
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
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.client.RestClient;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class IngestionServiceTitleExtractionTest {

    @Mock
    private RestClient restClient;

    @Spy
    private ObjectMapper objectMapper = new ObjectMapper();

    @InjectMocks
    private IngestionService ingestionService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(ingestionService, "unstructuredBaseUrl", "http://localhost:8000");
        ReflectionTestUtils.setField(ingestionService, "unstructuredApiPath", "/general/v0/general");
    }


    @Test
    @DisplayName("processMarkdown extracts basename for title when filename has no path separator")
    void processMarkdown_FilenameWithoutPath_UsesBareFilenameAsTitle() throws java.io.IOException {
        // given — markdown with no H1, filename is just "readme.md" (no slash)
        String markdown = "Some content without a heading.";
        try (InputStream stream = new ByteArrayInputStream(markdown.getBytes(StandardCharsets.UTF_8))) {

            // when
            List<Document> docs = ingestionService.processMarkdown(stream, "readme.md");

            // then — title falls back to the full filename since there's no slash
            assertThat(docs).hasSize(1);
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("readme.md");
        }
    }

    @Test
    @DisplayName("processMarkdown uses the substring after the last slash as title fallback")
    void processMarkdown_FilenameWithSlash_UsesBasenameAsTitle() throws java.io.IOException {
        // given
        String markdown = "Content without heading.";
        try (InputStream stream = new ByteArrayInputStream(markdown.getBytes(StandardCharsets.UTF_8))) {

            // when
            List<Document> docs = ingestionService.processMarkdown(stream, "folder/subfolder/notes.md");

            // then
            assertThat(docs).hasSize(1);
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("notes.md");
        }
    }


    @Test
    @DisplayName("processUnstructured returns empty list when response is not a JSON array")
    void processUnstructured_NonArrayResponse_ReturnsEmpty() throws java.io.IOException {
        // given
        stubUnstructured("{\"error\":\"unsupported\"}");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            // when
            List<Document> docs = ingestionService.processUnstructured(stream, "test.pdf");

            // then
            assertThat(docs).isEmpty();
        }
    }

    @Test
    @DisplayName("processUnstructured returns empty list when JSON array is empty")
    void processUnstructured_EmptyArray_ReturnsEmpty() throws java.io.IOException {
        stubUnstructured("[]");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            List<Document> docs = ingestionService.processUnstructured(stream, "test.pdf");

            assertThat(docs).isEmpty();
        }
    }

    @Test
    @DisplayName("processUnstructured uses non-Title element text but falls back to filename for title")
    void processUnstructured_ElementsWithoutTitleType_UsesFallbackTitle() throws java.io.IOException {
        // given — no element has type "Title", so title falls back to basename
        stubUnstructured("[{\"type\":\"NarrativeText\",\"text\":\"Some body text.\"}]");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            List<Document> docs = ingestionService.processUnstructured(stream, "folder/report.pdf");

            assertThat(docs).hasSize(1);
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("report.pdf");
            assertThat(docs.getFirst().getText()).contains("Some body text.");
        }
    }

    @Test
    @DisplayName("processUnstructured skips elements that lack a text field")
    void processUnstructured_ElementWithNoTextField_SkippedFromText() throws java.io.IOException {
        // given — second element has no "text" field; only first contributes
        stubUnstructured("[{\"type\":\"Title\",\"text\":\"My Title\"},{\"type\":\"Image\"}]");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            List<Document> docs = ingestionService.processUnstructured(stream, "test.pdf");

            assertThat(docs).hasSize(1);
            // "Image" element contributed no text, only "My Title" row did
            assertThat(docs.getFirst().getText()).isEqualTo("My Title\n");
        }
    }

    @Test
    @DisplayName("processUnstructured ignores Title element with blank text when extracting title")
    void processUnstructured_TitleElementWithBlankText_FallsBackToFilename() throws java.io.IOException {
        // given — Title element has blank text candidate
        stubUnstructured("[{\"type\":\"Title\",\"text\":\"   \"},{\"type\":\"NarrativeText\",\"text\":\"body\"}]");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            List<Document> docs = ingestionService.processUnstructured(stream, "blank_title.pdf");

            assertThat(docs).hasSize(1);
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("blank_title.pdf");
        }
    }

    @Test
    @DisplayName("processUnstructured captures first Title element as the document title")
    void processUnstructured_FirstTitleElement_UsedAsTitle() throws java.io.IOException {
        stubUnstructured("[{\"type\":\"Title\",\"text\":\"Real Title\"},{\"type\":\"Title\",\"text\":\"Second Title\"}]");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            List<Document> docs = ingestionService.processUnstructured(stream, "test.pdf");

            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("Real Title");
        }
    }

    @Test
    @DisplayName("processUnstructured skips Title extraction once title is already set")
    void processUnstructured_TitleAlreadySet_SkipsSubsequentTitleElements() throws java.io.IOException {
        // First Title is captured; second Title node should be skipped (but its text still appended)
        stubUnstructured("[{\"type\":\"Title\",\"text\":\"First Title\"},{\"type\":\"Title\",\"text\":\"Ignored Title\"}]");

        try (InputStream stream = new ByteArrayInputStream("data".getBytes())) {

            List<Document> docs = ingestionService.processUnstructured(stream, "two_titles.pdf");

            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("First Title");
            assertThat(docs.getFirst().getText()).contains("First Title").contains("Ignored Title");
        }
    }

    @Test
    @DisplayName("processUnstructured skips Title extraction when Title element has no text field")
    void processUnstructured_TitleWithNoTextField_FallsBackToFilename() throws java.io.IOException {
        // Title element present BUT has no "text" field -> 4th condition of compound fails -> extractedTitle stays null
        stubUnstructured("[{\"type\":\"Title\"},{\"type\":\"NarrativeText\",\"text\":\"body\"}]");

        try (java.io.InputStream stream = new java.io.ByteArrayInputStream("data".getBytes())) {
            List<Document> docs = ingestionService.processUnstructured(stream, "test.pdf");

            assertThat(docs).hasSize(1);
            // Title had no text -> title falls back to basename "test.pdf"
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("test.pdf");
        }
    }

    @Test
    @DisplayName("processMarkdown uses bare filename as title when filename has no path separator")
    void processMarkdown_FilenameNoSlash_UsesFullFilename() throws java.io.IOException {
        String markdown = "Some content";
        try (InputStream stream = new ByteArrayInputStream(markdown.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {

            List<Document> docs = ingestionService.processMarkdown(stream, "nopath.md");

            assertThat(docs).hasSize(1);
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("nopath.md");
        }
    }

    @Test
    @DisplayName("processMarkdown uses filename as title when extracted title is blank")
    void processMarkdown_BlankExtractedTitle_UsesFallbackFilename() throws Exception {
        // Markdown with H1 that has blank text content (unlikely but possible via edge-case parser)
        // More practically: a heading that only contains whitespace
        // Actually TitleExtractionVisitor extracts literal text, so let's test via a heading with empty text
        // The easiest approach: a file with an H1 that produces blank title via the visitor
        // Since the visitor extracts Text node literals, an H1 with no text child -> title = null
        // An H1 with blank text child -> title = blank
        // Let's test with an H1 that contains spaces only
        String markdown = "#   \n\nSome content.";
        try (java.io.InputStream stream = new java.io.ByteArrayInputStream(markdown.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {

            List<Document> docs = ingestionService.processMarkdown(stream, "test.md");

            assertThat(docs).hasSize(1);
            // H1 with just spaces produces "" title -> isBlank() = true -> use filename
            assertThat(docs.getFirst().getMetadata().get("title")).isEqualTo("test.md");
        }
    }

    @Test
    @DisplayName("processMarkdown throws IngestionException when inputStream throws IOException")
    void processMarkdown_IOExceptionFromStream_ThrowsIngestionException() {
        // Create an InputStream that throws IOException on read
        java.io.InputStream brokenStream = new java.io.InputStream() {
            @Override
            public int read() throws java.io.IOException {
                throw new java.io.IOException("disk error");
            }
        };

        org.assertj.core.api.Assertions.assertThatThrownBy(
                        () -> ingestionService.processMarkdown(brokenStream, "broken.md"))
                .isInstanceOf(com.lukk.ascend.ai.agent.exception.IngestionException.class)
                .hasMessageContaining("broken.md");
    }


    private void stubUnstructured(String jsonResponse) {
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
}
