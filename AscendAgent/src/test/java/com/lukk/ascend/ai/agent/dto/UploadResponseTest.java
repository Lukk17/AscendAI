package com.lukk.ascend.ai.agent.dto;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class UploadResponseTest {

    @Test
    void accessors_ReturnConstructedValues() {
        UploadResponse r = new UploadResponse(List.of("a"), List.of("b"));

        assertThat(r.uploaded()).containsExactly("a");
        assertThat(r.failures()).containsExactly("b");
    }

    @Test
    void equalsAndHashCode_AreSymmetric() {
        UploadResponse a = new UploadResponse(List.of("a"), List.of());
        UploadResponse b = new UploadResponse(List.of("a"), List.of());

        assertThat(a).isEqualTo(b);
        assertThat(b).isEqualTo(a);
        assertThat(a.hashCode()).isEqualTo(b.hashCode());
        assertThat(a).isNotEqualTo(new UploadResponse(List.of(), List.of()));
        assertThat(a).isNotEqualTo(null);
    }
}
