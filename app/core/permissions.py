from collections.abc import Iterable

from app.core.agent_tool_catalog import AGENT_TOOL_CATALOG

AGENT_TOOL_PERMISSION_CODES = {
    function_name: metadata["permission_code"]
    for function_name, metadata in AGENT_TOOL_CATALOG.items()
}

AGENT_TOOL_PERMISSION_CATALOG = tuple(AGENT_TOOL_PERMISSION_CODES.values())

PERMISSION_CATALOG = (
    "members.read",
    "members.manage",
    "knowledge.read",
    "knowledge.manage",
    "chat.read",
    "chat.write",
    "chat.delete",
    "document.read",
    "document.write",
    "audit.read",
    *AGENT_TOOL_PERMISSION_CATALOG,
)

_STANDARD_AGENT_TOOL_PERMISSIONS = tuple(
    permission
    for permission in AGENT_TOOL_PERMISSION_CATALOG
    if permission != "agent.tool.knowledge_file.extract"
)


DEFAULT_PERMISSIONS_BY_ROLE = {
    "owner": PERMISSION_CATALOG,
    "admin": PERMISSION_CATALOG,
    "editor": (
        "knowledge.read",
        "knowledge.manage",
        "chat.read",
        "chat.write",
        "chat.delete",
        "document.read",
        "document.write",
        *AGENT_TOOL_PERMISSION_CATALOG,
    ),
    "employee": (
        "knowledge.read",
        "chat.read",
        "chat.write",
        "chat.delete",
        "document.read",
        "document.write",
        *_STANDARD_AGENT_TOOL_PERMISSIONS,
    ),
    "viewer": (
        "knowledge.read",
        "chat.read",
        "chat.write",
        "document.read",
        *_STANDARD_AGENT_TOOL_PERMISSIONS,
    ),
}


def get_agent_tool_permissions_by_role() -> dict[str, list[str]]:
    agent_permissions = set(AGENT_TOOL_PERMISSION_CATALOG)
    return {
        role: [permission for permission in permissions if permission in agent_permissions]
        for role, permissions in DEFAULT_PERMISSIONS_BY_ROLE.items()
    }

ROLE_FORBIDDEN_PERMISSIONS = {
    "employee": frozenset(("knowledge.manage",)),
}


def get_default_permissions_by_role() -> dict[str, list[str]]:
    return {
        role: list(permissions)
        for role, permissions in DEFAULT_PERMISSIONS_BY_ROLE.items()
    }


def get_forbidden_permissions(role: str) -> frozenset[str]:
    return ROLE_FORBIDDEN_PERMISSIONS.get(role, frozenset())


def get_effective_permissions(
    role: str,
    overrides: Iterable[tuple[str, str]],
    *,
    is_guest: bool = False,
) -> list[str]:
    permissions = set(
        ("chat.read", "chat.write") if is_guest else DEFAULT_PERMISSIONS_BY_ROLE.get(role, ())
    )
    valid_permissions = set(PERMISSION_CATALOG)

    for effect, permission in overrides:
        if permission not in valid_permissions:
            continue
        if effect == "grant":
            permissions.add(permission)
        elif effect == "deny":
            permissions.discard(permission)

    permissions.difference_update(get_forbidden_permissions(role))

    return [permission for permission in PERMISSION_CATALOG if permission in permissions]
