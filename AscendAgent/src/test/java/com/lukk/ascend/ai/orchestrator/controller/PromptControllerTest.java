package com.lukk.ascend.ai.orchestrator.controller;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.service.ChatOrchestratorService;
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
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PromptControllerTest {

    @Mock
    private ChatOrchestratorService chatOrchestratorService;

    @Mock
    private MultipartFile image;

    @Mock
    private MultipartFile document;

    @InjectMocks
    private PromptController promptController;

    @Test
    void prompt_shouldReturnAiResponse() {
        // given
        String prompt = "test prompt";
        String responseText = "AI Response";
        AiResponse aiResponse = new AiResponse(responseText, null);
        ReflectionTestUtils.setField(promptController, "defaultUserId", "user1");

        when(chatOrchestratorService.prompt(anyString(), any(), any(), anyString(), any(), any(), any()))
                .thenReturn(aiResponse);

        // when
        ResponseEntity<AiResponse> response = promptController.prompt(prompt, null, null, null, null, null, "user1");

        // then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(responseText, response.getBody().content());
    }

    @Test
    void prompt_shouldThrowException_whenServiceFails() {
        // given
        String prompt = "test prompt";
        ReflectionTestUtils.setField(promptController, "defaultUserId", "user1");

        when(chatOrchestratorService.prompt(anyString(), any(), any(), anyString(), any(), any(), any()))
                .thenThrow(new RuntimeException("Service Error"));

        // then
        assertThrows(RuntimeException.class, () -> promptController.prompt(prompt, null, null, null, null, null, "user1"));
    }
}
