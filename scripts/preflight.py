#!/usr/bin/env python3
"""
preflight.py — Verify the entire stack can be deployed BEFORE setup_workspace.py
=================================================================================
Run this AFTER `az login` and BEFORE `setup_workspace.py` to catch every
prerequisite issue up-front instead of failing halfway through deployment.

What it checks
--------------
  Section 1  Dev container prerequisites (az, python, node, pyodbc, ODBC18, .venv,
             requirements installed, backend/.env exists)
  Section 2  Azure context (az login, subscription, identity, az fabric extension)
  Section 3  Azure resource providers registered
             (Microsoft.Fabric, Microsoft.DocumentDB, Microsoft.CognitiveServices)
  Section 4  Region supports everything we need (Fabric, Cosmos, OpenAI)
  Section 5  Fabric capacity exists and is active in region
             (with --fix, auto-creates an F4 capacity)
  Section 6  Fabric API reachable, user can list workspaces
  Section 7  Azure OpenAI resource + required model deployments
             (gpt-* chat model and text-embedding-ada-002)
  Section 8  Summary with exit code 0 (ready) / 1 (issues)

Usage
-----
    # Required: pick a region (Azure-name format, e.g. "eastus2", "westeurope",
    #           "israelcentral").  We'll validate it supports everything.
    python scripts/preflight.py --region eastus2

    # Optionally tell us which existing OpenAI resource to use
    python scripts/preflight.py --region eastus2 \\
                                --openai-resource my-aoai-resource

    # Auto-create missing things where possible
    # (install az fabric extension, register providers, create F4 capacity)
    python scripts/preflight.py --region eastus2 --fix
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# ── ANSI ───────────────────────────────────────────────────────────────────────
_TTY = sys.stdout.isatty()
G = "\033[32m" if _TTY else ""
Y = "\033[33m" if _TTY else ""
R = "\033[31m" if _TTY else ""
C = "\033[36m" if _TTY else ""
B = "\033[1m"  if _TTY else ""
X = "\033[0m"  if _TTY else ""

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / "backend" / ".env"
REQUIREMENTS_FILE = REPO / "requirements.txt"
PACKAGE_JSON = REPO / "package.json"
DEPLOY_STATE = REPO / "scripts" / "deploy-state.json"

FABRIC_API = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

# Regions where Cosmos DB in Fabric is documented as NOT available
COSMOS_UNSUPPORTED_REGIONS = {
    "indiawest", "qatarcentral", "uaecentral",
    "austriaeast", "chilecentral", "southcentralus",
}
# Regions where Cosmos DB in Fabric is currently lagging despite docs (empirical)
COSMOS_LAGGING_REGIONS = {"israelcentral"}

# Required Azure resource providers
REQUIRED_PROVIDERS = [
    "Microsoft.Fabric",
    "Microsoft.DocumentDB",
    "Microsoft.CognitiveServices",
]

# Expected Fabric workspace items (after a successful setup_workspace.py)
EXPECTED_ITEMS = [
    ("SQLDatabase",       "agentic_app_db"),
    ("CosmosDBDatabase",  "agentic_cosmos_db"),
    ("Lakehouse",         "agentic_lake"),
    ("Eventhouse",        "AgenticEventHouse"),
    ("KQLDatabase",       "app_events"),
    ("Eventstream",       "agentic_stream"),
    ("KQLQueryset",       "QueryWorkBench"),
    ("DataAgent",         "Banking_DataAgent"),
    ("SemanticModel",     "banking_semantic_model"),
    ("Report",            "Agentic_Insights"),
    ("Notebook",          "QA_Evaluation_Notebook"),
]

REQUIRED_PYTHON = (3, 11)
REQUIRED_NODE_MAJOR = 18


def load_env_file(path: Path) -> dict:
    """Minimal .env parser — does not mutate os.environ."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        out[k.strip()] = v
    return out


def write_env_var(path: Path, key: str, value: str) -> None:
    """Idempotently set KEY=value in a .env-style file (preserves other lines)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text().splitlines() if path.exists() else []
    new_line = f'{key}="{value}"'
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
            lines[i] = new_line
            found = True
            break
    if not found:
        lines.append(new_line)
    path.write_text("\n".join(lines) + "\n")

# ── Output helpers ─────────────────────────────────────────────────────────────
issues:   list[str] = []
warnings: list[str] = []
fixes:    list[str] = []


def head(t):     print(f"\n{B}━━ {t}{X}")
def ok(m):       print(f"  {G}✓{X} {m}")
def fail(m):     print(f"  {R}✗{X} {m}"); issues.append(m)
def warn(m):     print(f"  {Y}⚠{X} {m}"); warnings.append(m)
def info(m):     print(f"  {C}·{X} {m}")
def fix_hint(m): print(f"     {C}→{X} {m}"); fixes.append(m)


def run_cmd(cmd, check=False, capture=True):
    # On Windows, the az CLI ships as az.cmd, which subprocess.run with a list
    # of args cannot resolve through PATH without going through the shell.
    # shell=True lets Windows resolve .cmd / .bat shims (see issue #62).
    use_shell = sys.platform == "win32"
    try:
        return subprocess.run(
            cmd, capture_output=capture, text=True, check=check, timeout=120,
            shell=use_shell,
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, "", str(e))
    except FileNotFoundError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def az(args, check=False):
    if isinstance(args, str):
        args = args.split()
    return run_cmd(["az", *args], check=check)


def az_json(args):
    r = az(args)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Dev container prerequisites
# ─────────────────────────────────────────────────────────────────────────────
def check_devcontainer():
    head("1. Dev container prerequisites")

    # azure CLI
    if not shutil.which("az"):
        fail("az CLI not found in PATH")
        fix_hint("Install: https://learn.microsoft.com/cli/azure/install-azure-cli")
    else:
        v = az_json("version")
        ver = (v or {}).get("azure-cli", "?")
        ok(f"az CLI: v{ver}")

    # python
    py = sys.version_info
    if (py.major, py.minor) >= REQUIRED_PYTHON:
        ok(f"python: {py.major}.{py.minor}.{py.micro}")
    else:
        fail(f"python {py.major}.{py.minor} < required {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}")
        fix_hint(f"Install python {REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+ "
                 "or rebuild the dev container")

    # node
    if shutil.which("node"):
        r = run_cmd(["node", "--version"])
        m = re.match(r"v(\d+)", r.stdout.strip())
        if m and int(m.group(1)) >= REQUIRED_NODE_MAJOR:
            ok(f"node: {r.stdout.strip()}")
        else:
            fail(f"node version {r.stdout.strip()} < required v{REQUIRED_NODE_MAJOR}")
            fix_hint("Use the dev container, or install node 20 LTS")
    else:
        fail("node not found in PATH")
        fix_hint("Use the dev container, or install node 20 LTS")

    # npm install ran (node_modules exists)
    if (REPO / "node_modules").is_dir():
        ok("node_modules/ exists (npm install ran)")
    else:
        fail("node_modules/ missing — npm install hasn't run")
        fix_hint("Run: npm install")

    # .venv with requirements installed
    venv_python = REPO / ".venv" / "bin" / "python"
    if not venv_python.exists():
        venv_python = REPO / ".venv" / "Scripts" / "python.exe"  # Windows
    if venv_python.exists():
        ok(f".venv exists ({venv_python.relative_to(REPO)})")
    else:
        warn(".venv not found — pip packages may be installed system-wide")

    # required python packages
    required_pkgs = [
        "azure.identity", "azure.cosmos", "azure.eventhub",
        "requests", "pyodbc", "flask", "langchain_community", "langchain_openai",
    ]
    missing = []
    for pkg in required_pkgs:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        ok(f"python packages: all {len(required_pkgs)} installed")
    else:
        fail(f"missing python packages: {', '.join(missing)}")
        fix_hint("Run: pip install -r requirements.txt")

    # ODBC Driver 18
    odbc_check = run_cmd(["bash", "-c", "odbcinst -q -d 2>/dev/null | grep -i 'ODBC Driver 18'"])
    if odbc_check.returncode == 0 and odbc_check.stdout.strip():
        ok("ODBC Driver 18 for SQL Server installed")
    else:
        # Fallback: try connecting via pyodbc
        try:
            import pyodbc as _po
            drivers = [d for d in _po.drivers() if "18" in d and "SQL Server" in d]
            if drivers:
                ok(f"ODBC driver: {drivers[0]}")
            else:
                fail("ODBC Driver 18 for SQL Server not installed")
                fix_hint("Use the dev container, or install msodbcsql18")
        except Exception:
            warn("could not verify ODBC Driver 18 installation")

    # backend/.env
    if ENV_FILE.exists():
        ok(f"{ENV_FILE.relative_to(REPO)} exists")
    else:
        sample = REPO / "backend" / ".env.sample"
        if sample.exists():
            warn(f"{ENV_FILE.relative_to(REPO)} missing — copying from .env.sample")
            shutil.copy(sample, ENV_FILE)
        else:
            fail(f"{ENV_FILE.relative_to(REPO)} missing AND no .env.sample to copy from")


# ─────────────────────────────────────────────────────────────────────────────
# Section 2: Azure context
# ─────────────────────────────────────────────────────────────────────────────
def check_azure_context(fix: bool = False):
    head("2. Azure context")
    acct = az_json("account show -o json")
    if not acct:
        fail("not logged in to Azure")
        fix_hint("Run: az login")
        return None
    sub_id = acct.get("id")
    sub_name = acct.get("name")
    tenant = acct.get("tenantId")
    user = acct.get("user", {}).get("name")
    ok(f"subscription: {sub_name} ({sub_id})")
    ok(f"tenant:       {tenant}")
    ok(f"user:         {user}")

    user_oid = az_json("ad signed-in-user show --query id -o json")
    if user_oid:
        ok(f"user OID:     {user_oid}")
    else:
        warn("could not resolve signed-in user OID (some checks skipped)")

    # Fabric capacities are managed via raw ARM (Microsoft.Fabric/capacities) —
    # there is no public 'az fabric' extension. We rely on 'az resource create' instead.
    info("note: Fabric capacities managed via ARM (no 'az fabric' extension required)")

    return {"sub_id": sub_id, "tenant": tenant, "user": user, "user_oid": user_oid}


# ─────────────────────────────────────────────────────────────────────────────
# Section 3: Resource providers
# ─────────────────────────────────────────────────────────────────────────────
def check_resource_providers(fix: bool):
    head("3. Azure resource providers")
    for ns in REQUIRED_PROVIDERS:
        prov = az_json(["provider", "show", "-n", ns, "-o", "json"])
        if not prov:
            fail(f"{ns}: could not query (insufficient permissions?)")
            continue
        state = prov.get("registrationState")
        if state == "Registered":
            ok(f"{ns}: Registered")
        elif state == "NotRegistered":
            if fix:
                info(f"{ns}: registering (--fix)…")
                r = az(["provider", "register", "-n", ns, "-o", "none"])
                if r.returncode == 0:
                    ok(f"{ns}: registration started (may take a few minutes)")
                else:
                    fail(f"{ns}: register failed — {r.stderr.strip()}")
            else:
                fail(f"{ns}: NotRegistered")
                fix_hint(f"Run: az provider register -n {ns}   (or pass --fix)")
        else:
            warn(f"{ns}: state={state}")


# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Region validation
# ─────────────────────────────────────────────────────────────────────────────
def normalize_region(r: str) -> str:
    return re.sub(r"[\s\-_]", "", r.lower())


def check_region(region: str):
    head(f"4. Region validation ({region})")
    norm = normalize_region(region)

    # Verify region exists in Azure
    locs = az_json("account list-locations -o json") or []
    loc_names = {normalize_region(l.get("name", "")) for l in locs}
    if norm not in loc_names:
        fail(f"region '{region}' not in Azure locations list")
        fix_hint("Use a valid Azure region: az account list-locations -o table")
        return False
    ok(f"region '{region}' is a valid Azure region")

    # Cosmos DB in Fabric region check
    if norm in COSMOS_UNSUPPORTED_REGIONS:
        fail(f"Cosmos DB in Fabric NOT supported in {region}")
        fix_hint("Use a different region OR provision a separate Azure Cosmos DB account")
    elif norm in COSMOS_LAGGING_REGIONS:
        warn(f"Cosmos DB in Fabric documented as supported in {region} but rollout appears delayed")
        fix_hint(
            "Test by opening Fabric portal → + New item → search 'Cosmos'. "
            "If only 'Mirrored Cosmos DB' shows, run scripts/provision_azure_cosmos.py instead."
        )
    else:
        ok(f"Cosmos DB in Fabric: documented support for {region}")

    # OpenAI quota / availability
    info("checking Azure OpenAI model availability in region…")
    sku_url = (
        f"-o json --query \"[?kind=='OpenAI' && location=='{region}']\""
    )
    skus = az_json(["cognitiveservices", "account", "list-skus",
                    "--location", region, "-o", "json"])
    if skus is None:
        warn("could not query Azure OpenAI SKUs in region (Cognitive Services may not be registered yet)")
    elif not skus:
        warn(f"Azure OpenAI may not be available in {region} via this tenant — verify quota")
        fix_hint(f"Check: https://aka.ms/oai/availability for {region}")
    else:
        ok(f"Azure OpenAI offered in {region} ({len(skus)} SKU(s))")

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Section 5: Fabric capacity
# ─────────────────────────────────────────────────────────────────────────────
def check_fabric_capacity(region: str, fix: bool, sub_id: str, user_oid: Optional[str], token: Optional[str], rg: str):
    head(f"5. Fabric capacity in {region}")
    norm_region = normalize_region(region)

    # Primary: list via ARM (Microsoft.Fabric/capacities) — works without extensions
    arm = az_json([
        "resource", "list",
        "--resource-type", "Microsoft.Fabric/capacities",
        "-o", "json",
    ])
    caps = None
    if arm is not None:
        # ARM returns objects with .sku and .name and .location, but no .properties.state.
        # Pull the state via a per-capacity show call.
        caps = []
        for c in arm:
            state = "Unknown"
            show = az_json([
                "resource", "show",
                "--ids", c.get("id"),
                "--api-version", "2023-11-01",
                "-o", "json",
            ])
            if show:
                state = show.get("properties", {}).get("state", "Unknown")
            caps.append({
                "name": c.get("name"),
                "location": c.get("location", ""),
                "sku": {"name": (c.get("sku") or {}).get("name")},
                "properties": {"state": state},
                "id": c.get("id"),
            })
        ok(f"listed {len(caps)} capacity/ies via ARM (Microsoft.Fabric/capacities)")

    # Fallback: Fabric REST API (covers trial capacities and tenant-level ones not in subscription)
    if caps is None and token:
        info("ARM list unavailable — falling back to Fabric REST API")
        import urllib.request
        try:
            req = urllib.request.Request(
                f"{FABRIC_API}/capacities",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read())
            rest_caps = body.get("value", [])
            caps = [{
                "name": c.get("displayName"),
                "location": c.get("region", ""),
                "sku": {"name": c.get("sku")},
                "properties": {"state": c.get("state")},
                "id": c.get("id"),
            } for c in rest_caps]
            ok(f"listed {len(caps)} capacity/ies via Fabric REST API")
        except Exception as e:
            warn(f"Fabric REST capacities call failed: {e}")
            caps = None

    if caps is None:
        warn("could not list Fabric capacities (no Fabric token and az ARM list failed)")
        fix_hint("Verify you can list capacities: az resource list --resource-type Microsoft.Fabric/capacities")
        return None

    region_caps = [
        c for c in caps
        if normalize_region(c.get("location", "")) == norm_region
    ]
    active_caps = [c for c in region_caps if c.get("properties", {}).get("state") == "Active"]

    if active_caps:
        ok(f"{len(active_caps)} Active capacity in {region}: " +
           ", ".join(f"{c['name']} ({c.get('sku',{}).get('name','?')})" for c in active_caps))
        return active_caps[0]

    if region_caps:
        warn(f"capacities exist in {region} but none Active: " +
             ", ".join(f"{c['name']} ({c.get('properties',{}).get('state')})" for c in region_caps))
        fix_hint("Resume in Azure portal: Microsoft Fabric capacity → Resume")
        return None

    fail(f"no Fabric capacity exists in {region}")
    if fix:
        admin_email = az_json("account show --query user.name -o json")
        if not admin_email:
            warn("cannot auto-create capacity without signed-in user email")
            return None
        cap_name = f"agenticbanking{norm_region[:8]}"
        info(f"creating resource group {rg} in {region}…")
        az(["group", "create", "-n", rg, "-l", region, "-o", "none"])
        info(f"creating Fabric capacity {cap_name} (F4) via ARM…")
        # Microsoft.Fabric/capacities — full ARM body via --is-full-object
        full_body = json.dumps({
            "location": region,
            "sku": {"name": "F4", "tier": "Fabric"},
            "properties": {
                "administration": {"members": [admin_email]}
            },
        })
        r = az([
            "resource", "create",
            "--resource-group", rg,
            "--name", cap_name,
            "--resource-type", "Microsoft.Fabric/capacities",
            "--api-version", "2023-11-01",
            "--is-full-object",
            "--properties", full_body,
            "-o", "none",
        ])
        if r.returncode == 0:
            ok(f"capacity {cap_name} created (F4) — may take ~30s to become Active")
            # Clear the earlier failure since --fix succeeded
            try:
                issues.remove(f"no Fabric capacity exists in {region}")
            except ValueError:
                pass
            return {"name": cap_name, "id": "", "sku": {"name": "F4"},
                    "properties": {"state": "Active"}, "location": region}
        else:
            fail(f"capacity creation failed: {r.stderr.strip()}")
            fix_hint(
                "Try via portal: https://portal.azure.com/#create/Microsoft.MicrosoftFabric "
                f"(region={region}, sku=F4)"
            )
    else:
        fix_hint(
            "Either: (a) run with --fix to auto-create an F4, or "
            "(b) start a free 60-day trial: https://app.fabric.microsoft.com → "
            "user menu → Start trial"
        )
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Section 6: Fabric API access
# ─────────────────────────────────────────────────────────────────────────────
def check_fabric_api():
    head("6. Fabric API access")
    try:
        from azure.identity import AzureCliCredential
    except ImportError:
        fail("azure-identity not installed")
        return None
    try:
        cred = AzureCliCredential()
        tok = cred.get_token(FABRIC_SCOPE)
    except Exception as e:
        fail(f"could not acquire Fabric token: {e}")
        return None
    ok("acquired Fabric API token")

    import urllib.request
    req = urllib.request.Request(
        f"{FABRIC_API}/workspaces",
        headers={"Authorization": f"Bearer {tok.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.loads(r.read())
        ws_count = len(body.get("value", []))
        ok(f"can list workspaces ({ws_count} accessible)")
        return tok.token
    except Exception as e:
        fail(f"Fabric workspaces list failed: {e}")
        fix_hint(
            "Tenant may not have 'Users can create Fabric items' enabled. "
            "Tenant admin: https://app.fabric.microsoft.com/admin-portal/tenantSettings"
        )
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Section 7: Azure OpenAI
# ─────────────────────────────────────────────────────────────────────────────
def _deploy_openai_chat(acct: str, rg: str) -> Optional[str]:
    """Try to deploy a current chat model — cascades through versions.
    Returns the deployment name on success, None on total failure."""
    candidates = [
        # (deployment-name, model-name, model-version)
        ("gpt-4o-mini", "gpt-4o-mini", "2024-07-18"),
        ("gpt-4o", "gpt-4o", "2024-11-20"),
        ("gpt-4o", "gpt-4o", "2024-08-06"),
        ("gpt-4.1-mini", "gpt-4.1-mini", "2025-04-14"),
        ("gpt-4.1", "gpt-4.1", "2025-04-14"),
    ]
    for dep_name, model, ver in candidates:
        if _deploy_openai_model(acct, rg, dep_name, model, ver):
            return dep_name
    warn(f"    could not deploy any chat model — try the Azure AI Foundry portal for current SKUs")
    return None


def _write_openai_env(acct: str, rg: str, chat_deployment: Optional[str]) -> None:
    """Persist key + endpoint + deployment names to backend/.env."""
    keys = az_json([
        "cognitiveservices", "account", "keys", "list",
        "-n", acct, "-g", rg, "-o", "json",
    ]) or {}
    key1 = keys.get("key1") or ""
    show = az_json([
        "cognitiveservices", "account", "show",
        "-n", acct, "-g", rg, "-o", "json",
    ]) or {}
    endpoint = (show.get("properties", {}).get("endpoint")
                or f"https://{acct}.openai.azure.com/")
    if not key1:
        info("    could not fetch OpenAI key — set AZURE_OPENAI_KEY manually")
        return
    write_env_var(ENV_FILE, "AZURE_OPENAI_KEY", key1)
    write_env_var(ENV_FILE, "AZURE_OPENAI_ENDPOINT", endpoint)
    if chat_deployment:
        write_env_var(ENV_FILE, "AZURE_OPENAI_DEPLOYMENT", chat_deployment)
    write_env_var(ENV_FILE, "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")
    ok(f"    wrote AZURE_OPENAI_KEY/ENDPOINT/DEPLOYMENT to {ENV_FILE.relative_to(REPO)}")


def _deploy_openai_model(acct: str, rg: str, dep_name: str, model_name: str, model_version: str):
    """Idempotently create an Azure OpenAI deployment. Returns True on success."""
    existing = az_json([
        "cognitiveservices", "account", "deployment", "show",
        "-n", acct, "-g", rg, "--deployment-name", dep_name, "-o", "json",
    ])
    if existing:
        ok(f"    deployment '{dep_name}' already exists")
        return True
    info(f"    deploying {model_name} (v{model_version}) as '{dep_name}'…")
    r = az([
        "cognitiveservices", "account", "deployment", "create",
        "-n", acct, "-g", rg,
        "--deployment-name", dep_name,
        "--model-name", model_name,
        "--model-version", model_version,
        "--model-format", "OpenAI",
        "--sku-name", "Standard", "--sku-capacity", "10",
        "-o", "none",
    ])
    if r.returncode == 0:
        ok(f"    deployed '{dep_name}'")
        return True
    err_short = r.stderr.strip().split("\n")[0][:140]
    info(f"    skip {model_name} v{model_version}: {err_short}")
    return False


def check_openai(region: str, openai_resource: Optional[str], rg: str, fix: bool = False):
    head("7. Azure OpenAI resource & deployments")
    accts = az_json(["cognitiveservices", "account", "list", "-o", "json"]) or []
    openai_accts = [a for a in accts if a.get("kind") == "OpenAI"]

    if openai_resource:
        match = next((a for a in openai_accts if a.get("name") == openai_resource), None)
        if not match:
            fail(f"OpenAI resource '{openai_resource}' not found in subscription")
            fix_hint(f"Available: {', '.join(a['name'] for a in openai_accts) or '(none)'}")
            return
        targets = [match]
    else:
        if not openai_accts:
            if fix:
                acct_name = f"agentic-aoai-{normalize_region(region)[:8]}"
                info(f"creating Azure OpenAI account {acct_name} in {region}…")
                az(["group", "create", "-n", rg, "-l", region, "-o", "none"])

                def _try_create(name: str):
                    return az([
                        "cognitiveservices", "account", "create",
                        "-n", name, "-g", rg, "-l", region,
                        "--kind", "OpenAI", "--sku", "S0",
                        "--custom-domain", name,
                        "--yes", "-o", "none",
                    ])

                r = _try_create(acct_name)
                # Handle soft-deleted resource collision: purge then retry.
                if r.returncode != 0 and "CustomDomainInUse" in (r.stderr or ""):
                    info(f"name '{acct_name}' collides with a soft-deleted resource; "
                         "attempting purge…")
                    deleted = az_json([
                        "cognitiveservices", "account", "list-deleted", "-o", "json"
                    ]) or []
                    match = next(
                        (d for d in deleted
                         if d.get("name") == acct_name
                         and normalize_region(d.get("location", "")) == normalize_region(region)),
                        None,
                    )
                    if match:
                        purge = az([
                            "cognitiveservices", "account", "purge",
                            "-n", acct_name, "-g", match.get("properties", {}).get("resourceGroup")
                                                or match.get("id", "").split("/")[4],
                            "-l", match.get("location", region), "-o", "none",
                        ])
                        if purge.returncode == 0:
                            ok(f"purged soft-deleted {acct_name}; retrying create…")
                            r = _try_create(acct_name)
                        else:
                            info(f"purge failed: {purge.stderr.strip()}")
                    # Still failing? Fall back to a unique suffix.
                    if r.returncode != 0:
                        suffix = uuid.uuid4().hex[:5]
                        acct_name = f"agentic-aoai-{normalize_region(region)[:8]}-{suffix}"
                        info(f"retrying with unique name {acct_name}…")
                        r = _try_create(acct_name)
                if r.returncode != 0:
                    fail(f"OpenAI account creation failed: {r.stderr.strip()}")
                    fix_hint(
                        "Create one in portal: "
                        "https://portal.azure.com/#create/Microsoft.CognitiveServicesOpenAI"
                    )
                    return
                ok(f"OpenAI account {acct_name} created")
                # Deploy required models
                chat_dep = _deploy_openai_chat(acct_name, rg)
                _deploy_openai_model(acct_name, rg, "text-embedding-ada-002",
                                     "text-embedding-ada-002", "2")
                _write_openai_env(acct_name, rg, chat_dep)
                # Re-fetch account details
                fresh = az_json(["cognitiveservices", "account", "show",
                                 "-n", acct_name, "-g", rg, "-o", "json"])
                if fresh:
                    targets = [fresh]
                else:
                    return
            else:
                fail("no Azure OpenAI resources in subscription")
                fix_hint(
                    "Auto-create with --fix, or via portal: "
                    "https://portal.azure.com/#create/Microsoft.CognitiveServicesOpenAI"
                )
                return
        else:
            targets = openai_accts
            if len(targets) > 1:
                info(f"{len(targets)} OpenAI resources found; checking each. "
                     "Use --openai-resource to pin one.")

    norm_region = normalize_region(region)
    found_chat, found_embed = False, False
    chosen = None
    for acct in targets:
        loc = normalize_region(acct.get("location", ""))
        name = acct.get("name")
        rg = acct.get("resourceGroup") or acct.get("id", "").split("/")[4]
        endpoint = (acct.get("properties", {}).get("endpoint")
                    or f"https://{name}.openai.azure.com/")
        same_region = (loc == norm_region)
        marker = G + "✓" + X if same_region else Y + "≠" + X
        info(f"{marker}  {name}  (region={acct.get('location')}, rg={rg})")
        deps = az_json([
            "cognitiveservices", "account", "deployment", "list",
            "-n", name, "-g", rg, "-o", "json",
        ]) or []
        chat_deps = [d for d in deps if "embedding" not in (d.get("properties", {})
                     .get("model", {}).get("name", "")).lower()]
        embed_deps = [d for d in deps if "embedding" in (d.get("properties", {})
                      .get("model", {}).get("name", "")).lower()]
        if chat_deps:
            names = ", ".join(d["name"] for d in chat_deps)
            ok(f"    chat deployments: {names}")
            found_chat = True
            chat_dep_name = chat_deps[0]["name"]
        else:
            warn(f"    no chat model deployments")
            chat_dep_name = None
            if fix and same_region:
                chat_dep_name = _deploy_openai_chat(name, rg)
                if chat_dep_name:
                    found_chat = True
        embed_match = next(
            (d for d in embed_deps
             if d.get("properties", {}).get("model", {}).get("name") == "text-embedding-ada-002"),
            None,
        )
        if embed_match:
            ok(f"    text-embedding-ada-002: {embed_match['name']}")
            found_embed = True
        else:
            other = ", ".join(d["name"] for d in embed_deps) or "(none)"
            warn(f"    text-embedding-ada-002 not deployed (have: {other})")
            if fix and same_region:
                if _deploy_openai_model(name, rg, "text-embedding-ada-002",
                                        "text-embedding-ada-002", "2"):
                    found_embed = True
        if same_region and chat_deps and embed_match:
            chosen = (name, endpoint, rg, chat_dep_name or chat_deps[0]["name"])

    if not found_chat:
        fail("no chat model deployment found in any OpenAI resource")
        fix_hint("Deploy gpt-4o, gpt-4.1, or gpt-4o-mini in Azure AI Foundry / Azure Portal")
    if not found_embed:
        fail("text-embedding-ada-002 not deployed in any OpenAI resource")
        fix_hint(
            "REQUIRED: text-embedding-ada-002 (the repo's embeddings depend on it). "
            "Deploy via Azure AI Foundry / Azure Portal."
        )

    if chosen:
        ok(f"recommended for backend/.env: {chosen[0]} → {chosen[1]}")
        if fix:
            _write_openai_env(chosen[0], chosen[2], chosen[3])


# ─────────────────────────────────────────────────────────────────────────────
# Section 8: Summary
# ─────────────────────────────────────────────────────────────────────────────
def print_summary():
    head("Summary")
    if not issues and not warnings:
        print(f"{G}{B}  ✅  All preflight checks passed — ready for setup_workspace.py{X}")
        return 0
    if warnings:
        print(f"{Y}{B}  ⚠  {len(warnings)} warning(s):{X}")
        for w in warnings:
            print(f"     {Y}-{X} {w}")
    if issues:
        print(f"{R}{B}  ✗  {len(issues)} blocking issue(s):{X}")
        for i in issues:
            print(f"     {R}-{X} {i}")
    if fixes:
        print(f"\n{C}{B}  Suggested fixes:{X}")
        for f in fixes:
            print(f"     {C}→{X} {f}")
    return 1 if issues else 0


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="Preflight check for the agentic-app-with-fabric workshop deployment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--region",
                   help="Azure region for Fabric capacity + Cosmos + OpenAI "
                        "(e.g. eastus2, westeurope, israelcentral). "
                        "Overrides AZURE_REGION in backend/.env. "
                        "If neither is set, you'll be prompted.")
    p.add_argument("--openai-resource",
                   help="Pin a specific Azure OpenAI account name to verify")
    p.add_argument("--fix", action="store_true",
                   help="Auto-fix what can be auto-fixed (register providers, "
                        "create Fabric capacity, create OpenAI resource + deployments)")
    p.add_argument("--skip-devcontainer", action="store_true",
                   help="Skip section 1 (use only when running outside the dev container "
                        "and you've installed prereqs manually)")
    args = p.parse_args()

    # Region resolution: --region > AZURE_REGION in .env > prompt
    env_vars = load_env_file(ENV_FILE)
    env_region = env_vars.get("AZURE_REGION", "").strip()
    region = args.region or env_region
    if not region:
        try:
            region = input("Azure region (e.g. eastus2): ").strip()
        except EOFError:
            region = ""
    if not region:
        print(f"{R}✗  No region provided. Set AZURE_REGION in backend/.env or pass --region{X}")
        return 1
    args.region = region

    # Persist resolved region back to backend/.env if missing or different
    if region != env_region:
        write_env_var(ENV_FILE, "AZURE_REGION", region)
        print(f"{C}ℹ  AZURE_REGION={region} written to {ENV_FILE.relative_to(REPO)}{X}")

    # Resource group is read ONLY from backend/.env (AZURE_RESOURCE_GROUP).
    rg = env_vars.get("AZURE_RESOURCE_GROUP", "").strip()
    if not rg:
        print(f"{R}✗  AZURE_RESOURCE_GROUP not set in {ENV_FILE.relative_to(REPO)}{X}")
        print(f"   Add a line like:  AZURE_RESOURCE_GROUP=\"{REPO.name}-rg\"")
        return 1
    args.rg = rg

    print(f"{B}🛫  {REPO.name}  ·  Preflight  ·  region={args.region}  ·  rg={args.rg}{X}")

    if not args.skip_devcontainer:
        check_devcontainer()
    ctx = check_azure_context(fix=args.fix)
    if not ctx:
        return print_summary()
    check_resource_providers(args.fix)
    if not check_region(args.region):
        return print_summary()
    # Acquire Fabric token first so capacity check can fall back to REST API
    token = check_fabric_api()
    check_fabric_capacity(args.region, args.fix, ctx["sub_id"], ctx.get("user_oid"), token=token, rg=args.rg)
    check_openai(args.region, args.openai_resource, fix=args.fix, rg=args.rg)
    return print_summary()


if __name__ == "__main__":
    sys.exit(main())
