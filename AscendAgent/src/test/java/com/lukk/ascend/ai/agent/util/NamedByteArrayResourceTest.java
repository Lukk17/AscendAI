package com.lukk.ascend.ai.agent.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class NamedByteArrayResourceTest {

    @DisplayName("get filename returns constructor value")
    @Test
    void getFilename_ReturnsConstructorValue() {
        // given
        byte[] bytes = "hello".getBytes();
        NamedByteArrayResource resource = new NamedByteArrayResource(bytes, "report.pdf");

        // then
        assertThat(resource.getFilename()).isEqualTo("report.pdf");
        assertThat(resource.getByteArray()).isEqualTo(bytes);
        assertThat(resource.contentLength()).isEqualTo(5L);
    }
}
