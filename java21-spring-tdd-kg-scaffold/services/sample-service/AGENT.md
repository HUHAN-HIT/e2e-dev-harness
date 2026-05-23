# Sample Service Agent Instructions

These instructions apply to `services/sample-service`.

## Service Boundary

- This service is a sample Spring 6 MVC service.
- Keep sample behavior small and easy to replace.
- Do not add persistence, messaging, or security dependencies unless a clarified use case requires them.

## Testing

- Prefer plain JUnit tests for domain and application-service behavior.
- Add Spring MVC tests only for request/response mapping, validation, serialization, or controller wiring.
- Use `mvn -pl services/sample-service -am test` for service-scoped verification.

## Implementation

- Keep controller methods thin.
- Keep business calculation logic outside the controller.
- Do not expand the sample API surface without updating the design and test plan.
