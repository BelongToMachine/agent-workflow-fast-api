from collections.abc import Iterable

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
    ),
    "viewer": (
        "knowledge.read",
        "chat.read",
        "chat.write",
        "document.read",
    ),
}


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

    return [permission for permission in PERMISSION_CATALOG if permission in permissions]
