package com.lukk.ascend.ai.agent.service.chat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AssembledSystemMessagesTest {

    @Test
    @DisplayName("hasDynamic returns false when dynamicSuffix is blank")
    void hasDynamic_BlankSuffix_ReturnsFalse() {
        // given
        AssembledSystemMessages msgs = new AssembledSystemMessages("static", "  ");

        // then
        assertThat(msgs.hasDynamic()).isFalse();
        assertThat(msgs.combined()).isEqualTo("static");
    }

    @Test
    @DisplayName("hasDynamic returns true and combined joins prefix + suffix when dynamicSuffix has content")
    void hasDynamic_NonBlankSuffix_ReturnsTrueAndCombines() {
        // given
        AssembledSystemMessages msgs = new AssembledSystemMessages("static", "dynamic content");

        // then
        assertThat(msgs.hasDynamic()).isTrue();
        assertThat(msgs.combined()).isEqualTo("static\n\ndynamic content");
    }
}
