"""Keep supplier secrets out of admin and web processes, including local deployments."""

SYSTEM_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "SSL_CERT_FILE", "SSL_CERT_DIR"}
PUBLIC_PREFIXES = (
    "YINGHE_",
    "YSEEAI_",
    "TOAPIS_",
    "RUNNINGHUB_",
    "OPTIMIZER_",
    "TOS_",
    "MEDIA_",
    "POLL_",
    "WORKER_",
    "MAX_",
)


def for_service(name, values):
    env = {k: v for k, v in values.items() if k in SYSTEM_KEYS}
    if name in {"public", "worker"}:
        env.update({k: v for k, v in values.items() if k == "DATABASE_URL" or k.startswith(PUBLIC_PREFIXES)})
    elif name == "admin":
        env.update(
            {k: v for k, v in values.items() if k == "DATABASE_URL" or k in {"ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_JWT_SECRET"}}
        )
    return env
