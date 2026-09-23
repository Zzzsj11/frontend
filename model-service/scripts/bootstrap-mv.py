#!/usr/bin/env python3
"""Run on the MV host: prepare; separately migrate/seed with Alembic; then grant.

Only provisions model_service and its three roles. Never creates a client API key.
Any existing/partial installation requires operator review, not password rotation.
"""

import argparse
import ast
import base64
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "model_service"
OWNER = "model_migration"
RUNTIMES = "model_public, model_control"
ROLES = (OWNER, "model_public", "model_control")
ENV_NAMES = (".env.public", ".env.admin", ".env.migration")
POSTGRES = "mv-agent-frontend-postgres-1"
BACKEND = "mv-agent-frontend-backend-1"

# Read only this allowlist, after app.config has loaded MV's runtime secrets.
# Older MV Settings has no overseas business fields: use only the named env keys.
READ_CONFIG = """import json, os
from app.config import settings as s
if not s.image_api_key or s.image_api_key != s.video_api_key:
    raise ValueError('Image/video keys missing or different')
pairs = {
    'YINGHE_BASE_URL': s.video_api_base_url,
    'YINGHE_API_KEY': s.video_api_key,
    'YINGHE_LLM_BASE_URL': s.llm_base_url.removesuffix('/v1'),
    'YINGHE_LLM_API_KEY': s.llm_api_key,
    'YSEEAI_BASE_URL': s.yseeai_api_base_url, 'YSEEAI_API_KEY': s.yseeai_api_key,
    'TOAPIS_BASE_URL': s.toapis_api_base_url, 'TOAPIS_API_KEY': s.toapis_api_key,
    'RUNNINGHUB_BASE_URL': s.runninghub_base_url.removesuffix('/openapi/v2'),
    'RUNNINGHUB_API_KEY': s.runninghub_api_key,
    'OPTIMIZER_GEMINI_BASE_URL': s.prompt_optimizer_gemini_base_url.removesuffix('/v1'),
    'OPTIMIZER_GEMINI_API_KEY': s.prompt_optimizer_gemini_api_key,
    'OPTIMIZER_MINIMAX_BASE_URL': s.prompt_optimizer_minimax_base_url,
    'OPTIMIZER_MINIMAX_API_KEY': s.prompt_optimizer_minimax_api_key,
    'YINGHE_ASSET_GROUP_ID': s.aigc_asset_group_id, 'LLM_MODEL': s.llm_model,
    'TOS_ACCESS_KEY': s.tos_access_key, 'TOS_SECRET_KEY': s.tos_secret_key,
    'TOS_ENDPOINT': s.tos_endpoint, 'TOS_REGION': s.tos_region,
    'TOS_REFERENCE_BUCKET': s.tos_reference_bucket, 'TOS_VIDEO_BUCKET': s.tos_video_bucket,
    'TOS_PUBLIC_DOMAIN': s.tos_public_domain,
    'YINGHE_BUSINESS_USER_ID': s.business_user_id,
    'YINGHE_BUSINESS_API_KEY': s.business_api_key,
    'YINGHE_BUSINESS_BASE_URL': s.business_balance_url.removesuffix('/business/reconcile/balance'),
}
for suffix, default in [('USER_ID', ''), ('API_KEY', ''), ('BASE_URL', 'https://api-aigc.yseeai.com')]:
    key = 'YSEEAI_BUSINESS_' + suffix
    pairs[key] = getattr(s, key.lower(), os.environ.get(key, default))
print(json.dumps(pairs))
"""

REQUIRED = (
    "YINGHE_BASE_URL",
    "YINGHE_API_KEY",
    "YINGHE_LLM_BASE_URL",
    "YINGHE_LLM_API_KEY",
    "LLM_MODEL",
    "TOS_ACCESS_KEY",
    "TOS_SECRET_KEY",
    "TOS_ENDPOINT",
    "TOS_REGION",
    "TOS_REFERENCE_BUCKET",
    "TOS_VIDEO_BUCKET",
)

CATALOG_SQL = """BEGIN READ ONLY;
SELECT json_build_object(
    'database', (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = 'model_service'),
    'roles', (SELECT COALESCE(json_object_agg(rolname,
        rolcanlogin AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
        AND NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid OR roleid = r.oid)), '{}'::json)
        FROM pg_roles r WHERE rolname IN ('model_migration', 'model_public', 'model_control'))
);
COMMIT;
"""

ACCESS_SQL = f"""REVOKE ALL ON DATABASE {DATABASE} FROM PUBLIC, {RUNTIMES};
GRANT CONNECT ON DATABASE {DATABASE} TO {OWNER}, {RUNTIMES};
REVOKE ALL ON SCHEMA public FROM PUBLIC, {RUNTIMES};
GRANT USAGE, CREATE ON SCHEMA public TO {OWNER};
GRANT USAGE ON SCHEMA public TO {RUNTIMES};
"""


class BootstrapError(Exception):
    """Only fixed, secret-free messages may cross the CLI boundary."""


def run(command, payload, phase):
    try:
        result = subprocess.run(command, input=payload, text=True, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        raise BootstrapError(f"{phase} failed; subprocess details suppressed.") from None
    if result.returncode:
        # psql errors can echo entire SQL; backend import errors can echo secrets.
        raise BootstrapError(f"{phase} failed (exit {result.returncode}); output suppressed.")
    return result.stdout


def psql(database, sql):
    if database not in ("postgres", DATABASE):
        raise BootstrapError("Refusing a database outside the bootstrap scope.")
    return run(
        [
            "docker",
            "exec",
            "-i",
            POSTGRES,
            "sh",
            "-c",
            'exec psql -X -w -qAt -v ON_ERROR_STOP=1 -v VERBOSITY=terse -h /var/run/postgresql -U "${POSTGRES_USER:-postgres}" -d "$1"',
            "sh",
            database,
        ],
        sql,
        "PostgreSQL operation",
    )


def read_json(raw):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise BootstrapError("Invalid captured JSON; output suppressed.") from None
    if not isinstance(value, dict):
        raise BootstrapError("Expected a captured JSON object; output suppressed.")
    return value


def catalog():
    result = read_json(psql("postgres", CATALOG_SQL))
    if set(result) != {"database", "roles"} or not isinstance(result["roles"], dict):
        raise BootstrapError("Invalid PostgreSQL preflight result.")
    return result


def require_absent(directory, state):
    if state["database"] is not None or state["roles"] or any(os.path.lexists(directory / name) for name in ENV_NAMES):
        raise BootstrapError("Existing or partial bootstrap detected; refusing overwrite/password changes. Operator review required.")


def config():
    values = read_json(run(["docker", "exec", "-i", BACKEND, "python", "-"], READ_CONFIG, "MV settings read"))
    if any(not isinstance(v, str) or any(ord(c) < 32 for c in v) for v in values.values()):
        raise BootstrapError("Configuration contains non-string or multiline/control values.")
    if any(not values.get(k, "").strip() for k in REQUIRED):
        raise BootstrapError("Required image/video, LLM or TOS configuration is missing.")
    for prefix in ("YSEEAI", "TOAPIS", "RUNNINGHUB", "OPTIMIZER_GEMINI", "OPTIMIZER_MINIMAX"):
        if values.get(prefix + "_API_KEY") and not values.get(prefix + "_BASE_URL", "").strip():
            raise BootstrapError("Configured supplier is missing its base URL.")
    for prefix, base in (("YINGHE", "https://api-aigc.fzyinghe.com"), ("YSEEAI", "https://api-aigc.yseeai.com")):
        user, key = (values.get(prefix + "_BUSINESS_" + suffix, "") for suffix in ("USER_ID", "API_KEY"))
        if bool(user) != bool(key) or ((user or key) and values.get(prefix + "_BUSINESS_BASE_URL") != base):
            raise BootstrapError("Business credentials are incomplete or have a mismatched site; refusing cross-site reuse.")
    return values


def scram_password(password):
    # Send a verifier, not a plaintext password, even if the server logs role DDL.
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 4096)
    stored = hashlib.sha256(hmac.digest(salted, b"Client Key", "sha256")).digest()
    server = hmac.digest(salted, b"Server Key", "sha256")
    encoded = [base64.b64encode(v).decode("ascii") for v in (salt, stored, server)]
    return f"SCRAM-SHA-256$4096:{encoded[0]}${encoded[1]}:{encoded[2]}"


def write_private(path, values):
    # docker run --env-file 保留引号；迁移文件不能使用 Compose 的引号语法。
    # 常驻服务仍由 Compose 读取，用单引号防止 $、# 被插值或截断。
    if path.name == ".env.migration":
        content = "".join(k + "=" + v + "\n" for k, v in values.items())
    else:
        content = "".join(k + "='" + v.replace("\\", "\\\\").replace("'", "\\'") + "'\n" for k, v in values.items())
    fd, temporary = tempfile.mkstemp(prefix=".bootstrap-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # link, unlike replace/rename, is atomic AND refuses an existing target.
        os.link(temporary, path, follow_symlinks=False)
    finally:
        os.unlink(temporary)


def prepare(directory):
    require_absent(directory, catalog())  # Read-only before importing or writing any secret.
    values = config()
    directory.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise BootstrapError("Env directory must be owned by this user and not group/world writable.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require_absent(directory, catalog())
        passwords = {role: secrets.token_urlsafe(48) for role in ROLES}
        urls = {
            role: f"postgresql+asyncpg://{role}:{quote(password, safe='')}@postgres:5432/{DATABASE}" for role, password in passwords.items()
        }
        bundles = (
            {"DATABASE_URL": urls["model_public"], **values},
            {
                "DATABASE_URL": urls["model_control"],
                "ADMIN_USERNAME": "admin",
                "ADMIN_PASSWORD": secrets.token_urlsafe(48),
                "ADMIN_JWT_SECRET": secrets.token_urlsafe(48),
            },
            {"DATABASE_URL": urls[OWNER], "LLM_MODEL": values["LLM_MODEL"]},
        )
        for name, bundle in zip(ENV_NAMES, bundles, strict=True):
            write_private(directory / name, bundle)
        os.fsync(fd)
        # Retain private files on any DB failure: CREATE DATABASE cannot be in a
        # transaction. Never drop roles/DB, rotate passwords or retry automatically.
        roles_sql = (
            "BEGIN;\n"
            + "\n".join(
                f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS "
                f"PASSWORD '{scram_password(password)}';"
                for role, password in passwords.items()
            )
            + "\nCOMMIT;\n"
        )
        psql("postgres", roles_sql)
        psql("postgres", f"CREATE DATABASE {DATABASE} OWNER {OWNER} TEMPLATE template0;\n")
        psql(DATABASE, "BEGIN;\n" + ACCESS_SQL + "COMMIT;\n")
    finally:
        os.close(fd)


def migration_head():
    # Standard library only: do not import migrations or require Alembic on host.
    revisions, parents = set(), set()
    for path in (ROOT / "migrations/versions").glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in {"revision", "down_revision"} for t in node.targets
            ):
                value = ast.literal_eval(node.value)
                if any(isinstance(t, ast.Name) and t.id == "revision" for t in node.targets):
                    revisions.add(value)
                elif value is not None:
                    parents.update(value if isinstance(value, tuple) else (value,))
    heads = revisions - parents
    if len(heads) != 1:
        raise BootstrapError("Expected exactly one local Alembic head.")
    return heads.pop()


def grant():
    state = catalog()
    if state["database"] != OWNER or set(state["roles"]) != set(ROLES) or not all(v is True for v in state["roles"].values()):
        raise BootstrapError("Database owner/roles do not match an isolated bootstrap; refusing grants.")
    head = migration_head().replace("'", "''")
    # The version and ownership checks precede every ACL change in one transaction.
    psql(
        DATABASE,
        f"""BEGIN;
SET LOCAL lock_timeout = '10s';
DO $$
BEGIN
    IF (SELECT count(*) FROM public.alembic_version) <> 1
       OR NOT EXISTS (SELECT 1 FROM public.alembic_version WHERE version_num = '{head}') THEN
        RAISE EXCEPTION 'Run the independent Alembic upgrade head first';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
               WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
               AND pg_get_userbyid(c.relowner) <> '{OWNER}') THEN
        RAISE EXCEPTION 'Public objects must be owned by the migration role';
    END IF;
END $$;
{ACCESS_SQL}
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, {RUNTIMES};
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {RUNTIMES};
REVOKE ALL ON TABLE public.admin_credentials FROM model_public;
REVOKE INSERT, UPDATE ON TABLE public.alembic_version FROM {RUNTIMES};
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, {RUNTIMES};
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {RUNTIMES};
ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER} IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC, {RUNTIMES};
ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER} IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO {RUNTIMES};
ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER} IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC, {RUNTIMES};
ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER} IN SCHEMA public GRANT USAGE ON SEQUENCES TO {RUNTIMES};
COMMIT;
""",
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="Create private env files, isolated database and roles; never overwrite")
    prepare_parser.add_argument("--env-dir", type=Path, default=ROOT, help="Existing parent required; default: model-service directory")
    commands.add_parser("grant", help="After independent Alembic head, grant runtime DML permissions")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare(args.env_dir.absolute())
        else:
            grant()
    except BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("Bootstrap failed; details suppressed. Preserve private files and review partial state before retrying.", file=sys.stderr)
        return 1
    print(
        "Prepared private env files and database roles; run independent Alembic/seed, then grant."
        if args.command == "prepare"
        else "Granted runtime DML permissions; no DDL or DELETE permissions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
