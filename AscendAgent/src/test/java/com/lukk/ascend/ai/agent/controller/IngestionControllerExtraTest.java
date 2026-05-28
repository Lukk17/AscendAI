package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.properties.IngestionUploadProperties;
import com.lukk.ascend.ai.agent.dto.ApiError;
import com.lukk.ascend.ai.agent.service.ManualIngestionService;
import com.lukk.ascend.ai.agent.service.MimeTypeDetector;
import com.lukk.ascend.ai.agent.service.StorageService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.Spy;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
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
class IngestionControllerExtraTest {

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
    void uploadDocument_ReturnsBadRequest_WhenFilesListIsNull() {
        ResponseEntity<?> response = controller.uploadDocument(null);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).isInstanceOf(ApiError.class);
        assertThat(((ApiError) response.getBody()).error()).isEqualTo("no_file");
    }

    @Test
    void uploadDocument_SkipsEmptyEntries_WhenMixedListProvided() throws IOException {
        // hits the "if (file.isEmpty()) continue;" branch in the loop
        MockMultipartFile empty = new MockMultipartFile("file", "skip.md", "text/markdown", new byte[0]);
        MockMultipartFile good = new MockMultipartFile("file", "ok.md", "text/markdown", "x".getBytes());

        ResponseEntity<?> response = controller.uploadDocument(List.of(empty, good));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        // verify only the good file was uploaded
        org.mockito.Mockito.verify(storageService).uploadFile(eq("markdown/ok.md"), any(), org.mockito.ArgumentMatchers.anyLong());
    }

    @Test
    void uploadDocument_RejectsAllFiles_WithDisallowedMime_Returns415() {
        MockMultipartFile evil = new MockMultipartFile("file", "evil.exe",
                "application/x-msdownload", "MZ".getBytes());

        ResponseEntity<?> response = controller.uploadDocument(List.of(evil));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        assertThat(response.getBody()).isInstanceOf(ApiError.class);
        ApiError err = (ApiError) response.getBody();
        assertThat(err.error()).isEqualTo("unsupported_media_type");
        assertThat(err.message()).contains("disallowed type");
    }

    @Test
    void uploadDocument_CapturesIOException_AndReportsInFailures() throws IOException {
        // Use a file whose getInputStream() throws.
        MultipartFile broken = new MockMultipartFile("file", "broken.pdf", "application/pdf", "data".getBytes()) {
            @Override
            public InputStream getInputStream() throws IOException {
                throw new IOException("disk full");
            }
        };

        ResponseEntity<?> response = controller.uploadDocument(List.of(broken));

        // No file was successfully uploaded → 415 with failures listed.
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        ApiError err = (ApiError) response.getBody();
        assertThat(err.message()).contains("disk full");
    }

    @Test
    void uploadDocument_ReportsIOFailure_AlongsideSuccessfulUploads() throws IOException {
        MockMultipartFile good = new MockMultipartFile("file", "ok.md", "text/markdown", "x".getBytes());
        MultipartFile broken = new MockMultipartFile("file", "boom.pdf", "application/pdf", "data".getBytes()) {
            @Override
            public InputStream getInputStream() throws IOException {
                throw new IOException("io failed");
            }
        };

        ResponseEntity<?> response = controller.uploadDocument(List.of(good, broken));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        com.lukk.ascend.ai.agent.dto.UploadResponse body =
                (com.lukk.ascend.ai.agent.dto.UploadResponse) response.getBody();
        assertThat(body.uploaded()).containsExactly("markdown/ok.md");
        assertThat(body.failures()).hasSize(1);
        assertThat(body.failures().getFirst()).contains("io failed");
    }

    @Test
    void uploadDocument_AcceptsAllMimes_WhenAllowedListIsEmpty() throws IOException {
        uploadProperties.setAllowedMimeTypes(List.of());
        MockMultipartFile any = new MockMultipartFile("file", "x.bin", "application/x-anything", "x".getBytes());

        ResponseEntity<?> response = controller.uploadDocument(List.of(any));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    void uploadDocument_AcceptsAllMimes_WhenAllowedListIsNull() throws IOException {
        uploadProperties.setAllowedMimeTypes(null);
        MockMultipartFile any = new MockMultipartFile("file", "x.bin", "application/x-anything", "x".getBytes());

        ResponseEntity<?> response = controller.uploadDocument(List.of(any));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    }

    @Test
    void runIngestion_DelegatesToService_WithProvidedPrefixAndProvider() {
        ManualIngestionService.ManualIngestionResult expected = new ManualIngestionService.ManualIngestionResult();
        expected.indexed = 3;
        when(manualIngestionService.run(eq(Optional.of("markdown/")), eq("lmstudio")))
                .thenReturn(expected);

        ResponseEntity<ManualIngestionService.ManualIngestionResult> response =
                controller.runIngestion("markdown/", "lmstudio");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isSameAs(expected);
    }

    @Test
    void runIngestion_DelegatesWithEmptyOptional_WhenPrefixIsNull() {
        ManualIngestionService.ManualIngestionResult expected = new ManualIngestionService.ManualIngestionResult();
        when(manualIngestionService.run(eq(Optional.empty()), eq("openai")))
                .thenReturn(expected);

        ResponseEntity<ManualIngestionService.ManualIngestionResult> response =
                controller.runIngestion(null, "openai");

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isSameAs(expected);
    }
}
