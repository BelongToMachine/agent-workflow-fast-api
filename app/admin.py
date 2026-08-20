"""SQLAdmin integration for the local FastAPI development backend."""

import secrets
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from sqlalchemy import Boolean, DateTime, String, Text, Uuid
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.requests import Request

from app.core.config import Settings


class AdminBase(DeclarativeBase):
    """Metadata base used only for SQLAdmin's existing-table mappings."""


class UserRecord(AdminBase):
    __tablename__ = "User"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    email: Mapped[str] = mapped_column(String(64), nullable=False)
    email_verified: Mapped[bool] = mapped_column("emailVerified", Boolean, nullable=False)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_anonymous: Mapped[bool] = mapped_column("isAnonymous", Boolean, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False)


class WorkspaceRecord(AdminBase):
    __tablename__ = "Workspace"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[UUID | None] = mapped_column("ownerId", Uuid(), nullable=True)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False)


class WorkspaceMemberRecord(AdminBase):
    __tablename__ = "WorkspaceMember"

    id: Mapped[UUID] = mapped_column(Uuid(), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    user_id: Mapped[UUID] = mapped_column("userId", Uuid(), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column("workspaceId", Uuid(), nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime, nullable=False)


class LocalAdminAuthentication(AuthenticationBackend):
    """Session login for the opt-in local SQLAdmin preview."""

    def __init__(self, settings: Settings) -> None:
        secret_key = settings.sqladmin_secret_key or settings.auth_secret
        if not secret_key:
            raise RuntimeError(
                "SQLADMIN_SECRET_KEY or AUTH_SECRET is required when SQLAdmin is enabled."
            )
        super().__init__(secret_key=secret_key)
        self.username = settings.sqladmin_username
        self.password = settings.sqladmin_password

    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            return False
        if self.password is None:
            return False
        if secrets.compare_digest(username, self.username) and secrets.compare_digest(
            password,
            self.password,
        ):
            request.session["sqladmin_authenticated"] = True
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("sqladmin_authenticated"))


class ReadOnlyModelView(ModelView):
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False


class UserAdminView(ReadOnlyModelView, model=UserRecord):
    name = "用户"
    name_plural = "用户"
    icon = "fa-solid fa-users"
    column_list = [
        UserRecord.id,
        UserRecord.email,
        UserRecord.name,
        UserRecord.is_anonymous,
        UserRecord.email_verified,
        UserRecord.created_at,
    ]
    column_searchable_list = [UserRecord.email, UserRecord.name]
    column_sortable_list = [UserRecord.email, UserRecord.created_at]
    column_default_sort = [(UserRecord.created_at, True)]


class WorkspaceAdminView(ReadOnlyModelView, model=WorkspaceRecord):
    name = "工作空间"
    name_plural = "工作空间"
    icon = "fa-solid fa-building"
    column_list = [
        WorkspaceRecord.id,
        WorkspaceRecord.name,
        WorkspaceRecord.owner_id,
        WorkspaceRecord.created_at,
    ]
    column_searchable_list = [WorkspaceRecord.name]
    column_sortable_list = [WorkspaceRecord.name, WorkspaceRecord.created_at]


class WorkspaceMemberAdminView(ReadOnlyModelView, model=WorkspaceMemberRecord):
    name = "成员"
    name_plural = "成员"
    icon = "fa-solid fa-user-group"
    column_list = [
        WorkspaceMemberRecord.id,
        WorkspaceMemberRecord.user_id,
        WorkspaceMemberRecord.workspace_id,
        WorkspaceMemberRecord.role,
        WorkspaceMemberRecord.status,
        WorkspaceMemberRecord.created_at,
    ]
    column_sortable_list = [WorkspaceMemberRecord.role, WorkspaceMemberRecord.created_at]


def install_sqladmin(application: FastAPI, settings: Settings, engine: AsyncEngine) -> Admin:
    """Mount the opt-in, read-only SQLAdmin preview at ``/admin``."""

    if not settings.sqladmin_password:
        raise RuntimeError("SQLADMIN_PASSWORD is required when SQLAdmin is enabled.")

    admin = Admin(
        application,
        engine,
        base_url="/admin",
        title="Asianode Admin Preview",
        authentication_backend=LocalAdminAuthentication(settings),
    )
    admin.add_view(UserAdminView)
    admin.add_view(WorkspaceAdminView)
    admin.add_view(WorkspaceMemberAdminView)
    return admin
