import os
APP_ENV = os.getenv("APP_ENV", "development")
ENABLE_SANDBOX = os.getenv("ENABLE_SANDBOX", "true").lower() == "true"
CORS_ORIGINS = [s.strip() for s in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",") if s.strip()]
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sandbox.db")
