# PrivacyGuard AI — Sprint 4C: التقرير (تقرير بعنوان "docs/sprint4c_engineering_walkthrough_ar.md")

## 1. البنية (Architecture)
- طبقات: Routers (app.py), Schemas (schemas.py), Services/Repos (repository.py), ORM models (models.py), Database session (database.py).
- التكوين (composition) وليس inheritance عدا Base.

## 2. Application entrypoint
- `create_app(database_url)` يبني FastAPI app وجلسة SQLAlchemy.
- Health endpoints `/health/live`, `/health/ready`.
- CRUD endpoints audit requests/runs; evidence repository; prohibited external queue.

## 3. SQLAlchemy ORM & Models
- `Base` في models.py.
- Primary key: `id: Mapped[str] = mapped_column(... primary_key=True)`.
- Foreign keys: `workspace_id Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))`.
- 1:N: Workspace has audit_requests Mapped[list["AuditRequest"]].
- Timestamps: `created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), ...)`.
- Unique constraint: `UniqueConstraint("workspace_id","request_id")`.

Example:
```python
class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit_requests: Mapped[list["AuditRequest"]] = relationship(back_populates="workspace")
```

## 4. Repository Pattern
- `WorkspaceRepository(session)`, `AuditRequestRepository`, `AuditRunRepository`.
- Encapsulation of DB access.

Example:
```python
class AuditRequestRepository:
    def __init__(self, session: Session):
        self.session = session
    def create(self, workspace_id, payload):
        request = AuditRequest(...)
        self.session.add(request)
        self.session.commit()
        return request
```

## 5. Dependency Injection
FastAPI `Depends(get_session)` injects session.

Example:
```python
def get_session() -> Session:
    session = platform_db.session()
    try: yield session
    finally: session.close()
```

## 6. Dependency Injection & Polymorphism
- Service/repo substitution for tests using dependency override providers.
- Layered routers/shemas.

## 7. Migration (Alembic)
- `alembic/env.py` sets `target_metadata = Base.metadata`, inserts src to path; upgrade database.
- (`alembic upgrade head`) used.

## 8. Status codes and contracts
- 201 create, 200 fetch, 404 not found, 503 readiness.
- Pydantic request/response schemas.

## 9. Security
- passwords in env only.
- DB session isolation; select-only SmartShop connector.
- No mutation schema without permission.
- Parameterized queries for SmartShop read-only.

## 10. Known limitations
- All audit executions stub status COMPLETED without SmartShop audit result integration.
- No auth/authz engine.
- In-memory default DB should only be for tests.
- Platform does not yet invoke actual PrivacyGuard audit engine (MVP service integration planned).

## 11. Next sprint
- Wire audit tasks to smartshop audit pipeline.
- Add permission scope.
- Persistence + migration hardening.

## 12. Files changed
- src/privacyguard/platform/app.py
- models.py, database.py, repository.py, schemas.py
- alembic/*, alembic.ini
- tests/platform/test_platform_api.py

## 13. Commands
```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m pytest -o addopts="" -q -W error
.\.venv\Scripts\uvicorn.exe privacyguard.platform.app:create_app --factory
```

## 14. Result
- 286 passed, 5 skipped, zero warnings.