package com.lukk.ascend.ai.orchestrator.controller;

import com.lukk.ascend.ai.orchestrator.service.StorageService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.IOException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class IngestionControllerTest {

    @Mock
    private StorageService storageService;

    @InjectMocks
    private IngestionController ingestionController;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(ingestionController, "obsidianFolder", "obsidian");
        ReflectionTestUtils.setField(ingestionController, "documentsFolder", "documents");
    }

    @Test
    void uploadDocument_ShouldUploadToObsidian_WhenFileIsMd() throws IOException {
        // given
        MockMultipartFile file = new MockMultipartFile("file", "test.md", "text/markdown", "content".getBytes());

        // when
        ResponseEntity<String> response = ingestionController.uploadDocument(file);

        // then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(storageService).uploadFile(eq("obsidian/test.md"), any(), anyLong());
    }

    @Test
    void uploadDocument_ShouldUploadToDocuments_WhenFileIsNotMd() throws IOException {
        // given
        MockMultipartFile file = new MockMultipartFile("file", "test.pdf", "application/pdf", "content".getBytes());

        // when
        ResponseEntity<String> response = ingestionController.uploadDocument(file);

        // then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        verify(storageService).uploadFile(eq("documents/test.pdf"), any(), anyLong());
    }

    @Test
    void uploadDocument_ShouldReturnBadRequest_WhenFileIsEmpty() {
        // given
        MockMultipartFile file = new MockMultipartFile("file", "test.txt", "text/plain", "".getBytes());

        // when
        ResponseEntity<String> response = ingestionController.uploadDocument(file);

        // then
        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
    }
}
