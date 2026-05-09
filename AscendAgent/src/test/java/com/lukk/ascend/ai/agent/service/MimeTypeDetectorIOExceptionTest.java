package com.lukk.ascend.ai.agent.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MimeTypeDetectorIOExceptionTest {

    private final MimeTypeDetector detector = new MimeTypeDetector();

    @Test
    void detect_FallsBackToContentType_WhenInputStreamThrows() throws IOException {
        MultipartFile file = mock(MultipartFile.class);
        when(file.getInputStream()).thenThrow(new IOException("read fail"));
        when(file.getContentType()).thenReturn("application/PDF");

        String result = detector.detect(file, "doc.pdf");

        assertThat(result).isEqualTo("application/pdf");
    }

    @Test
    void detect_FallsBackToOctetStream_WhenInputStreamThrowsAndContentTypeNull() throws IOException {
        MultipartFile file = mock(MultipartFile.class);
        when(file.getInputStream()).thenThrow(new IOException("read fail"));
        when(file.getContentType()).thenReturn(null);

        String result = detector.detect(file, "n");

        assertThat(result).isEqualTo("application/octet-stream");
    }

    @Test
    void detect_PassesNullSanitizedFilenameToTika_WithoutNPE() throws IOException {
        MultipartFile file = mock(MultipartFile.class);
        when(file.getInputStream()).thenReturn(InputStream.nullInputStream());

        String result = detector.detect(file, null);

        assertThat(result).isNotNull().contains("/");
    }
}
