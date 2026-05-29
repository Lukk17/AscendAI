package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.dto.ApiError;
import com.lukk.ascend.ai.agent.service.AscendChatService;
import com.lukk.ascend.ai.agent.service.VisionCapabilityResolver;
import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PromptControllerVisionTest {

    @Mock
    private AscendChatService ascendChatService;

    @Mock
    private VisionCapabilityResolver visionCapabilityResolver;

    @InjectMocks
    private PromptController promptController;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(promptController, "defaultUserId", TestConstants.DEFAULT_USER_ID);
    }

    @DisplayName("prompt with image and vision capable provider returns200")
    @Test
    void prompt_WithImageAndVisionCapableProvider_Returns200() {
        // given
        MockMultipartFile image = new MockMultipartFile("image", "cat.png", "image/png", "img".getBytes());
        when(visionCapabilityResolver.supportsImages("anthropic", "claude-sonnet-4-6")).thenReturn(true);
        when(ascendChatService.prompt(anyString(), any(), any(), anyString(), any(), any(), any(), anyBoolean(), any()))
                .thenReturn(new AiResponse("ok", null));

        // when
        ResponseEntity<?> response = promptController.prompt(
                "describe", image, null, "anthropic", "claude-sonnet-4-6", null, null, null, null, TestConstants.DEFAULT_USER_ID);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isInstanceOf(AiResponse.class);
    }

    @DisplayName("prompt with image and non vision provider returns415")
    @Test
    void prompt_WithImageAndNonVisionProvider_Returns415() {
        // given
        MockMultipartFile image = new MockMultipartFile("image", "cat.png", "image/png", "img".getBytes());
        when(visionCapabilityResolver.supportsImages("minimax", "MiniMax-M2.7")).thenReturn(false);

        // when
        ResponseEntity<?> response = promptController.prompt(
                "describe", image, null, "minimax", "MiniMax-M2.7", null, null, null, null, TestConstants.DEFAULT_USER_ID);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNSUPPORTED_MEDIA_TYPE);
        ApiError body = (ApiError) response.getBody();
        assertThat(body).isNotNull();
        assertThat(body.error()).isEqualTo("vision_unsupported");
        assertThat(body.message()).contains("does not support image input");
        verifyNoInteractions(ascendChatService);
    }

    @DisplayName("prompt without image always returns200 regardless of provider")
    @Test
    void prompt_WithoutImage_AlwaysReturns200_RegardlessOfProvider() {
        // given
        when(ascendChatService.prompt(anyString(), any(), any(), anyString(), any(), any(), any(), anyBoolean(), any()))
                .thenReturn(new AiResponse("ok", null));

        // when
        ResponseEntity<?> response = promptController.prompt(
                "hello", null, null, "minimax", "MiniMax-M2.7", null, null, null, null, TestConstants.DEFAULT_USER_ID);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        verifyNoInteractions(visionCapabilityResolver);
    }
}
