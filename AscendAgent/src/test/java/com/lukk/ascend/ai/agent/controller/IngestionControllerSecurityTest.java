package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.properties.IngestionUploadProperties;
import com.lukk.ascend.ai.agent.dto.ApiError;
import com.lukk.ascend.ai.agent.service.ManualIngestionService;
import com.lukk.ascend.ai.agent.service.MimeTypeDetector;
import com.lukk.ascend.ai.agent.service.StorageService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
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
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

@ExtendWith(MockitoExtension.class)
class IngestionControllerSecurityTest {

    @Mock
    private StorageService storageService;

    @Mock
    private ManualIngestionService manualIngestionService;

    @Mock
    private MimeTypeDetector mimeTypeDetector;

    @Spy
    private IngestionUploadProperties uploadProperties = new IngestionUploadProperties();

    @InjectMocks
    private IngestionController ingestionController;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(ingestionController, "markdownFolder", "markdown");
        ReflectionTestUtils.setField(ingestionController, "documentsFolder", "documents");
        uploadProperties.setAllowedMimeTypes(
                List.of("text/markdown", "text/plain", "application/pdf"));
        lenient().when(mimeTypeDetector.detect(any(MultipartFile.class), anyString()))
                .thenAnswer(inv -> {
                    MultipartFile mf = inv.getArgument(0);
                    return mf.getContentType() != null ? mf.getContentType().toLowerCase() : "application/octet-stream";
                });
    }

    @Test
    @DisplayName("returns 415 when content type is not in the allowlist")
    void uploadDocument_WhenContentTypeNotInAllowlist_Returns415() {
        // given
        MockMultipartFile file = new MockMultipartFile("file", "evil.zip",
                "application/zip", "evil_payload".getBytes());

        // when
        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(file));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        assertThat(response.getBody()).isNotNull().isInstanceOf(ApiError.class);
        ApiError body = (ApiError) response.getBody();
        assertThat(body.message()).contains("application/zip");
        verifyNoInteractions(storageService);
    }

    @Test
    @DisplayName("sanitizes path traversal filename to a safe storage key")
    void uploadDocument_WhenFilenameContainsPathTraversal_SanitizedToSafeKey() throws IOException {
        // given
        MockMultipartFile file = new MockMultipartFile("file", "../../etc/passwd.txt",
                "text/plain", "content".getBytes());

        // when
        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(file));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        verify(storageService).uploadFile(keyCaptor.capture(), any(), anyLong());
        String storedKey = keyCaptor.getValue();
        assertThat(storedKey).startsWith("documents/");
        assertThat(storedKey.substring("documents/".length())).doesNotContain("/");
        assertThat(storedKey).doesNotContain("/etc/");
    }

    @Test
    @DisplayName("replaces Unicode and control characters in filename with safe equivalents")
    void uploadDocument_WhenFilenameHasUnicodeOrControlChars_SanitizedToUnderscores() throws IOException {
        // given
        MockMultipartFile file = new MockMultipartFile("file", " evil‮.md",
                "text/markdown", "content".getBytes());

        // when
        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(file));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        ArgumentCaptor<String> keyCaptor = ArgumentCaptor.forClass(String.class);
        verify(storageService).uploadFile(keyCaptor.capture(), any(), anyLong());
        String storedKey = keyCaptor.getValue();
        assertThat(storedKey).doesNotContain("‮");
        assertThat(storedKey).startsWith("markdown/");
        assertThat(storedKey).matches("markdown/[A-Za-z0-9._-]+");
    }
}
