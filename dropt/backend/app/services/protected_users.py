"""Protected Linux accounts — cannot lock/delete/password-change via portal."""

PROTECTED_USERNAMES = frozenset(
    {
        "root",
        "bin",
        "daemon",
        "adm",
        "lp",
        "sync",
        "shutdown",
        "halt",
        "mail",
        "operator",
        "games",
        "ftp",
        "nobody",
        "systemd-network",
        "systemd-resolve",
        "dbus",
        "polkitd",
        "sshd",
        "chrony",
        "dtt-automation",
        "svc-opt",
    }
)

MIN_MUTABLE_UID = 1000


def is_protected_username(username: str) -> bool:
    return username.strip().lower() in PROTECTED_USERNAMES


def is_protected_uid(uid: int | None) -> bool:
    if uid is None:
        return False
    return uid < MIN_MUTABLE_UID
