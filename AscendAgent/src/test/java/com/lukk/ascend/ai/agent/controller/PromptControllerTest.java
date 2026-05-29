package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.service.AscendChatService;
import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.multipart.MultipartFile;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PromptControllerTest {

    @Mock
    private AscendChatService ascendChatService;

    @Mock
    private MultipartFile image;

    @Mock
    private MultipartFile document;

    @InjectMocks
    private PromptController promptController;

    @DisplayName("prompt should return ai response")
    @Test
    void prompt_shouldReturnAiResponse() {
        // given
        String prompt = "test prompt";
        String responseText = "AI Response";
        AiResponse aiResponse = new AiResponse(responseText, null);
        ReflectionTestUtils.setField(promptController, "defaultUserId", TestConstants.DEFAULT_USER_ID);

        when(ascendChatService.prompt(anyString(), any(), any(), anyString(), any(), any(), any(), anyBoolean(), any()))
                .thenReturn(aiResponse);

        // when
        ResponseEntity<?> response = promptController.prompt(prompt, null, null, null, null, null, null, null, null, TestConstants.DEFAULT_USER_ID);

        // then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(responseText, ((AiResponse) response.getBody()).content());
    }

    @DisplayName("prompt should throw exception when service fails")
    @Test
    void prompt_shouldThrowException_whenServiceFails() {
        // given
        String prompt = "test prompt";
        ReflectionTestUtils.setField(promptController, "defaultUserId", TestConstants.DEFAULT_USER_ID);

        when(ascendChatService.prompt(anyString(), any(), any(), anyString(), any(), any(), any(), anyBoolean(), any()))
                .thenThrow(new RuntimeException("Service Error"));

        // then
        assertThrows(RuntimeException.class, () -> promptController.prompt(prompt, null, null, null, null, null, null, null, null, TestConstants.DEFAULT_USER_ID));
    }
}
