## MODIFIED Requirements

### Requirement: The object store is never public

The gateway SHALL have no route to the object store, and the object store SHALL NOT be published on a public interface by any file of this repository. The object store addresses of the agent (`S3_ENDPOINT`, `S3_PUBLIC_ENDPOINT`) and of ascend-ocr (`OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`) SHALL come from the environment with today's local values as defaults. The deployment guide SHALL require both public endpoint variables to equal the private object store address in production, because only containers on the private network follow presigned links. Public clients SHALL download RAG sources through the agent's `GET /api/v1/documents/{id}/content`, so the object store never needs to be public.

#### Scenario: Presigned links point at the private address in production

- **WHEN** a production deployment sets `S3_PUBLIC_ENDPOINT` and `OCR_RESULT_S3_PUBLIC_ENDPOINT` to the private object store address
- **THEN** the agent still reads ascend-ocr results through the presigned link
- **AND** the presigned link does not resolve from outside the VM

#### Scenario: A public client downloads a source through the agent

- **WHEN** a public client fetches the `contentPath` of a source entry through the gateway
- **THEN** the agent streams the document bytes
- **AND** no request of the client reaches the object store
