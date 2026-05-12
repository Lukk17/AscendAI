package com.lukk.ascend.ai.agent.service.ingestion;

import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;

import static org.assertj.core.api.Assertions.assertThat;

class MultipartInputStreamResourceTest {

    @Test
    void getFilename_ReturnsConstructorValue() {
        InputStream is = new ByteArrayInputStream("data".getBytes());

        MultipartInputStreamResource res = new MultipartInputStreamResource(is, "doc.pdf");

        assertThat(res.getFilename()).isEqualTo("doc.pdf");
    }

    @Test
    void contentLength_ReturnsAvailable_WhenStreamSupportsIt() {
        InputStream is = new ByteArrayInputStream("12345".getBytes());

        MultipartInputStreamResource res = new MultipartInputStreamResource(is, "n");

        assertThat(res.contentLength()).isEqualTo(5L);
    }

    @Test
    void contentLength_ReturnsMinusOne_OnIOException() {
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

        assertThat(res.contentLength()).isEqualTo(-1L);
    }
}
