package com.lukk.ascend.ai.agent.dto;

public record ApiError(int status, String error, String message) {
}
