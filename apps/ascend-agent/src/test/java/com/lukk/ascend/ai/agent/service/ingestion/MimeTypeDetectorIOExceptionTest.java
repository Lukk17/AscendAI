package com.lukk.ascend.ai.agent.service.ingestion;

import org.junit.jupiter.api.DisplayName;
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

    @DisplayName("detect falls back to content type when input stream throws")
    @Test
    void detect_FallsBackToContentType_WhenInputStreamThrows() throws IOException {
        // given
        MultipartFile file = mock(MultipartFile.class);
        when(file.getInputStream()).thenThrow(new IOException("read fail"));
        when(file.getContentType()).thenReturn("application/PDF");

        // when
        String result = detector.detect(file, "doc.pdf");

        // then
        assertThat(result).isEqualTo("application/pdf");
    }

    @DisplayName("detect falls back to octet stream when input stream throws and content type null")
    @Test
    void detect_FallsBackToOctetStream_WhenInputStreamThrowsAndContentTypeNull() throws IOException {
        // given
        MultipartFile file = mock(MultipartFile.class);
        when(file.getInputStream()).thenThrow(new IOException("read fail"));
        when(file.getContentType()).thenReturn(null);

        // when
        String result = detector.detect(file, "n");

        // then
        assertThat(result).isEqualTo("application/octet-stream");
    }

    @DisplayName("detect passes null sanitized filename to tika without npe")
    @Test
    void detect_PassesNullSanitizedFilenameToTika_WithoutNPE() throws IOException {
        // given
        MultipartFile file = mock(MultipartFile.class);
        when(file.getInputStream()).thenReturn(InputStream.nullInputStream());

        // when
        String result = detector.detect(file, null);

        // then
        assertThat(result).isNotNull().contains("/");
    }
}
