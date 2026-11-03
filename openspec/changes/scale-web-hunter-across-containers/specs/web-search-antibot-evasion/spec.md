## ADDED Requirements

### Requirement: The inbound limit keys on the caller in front of the edge proxy

Behind the edge proxy, each copy SHALL take the caller's address from the `X-Forwarded-For` header the proxy writes, so
the inbound per caller limit counts the real caller and not the proxy. A caller SHALL NOT be able to choose its own key
by sending `X-Forwarded-For` to the proxy.

#### Scenario: Two callers behind one proxy

- **WHEN** two callers with different addresses send requests through the edge proxy
- **THEN** each has its own rate limit budget

#### Scenario: A forged header

- **WHEN** a caller sends its own `X-Forwarded-For` value to the edge proxy
- **THEN** its requests count against its real address
