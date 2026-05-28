package com.lukk.ascend.ai.agent.dto;

/**
 * Standard JSON error body for controller-thrown failures so the response
 * stays consistent with the {@code produces=application/json} contract on
 * every controller.
 *
 * @param status  HTTP status code reflected in the response line
 * @param error   short error code (e.g. "unsupported_media_type")
 * @param message human-readable detail explaining what went wrong
 */
public record ApiError(int status, String error, String message) {
}
