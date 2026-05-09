package com.lukk.ascend.ai.agent.util;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class NamedByteArrayResourceTest {

    @Test
    void getFilename_ReturnsConstructorValue() {
        byte[] bytes = "hello".getBytes();

        NamedByteArrayResource resource = new NamedByteArrayResource(bytes, "report.pdf");

        assertThat(resource.getFilename()).isEqualTo("report.pdf");
        assertThat(resource.getByteArray()).isEqualTo(bytes);
        assertThat(resource.contentLength()).isEqualTo(5L);
    }
}
