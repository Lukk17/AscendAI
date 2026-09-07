package com.lukk.ascend.ai.agent.service.ingestion;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;

import static org.assertj.core.api.Assertions.assertThat;

class MultipartInputStreamResourceTest {

    @DisplayName("get filename returns constructor value")
    @Test
    void getFilename_ReturnsConstructorValue() {
        // given
        InputStream is = new ByteArrayInputStream("data".getBytes());
        MultipartInputStreamResource res = new MultipartInputStreamResource(is, "doc.pdf");

        // then
        assertThat(res.getFilename()).isEqualTo("doc.pdf");
    }

    @DisplayName("content length returns available when stream supports it")
    @Test
    void contentLength_ReturnsAvailable_WhenStreamSupportsIt() {
        // given
        InputStream is = new ByteArrayInputStream("12345".getBytes());
        MultipartInputStreamResource res = new MultipartInputStreamResource(is, "n");

        // then
        assertThat(res.contentLength()).isEqualTo(5L);
    }

    @DisplayName("content length returns minus one on io exception")
    @Test
    void contentLength_ReturnsMinusOne_OnIOException() {
        // given
        InputStream broken = new InputStream() {
            @Override
            public int read() throws IOException {
                throw new IOException("read fail");
            }

            @Override
            public int available() throws IOException {
                throw new IOException("available fail");
            }
        };
        MultipartInputStreamResource res = new MultipartInputStreamResource(broken, "n");

        // then
        assertThat(res.contentLength()).isEqualTo(-1L);
    }
}
