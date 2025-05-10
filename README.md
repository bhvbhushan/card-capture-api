# Card Capture Backend

This is the backend service for the Card Capture application, built with FastAPI and following clean architecture principles.

## Project Structure

```
app/
├── api/            # API route definitions and versioning
├── controllers/    # Request handlers and response formatting
├── core/          # Core application components and configurations
├── models/        # Data models and schemas
├── repositories/  # Database access layer
├── services/      # Business logic layer
├── utils/         # Utility functions and helpers
├── worker/        # Background task workers
├── uploads/       # Temporary storage for uploaded files
├── config.py      # Application configuration
└── main.py        # Application entry point
```

### Directory Details

#### `/api`
- API route definitions
- API versioning
- Route grouping and organization
- OpenAPI/Swagger documentation

#### `/controllers`
- Request handling
- Input validation
- Response formatting
- Route-specific logic
- Error handling at the API level

#### `/core`
- Database connections
- External service clients
- Middleware
- Authentication
- Core application setup

#### `/models`
- Pydantic models
- Database models
- Data transfer objects (DTOs)
- Type definitions
- Schema validations

#### `/repositories`
- Database access layer
- CRUD operations
- Query implementations
- Data persistence logic
- Database transaction handling

#### `/services`
- Business logic implementation
- Service-to-service communication
- External API integrations
- Complex data processing
- Business rules enforcement

#### `/utils`
- Helper functions
- Common utilities
- Shared constants
- Custom decorators
- Reusable tools

#### `/worker`
- Background task processors
- Async job handlers
- Queue consumers
- Scheduled tasks
- Long-running processes

#### `/uploads`
- Temporary file storage
- Upload processing
- File management

### Key Files

- `config.py`: Application configuration, environment variables, and settings
- `main.py`: Application entry point, FastAPI app initialization, and startup configuration

## Development

### Prerequisites
- Python 3.8+
- PostgreSQL
- Redis (for background tasks)

### Setup
1. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. Run the development server:
   ```bash
   uvicorn app.main:app --reload
   ```

### Architecture

This project follows a layered architecture pattern:

1. **API Layer** (Controllers)
   - Handles HTTP requests/responses
   - Input validation
   - Route definitions

2. **Service Layer**
   - Business logic
   - Use case implementation
   - Orchestration of data flow

3. **Repository Layer**
   - Data access
   - Database operations
   - Data persistence

This separation ensures:
- Clear separation of concerns
- Maintainable codebase
- Testable components
- Scalable architecture 