package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.properties.IngestionUploadProperties;
import com.lukk.ascend.ai.agent.dto.UploadResponse;
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
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class IngestionControllerTest {

    @Mock
    private StorageService storageService;

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
        uploadProperties.setAllowedMimeTypes(List.of(
                "application/pdf", "text/markdown", "text/plain", "image/png", "image/jpeg",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"));
        lenient().when(mimeTypeDetector.detect(any(MultipartFile.class), anyString()))
                .thenAnswer(inv -> {
                    MultipartFile mf = inv.getArgument(0);
                    return mf.getContentType() != null ? mf.getContentType().toLowerCase() : "application/octet-stream";
                });
    }

    @Test
    void uploadDocument_ShouldUploadToMarkdown_WhenFileIsMd() throws IOException {
        MockMultipartFile file = new MockMultipartFile("file", "test.md", "text/markdown", "content".getBytes());

        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(file));

        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(storageService).uploadFile(eq("markdown/test.md"), any(), anyLong());
    }

    @Test
    void uploadDocument_ShouldUploadToDocuments_WhenFileIsNotMd() throws IOException {
        MockMultipartFile file = new MockMultipartFile("file", "test.pdf", "application/pdf", "content".getBytes());

        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(file));

        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(storageService).uploadFile(eq("documents/test.pdf"), any(), anyLong());
    }

    @Test
    void uploadDocument_ShouldReturnBadRequest_WhenFileIsEmpty() {
        MockMultipartFile file = new MockMultipartFile("file", "test.txt", "text/plain", "".getBytes());

        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(file));

        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
    }

    @Test
    void uploadDocument_ShouldUploadAllFiles_WhenMultipleProvided() throws IOException {
        MockMultipartFile md = new MockMultipartFile("file", "notes.md", "text/markdown", "md".getBytes());
        MockMultipartFile pdf = new MockMultipartFile("file", "report.pdf", "application/pdf", "pdf".getBytes());
        MockMultipartFile docx = new MockMultipartFile("file", "recipe.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx".getBytes());

        ResponseEntity<?> response = ingestionController.uploadDocument(List.of(md, pdf, docx));

        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(storageService).uploadFile(eq("markdown/notes.md"), any(), anyLong());
        verify(storageService).uploadFile(eq("documents/report.pdf"), any(), anyLong());
        verify(storageService).uploadFile(eq("documents/recipe.docx"), any(), anyLong());
        UploadResponse body = (UploadResponse) response.getBody();
        assertThat(body.uploaded()).containsExactly("markdown/notes.md", "documents/report.pdf", "documents/recipe.docx");
        assertThat(body.failures()).isEmpty();
    }
}
