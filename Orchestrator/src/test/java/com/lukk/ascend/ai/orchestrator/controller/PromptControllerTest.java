package com.lukk.ascend.ai.orchestrator.controller;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.dto.PromptRequest;
import com.lukk.ascend.ai.orchestrator.service.AiConnectionService;
import com.lukk.ascend.ai.orchestrator.test.TestDummyBuilder;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PromptControllerTest {

    @Mock
    private AiConnectionService aiConnectionService;

    @InjectMocks
    private PromptController promptController;

    @Test
    void getAiResponse_ShouldReturnOk_WhenServiceSucceeds() {
        // given
        PromptRequest request = TestDummyBuilder.createPromptRequest();
        AiResponse mockResponse = TestDummyBuilder.createAiResponse();
        ReflectionTestUtils.setField(promptController, "defaultUserId", "user1");

        when(aiConnectionService.prompt(anyString(), anyString())).thenReturn(mockResponse);

        // when
        ResponseEntity<AiResponse> response = promptController.getAiResponse(request);

        // then
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertEquals(mockResponse, response.getBody());
    }

    @Test
    void getAiResponse_ShouldPropagateException_WhenServiceFails() {
        // given
        PromptRequest request = TestDummyBuilder.createPromptRequest();
        ReflectionTestUtils.setField(promptController, "defaultUserId", "user1");

        when(aiConnectionService.prompt(anyString(), anyString())).thenThrow(new RuntimeException("Service Error"));

        // when & then
        assertThrows(RuntimeException.class, () -> promptController.getAiResponse(request));
    }
}
