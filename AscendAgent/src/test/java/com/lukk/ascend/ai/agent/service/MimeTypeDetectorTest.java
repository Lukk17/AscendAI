package com.lukk.ascend.ai.agent.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;

import static org.assertj.core.api.Assertions.assertThat;

class MimeTypeDetectorTest {

    private MimeTypeDetector detector;

    @BeforeEach
    void setUp() {
        detector = new MimeTypeDetector();
    }

    @Test
    void detect_PdfBytes_ReturnsPdfMime() {
        byte[] pdfBytes = "%PDF-1.4\n%âãÏÓ\nfake pdf body".getBytes();
        MockMultipartFile file = new MockMultipartFile("file", "test.pdf", "application/octet-stream", pdfBytes);

        String result = detector.detect(file, "test.pdf");

        assertThat(result).isEqualTo("application/pdf");
    }

    @Test
    void detect_PngBytes_ReturnsPngMime() {
        byte[] pngBytes = new byte[]{(byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
                0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52};
        MockMultipartFile file = new MockMultipartFile("file", "image.png", "image/png", pngBytes);

        String result = detector.detect(file, "image.png");

        assertThat(result).isEqualTo("image/png");
    }

    @Test
    void detect_JpegBytes_ReturnsJpegMime() {
        byte[] jpegBytes = new byte[]{(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, (byte) 0xE0,
                0x00, 0x10, 'J', 'F', 'I', 'F', 0x00};
        MockMultipartFile file = new MockMultipartFile("file", "photo.jpg", "image/jpeg", jpegBytes);

        String result = detector.detect(file, "photo.jpg");

        assertThat(result).isEqualTo("image/jpeg");
    }

    @Test
    void detect_PlainText_ReturnsTextPlainMime() {
        MockMultipartFile file = new MockMultipartFile("file", "notes.txt", "text/plain",
                "Just some plain text content.\n".getBytes());

        String result = detector.detect(file, "notes.txt");

        assertThat(result).startsWith("text/");
    }

    @Test
    void detect_MarkdownByExtension_ReturnsTextual() {
        MockMultipartFile file = new MockMultipartFile("file", "notes.md", "text/markdown",
                "# Heading\n\nbody\n".getBytes());

        String result = detector.detect(file, "notes.md");

        assertThat(result).startsWith("text/");
    }

    @Test
    void detect_ZipDisguisedAsPdf_StillDetectedAsZip() {
        // Tika trusts the bytes, not the client header
        byte[] zipBytes = new byte[]{0x50, 0x4B, 0x03, 0x04, 0x14, 0x00, 0x00, 0x00};
        MockMultipartFile file = new MockMultipartFile("file", "evil.pdf", "application/pdf", zipBytes);

        String result = detector.detect(file, "evil.pdf");

        assertThat(result).contains("zip");
    }

    @Test
    void detect_EmptyBytesWithFilenameHint_FallsBackToFilenameDetection() {
        MockMultipartFile file = new MockMultipartFile("file", "empty.txt", "text/plain", new byte[0]);

        String result = detector.detect(file, "empty.txt");

        // Tika without bytes will use the filename hint or return generic — assert non-null lowercase
        assertThat(result).isNotBlank().isEqualTo(result.toLowerCase());
    }
}
