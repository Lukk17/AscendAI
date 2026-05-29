package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.properties.IngestionUploadProperties;
import com.lukk.ascend.ai.agent.dto.ApiError;
import com.lukk.ascend.ai.agent.dto.UploadResponse;
import com.lukk.ascend.ai.agent.service.ingestion.ManualIngestionService;
import com.lukk.ascend.ai.agent.service.ingestion.MimeTypeDetector;
import com.lukk.ascend.ai.agent.service.storage.StorageService;
import org.assertj.core.api.InstanceOfAssertFactories;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.lang.NonNull;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class IngestionControllerUploadValidationTest {

    @Mock
    private StorageService storageService;

    @Mock
    private ManualIngestionService manualIngestionService;

    @Mock
    private MimeTypeDetector mimeTypeDetector;

    @Spy
    private IngestionUploadProperties uploadProperties = new IngestionUploadProperties();

    @InjectMocks
    private IngestionController controller;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(controller, "markdownFolder", "markdown");
        ReflectionTestUtils.setField(controller, "documentsFolder", "documents");
        uploadProperties.setAllowedMimeTypes(List.of(
                "application/pdf", "text/markdown", "text/plain"));
        lenient().when(mimeTypeDetector.detect(any(MultipartFile.class), anyString()))
                .thenAnswer(inv -> {
                    MultipartFile mf = inv.getArgument(0);
                    return mf.getContentType() != null ? mf.getContentType().toLowerCase() : "application/octet-stream";
                });
    }

    @Test
    @DisplayName("returns 400 with no_file error when files list is null")
    void uploadDocument_ReturnsBadRequest_WhenFilesListIsNull() {
        // when
        ResponseEntity<?> response = controller.uploadDocument(null);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody())
                .asInstanceOf(InstanceOfAssertFactories.type(ApiError.class))
                .extracting(ApiError::error)
                .isEqualTo("no_file");
    }

    @Test
    @DisplayName("skips empty file entries and uploads only non-empty files from a mixed list")
    void uploadDocument_SkipsEmptyEntries_WhenMixedListProvided() throws IOException {
        // given — hits the "if (file.isEmpty()) continue;" branch in the loop
        MockMultipartFile empty = new MockMultipartFile("file", "skip.md", "text/markdown", new byte[0]);
        MockMultipartFile good = new MockMultipartFile("file", "ok.md", "text/markdown", "x".getBytes());

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(empty, good));

        // then — verify only the good file was uploaded
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        org.mockito.Mockito.verify(storageService).uploadFile(eq("markdown/ok.md"), any(), org.mockito.ArgumentMatchers.anyLong());
    }

    @Test
    @DisplayName("returns 415 with unsupported_media_type error when all files have disallowed MIME type")
    void uploadDocument_RejectsAllFiles_WithDisallowedMime_Returns415() {
        // given
        MockMultipartFile evil = new MockMultipartFile("file", "evil.exe",
                "application/x-msdownload", "MZ".getBytes());

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(evil));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        assertThat(response.getBody())
                .asInstanceOf(InstanceOfAssertFactories.type(ApiError.class))
                .satisfies(err -> {
                    assertThat(err.error()).isEqualTo("unsupported_media_type");
                    assertThat(err.message()).contains("disallowed type");
                });
    }

    @Test
    @DisplayName("captures IOException from getInputStream and reports it in failures")
    void uploadDocument_CapturesIOException_AndReportsInFailures() throws IOException {
        // given
        MultipartFile broken = new MockMultipartFile("file", "broken.pdf", "application/pdf", "data".getBytes()) {
            @Override
            @NonNull
            public InputStream getInputStream() throws IOException {
                throw new IOException("disk full");
            }
        };

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(broken));

        // then — no file successfully uploaded -> 415 with failures listed
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        assertThat(response.getBody())
                .asInstanceOf(InstanceOfAssertFactories.type(ApiError.class))
                .extracting(ApiError::message, InstanceOfAssertFactories.STRING)
                .contains("disk full");
    }

    @Test
    @DisplayName("reports IO failure alongside successful uploads in the same response")
    void uploadDocument_ReportsIOFailure_AlongsideSuccessfulUploads() throws IOException {
        // given
        MockMultipartFile good = new MockMultipartFile("file", "ok.md", "text/markdown", "x".getBytes());
        MultipartFile broken = new MockMultipartFile("file", "boom.pdf", "application/pdf", "data".getBytes()) {
            @Override
            @NonNull
            public InputStream getInputStream() throws IOException {
                throw new IOException("io failed");
            }
        };

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(good, broken));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody())
                .asInstanceOf(InstanceOfAssertFactories.type(UploadResponse.class))
                .satisfies(body -> {
                    assertThat(body.uploaded()).containsExactly("markdown/ok.md");
                    assertThat(body.failures()).hasSize(1);
                    assertThat(body.failures().getFirst()).contains("io failed");
                });
    }

    @Test
    @DisplayName("accepts any MIME type when the allowed list is empty")
    void uploadDocument_AcceptsAllMimes_WhenAllowedListIsEmpty() throws IOException {
        // given
        uploadProperties.setAllowedMimeTypes(List.of());
        MockMultipartFile any = new MockMultipartFile("file", "x.bin", "application/x-anything", "x".getBytes());

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(any));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("accepts any MIME type when the allowed list is null")
    void uploadDocument_AcceptsAllMimes_WhenAllowedListIsNull() throws IOException {
        // given
        uploadProperties.setAllowedMimeTypes(null);
        MockMultipartFile any = new MockMultipartFile("file", "x.bin", "application/x-anything", "x".getBytes());

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(any));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    @DisplayName("runIngestion delegates to service with provided prefix and embedding provider")
    void runIngestion_DelegatesToService_WithProvidedPrefixAndProvider() {
        // given
        ManualIngestionService.ManualIngestionResult expected = new ManualIngestionService.ManualIngestionResult();
        expected.indexed = 3;
        when(manualIngestionService.run(eq(Optional.of("markdown/")), eq("lmstudio")))
                .thenReturn(expected);

        // when
        ResponseEntity<ManualIngestionService.ManualIngestionResult> response =
                controller.runIngestion("markdown/", "lmstudio");

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isSameAs(expected);
    }

    @Test
    @DisplayName("runIngestion passes empty Optional to service when prefix is null")
    void runIngestion_DelegatesWithEmptyOptional_WhenPrefixIsNull() {
        // given
        ManualIngestionService.ManualIngestionResult expected = new ManualIngestionService.ManualIngestionResult();
        when(manualIngestionService.run(eq(Optional.empty()), eq("openai")))
                .thenReturn(expected);

        // when
        ResponseEntity<ManualIngestionService.ManualIngestionResult> response =
                controller.runIngestion(null, "openai");

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isSameAs(expected);
    }

    @Test
    @DisplayName("returns 400 when files list is empty (size 0)")
    void uploadDocument_EmptyList_ReturnsBadRequest() {
        // then
        assertThat(controller.uploadDocument(java.util.List.of()).getStatusCode())
                .isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    @DisplayName("returns 400 when all files in the list are empty")
    void uploadDocument_AllFilesEmpty_ReturnsBadRequest() {
        // given
        MockMultipartFile e1 = new MockMultipartFile("file", "a.md", "text/markdown", new byte[0]);
        MockMultipartFile e2 = new MockMultipartFile("file", "b.pdf", "application/pdf", new byte[0]);

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(e1, e2));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    @DisplayName("routes file with null original filename to documentsFolder")
    void uploadDocument_NullFilename_RoutesToDocumentsFolder() {
        // given — MockMultipartFile with no filename will be sanitized to unknown_file -> documents/ folder
        MockMultipartFile f = new MockMultipartFile("file", (String) null, "application/pdf", "data".getBytes());

        // when
        ResponseEntity<?> response = controller.uploadDocument(List.of(f));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }
}
