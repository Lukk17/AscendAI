"""
Consumer-driven contract stub for the ascend-ai-agent <-> ascend-ocr REST + MCP boundary.

The /tdd-workflow skill mandates Pact contract tests for HTTP APIs consumed by external services. ascend-ai-agent
is the consumer of ascend-ocr's `/v1/ocr` and the MCP `ocr_process` tool. This module defines the consumer-side
contract shape that ascend-ai-agent expects.

The actual Pact provider verification job runs against this contract file on the ascend-ocr side; the consumer
contract is published from the ascend-ai-agent build. This stub holds the shape so the contract surface is
discoverable in the test tree and the verification job can be wired without a redesign.
"""

import pytest


@pytest.mark.skip(reason="Provider verification runs only when pact broker URL is configured in CI")
class TestAscendAiAgentPactContract:
    def test_rest_v1_ocr_response_shape(self):
        # Given a successful upload, the ascend-ai-agent consumer expects:
        #   200 OK
        #   {
        #     "schema_version": "1",
        #     "filename": <string>,
        #     "language": <string matching [a-z]{2,5}>,
        #     "pages": [
        #       {"page_number": int >= 1, "lines": [...]},
        #       ...
        #     ],
        #     "processing_time_seconds": <number >= 0>
        #   }
        # When the provider returns this shape, verification passes.
        pass

    def test_rest_v1_ocr_error_shape(self):
        # Given a 4xx/5xx, the ascend-ai-agent expects:
        #   {"code": "<stable code>", "detail": "<generic phrase>"}
        # Where code in {OCR_FAILED, FILE_TOO_LARGE, UNSUPPORTED_FILE_TYPE, UNSAFE_URI,
        #                DOWNLOAD_FAILED, INTERNAL_ERROR}.
        pass

    def test_mcp_ocr_process_result_shape(self):
        # Given a successful MCP tools/call for ocr_process, the ascend-ai-agent consumer expects:
        #   result.content[0] of type=text, text parses as JSON matching OcrJsonResponse.
        pass

    def test_mcp_ocr_process_error_shape(self):
        # Given an MCP failure, the ascend-ai-agent consumer expects:
        #   JSON-RPC error frame OR result.isError=true with a code matching the catalog.
        pass
