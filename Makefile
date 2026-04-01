.PHONY: backend-install frontend-install test-backend test-frontend test

backend-install:
	cd backend && python -m pip install -e ".[dev]"

frontend-install:
	cd frontend && npm install

test-backend:
	cd backend && pytest tests/api/test_health.py -q

test-frontend:
	cd frontend && npm test -- --run tests/app/App.test.tsx

test: test-backend test-frontend
