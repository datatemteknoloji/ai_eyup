# Testing

100% test coverage is the key to great vibe coding. Tests let you move fast, trust your instincts, and ship with confidence — without them, vibe coding is just yolo coding. With tests, it's a superpower.

## Frameworks

| Layer | Framework | Version |
|-------|-----------|---------|
| Frontend | Vitest + @testing-library/react | 1.6.x |
| Backend | pytest + pytest-asyncio | 9.0.x / 0.24.x |

---

## How to Run Tests

### Backend (pytest)

```bash
# Run all backend tests inside the running container
docker exec -e PYTHONPATH=/app -w /app server_management_backend python3 -m pytest app/tests/ -v

# Run a specific test file
docker exec -e PYTHONPATH=/app -w /app server_management_backend python3 -m pytest app/tests/test_auth.py -v
```

Test files live in: `backend/app/tests/`

### Frontend (Vitest)

```bash
# Run all frontend tests (uses temporary node:20 container — node is not installed on host)
docker run --rm -v $(pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install --legacy-peer-deps && npm test"

# Watch mode (interactive)
docker run --rm -v $(pwd)/frontend:/app -w /app node:20-alpine sh -c "npm install --legacy-peer-deps && npm run test:watch"
```

Test files live in: `frontend/src/test/` and alongside components as `*.test.tsx`

---

## Test Layers

### Unit Tests
- **What:** Pure functions, business logic, security utilities (e.g. JWT revocation, token creation)
- **Where:** `backend/app/tests/test_*.py` / `frontend/src/test/*.test.tsx`
- **When:** Every function with a conditional branch or error path

### Integration Tests
- **What:** API endpoints end-to-end, database writes, auth flows
- **Where:** `backend/app/tests/test_api_*.py`
- **When:** New endpoints, permission changes, data model changes

### Component Tests
- **What:** React component render, user interaction, error states
- **Where:** `frontend/src/test/*.test.tsx`
- **When:** New components, interactive behavior, error boundaries

---

## Conventions

### Backend (pytest)
- File naming: `test_{feature}.py`
- Classes: `class TestFeatureName:` (no inheritance needed)
- Fixtures: defined in `conftest.py`
- Mocks: `unittest.mock.patch` or `MagicMock`
- Assertions: plain `assert` statements

### Frontend (Vitest + @testing-library)
- File naming: `ComponentName.test.tsx` in `src/test/`
- Imports: `describe`, `it`, `expect`, `vi` from `vitest`
- Rendering: `render()` from `@testing-library/react`
- Queries: prefer `getByRole`, `getByText` over `getByTestId`
- Mocking: `vi.spyOn()` for console/external calls

---

## Test Expectations

- 100% test coverage is the goal
- When writing new functions → write a corresponding test
- When fixing a bug → write a regression test before the fix
- When adding error handling → write a test that triggers the error
- When adding a conditional (if/else) → test BOTH paths
- Never commit code that makes existing tests fail
