package com.lukk.ascend.ai.agent.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.util.MimeType;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ChatExecutorImageTest {

    private final ChatExecutor chatExecutor = new ChatExecutor(null, null, null);

    static Stream<Arguments> mimeResolutionCases() {
        return Stream.of(
                Arguments.of("null content type, jpg filename",
                        null, "photo.jpg", "image/jpeg"),
                Arguments.of("blank content type, png filename",
                        "", "photo.png", "image/png"),
                Arguments.of("malformed 'file' content type, webp filename",
                        "file", "photo.webp", "image/webp"),
                Arguments.of("octet-stream content type, gif filename",
                        "application/octet-stream", "photo.gif", "image/gif"),
                Arguments.of("valid jpeg content type takes precedence",
                        "image/jpeg", "photo.png", "image/jpeg"),
                Arguments.of("parameterized jpeg content type",
                        "image/jpeg; charset=utf-8", "photo.bin", "image/jpeg")
        );
    }

    @ParameterizedTest(name = "[{index}] {0}")
    @MethodSource("mimeResolutionCases")
    void resolveImageMimeType_HandlesVariousInputs(String description,
                                                   String contentType,
                                                   String filename,
                                                   String expectedMime) {
        MultipartFile file = new MockMultipartFile("file", filename, contentType, new byte[]{1, 2, 3});

        MimeType resolved = chatExecutor.resolveImageMimeType(file);

        assertThat(resolved).isNotNull();
        assertThat(resolved.toString()).startsWith(expectedMime);
        assertThat(resolved.getType()).isEqualTo(expectedMime.split("/")[0]);
        assertThat(resolved.getSubtype()).isEqualTo(expectedMime.split("/")[1]);
    }

    @Test
    void resolveImageMimeType_WhenNoContentTypeAndNoFilename_ThenDefaultsToImagePng() {
        MultipartFile file = new MockMultipartFile("file", null, null, new byte[]{1});

        MimeType resolved = chatExecutor.resolveImageMimeType(file);

        assertThat(resolved).isNotNull();
        assertThat(resolved.toString()).isEqualTo("image/png");
    }

    @Test
    void resolveImageMimeType_NeverThrows_ForBrokenContentTypeAndUnknownExtension() {
        MultipartFile file = new MockMultipartFile("file", "noext_file", "garbage", new byte[]{1});

        assertThatCode(() -> chatExecutor.resolveImageMimeType(file)).doesNotThrowAnyException();

        MimeType resolved = chatExecutor.resolveImageMimeType(file);
        assertThat(resolved.toString()).isEqualTo("image/png");
    }

    /**
     * Hits the {@code catch (InvalidMimeTypeException)} fallback at line 121:
     * Content-Type passes the upstream guards (has text, contains '/', not octet-stream)
     * but Spring's MimeType parser still rejects it, so we must fall back to the filename.
     */
    @ParameterizedTest(name = "[{index}] malformed content-type ''{0}'' falls back to filename")
    @ValueSource(strings = {"foo/", "/bar", "foo/bar/baz"})
    void resolveImageMimeType_WhenContentTypeRejectedByParser_FallsBackToFilename(String malformedContentType) {
        MultipartFile file = new MockMultipartFile("file", "photo.jpg", malformedContentType, new byte[]{1});

        MimeType resolved = chatExecutor.resolveImageMimeType(file);

        assertThat(resolved).isEqualTo(org.springframework.util.MimeTypeUtils.IMAGE_JPEG);
    }

    @Test
    void extractToolsUsed_ReturnsEmptyList_WhenChatResponseGetResultThrows() {
        ChatResponse chatResponse = mock(ChatResponse.class);
        when(chatResponse.getResult()).thenThrow(new IllegalStateException("ChatResponse internals unavailable"));

        List<String> tools = chatExecutor.extractToolsUsed(chatResponse);

        assertThat(tools).isEmpty();
    }

    @Test
    void extractToolsUsed_ReturnsEmptyList_WhenToolCallNamesThrow() {
        ChatResponse chatResponse = mock(ChatResponse.class);
        Generation generation = mock(Generation.class);
        AssistantMessage assistant = mock(AssistantMessage.class);
        when(chatResponse.getResult()).thenReturn(generation);
        when(generation.getOutput()).thenReturn(assistant);
        when(assistant.getToolCalls()).thenThrow(new RuntimeException("tool calls unavailable"));

        List<String> tools = chatExecutor.extractToolsUsed(chatResponse);

        assertThat(tools).isEmpty();
    }
}
