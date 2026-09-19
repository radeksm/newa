"""Validate-config command for NEWA CLI."""

import re
from typing import Optional

import click
import requests

from newa import CLIContext

try:
    from requests_kerberos import OPTIONAL, HTTPKerberosAuth
    KERBEROS_AVAILABLE = True
except ImportError:
    KERBEROS_AVAILABLE = False


def _test_errata_tool(ctx: CLIContext) -> tuple[bool, str, Optional[str]]:
    url = ctx.settings.et_url
    if not url:
        return False, "No URL configured", None

    endpoint = f"{url}/api/v1/erratum/1"

    if not KERBEROS_AVAILABLE:
        return (False,
                "requests-kerberos not installed (pip install requests-kerberos)",
                endpoint)
    try:
        auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
        response = requests.get(endpoint, auth=auth, timeout=10, verify=True)

        if response.status_code == 200:
            return True, "Connected with Kerberos auth", endpoint
        elif response.status_code == 401:
            return False, "Kerberos auth failed - no valid ticket (run: kinit)", endpoint
        elif response.status_code == 403:
            return False, "Authenticated but forbidden (HTTP 403)", endpoint
        elif response.status_code == 404:
            return True, "Authenticated (test erratum not found, but auth succeeded)", endpoint
        else:
            return True, f"Connected (HTTP {response.status_code})", endpoint
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection failed: {e}", endpoint
    except requests.exceptions.Timeout:
        return False, "Request timeout", endpoint
    except Exception as e:
        if "kerberos" in str(e).lower():
            return False, f"Kerberos error: {e} (try: kinit)", endpoint
        return False, f"Error: {e}", endpoint


def _test_jira(ctx: CLIContext) -> tuple[bool, str, Optional[str]]:
    url = ctx.settings.jira_url
    token = ctx.settings.jira_token
    email = ctx.settings.jira_email

    if not url or not token:
        return False, "URL or token not configured", None

    endpoint = f"{url}/rest/api/3/myself"
    try:
        # Jira Cloud requires Basic Auth (email:token), not Bearer token
        response = requests.get(
            endpoint,
            auth=(email, token) if email else ("", token),
            timeout=10,
            verify=True,
            )
        if response.status_code == 200:
            data = response.json()
            user = data.get("displayName", data.get("name", "Unknown"))
            return True, f"Authenticated as: {user}", endpoint
        elif response.status_code == 401:
            return False, "Invalid token (HTTP 401)", endpoint
        elif response.status_code == 403:
            return False, "Forbidden (HTTP 403)", endpoint
        else:
            return False, f"Failed (HTTP {response.status_code})", endpoint
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection failed: {e}", endpoint
    except requests.exceptions.Timeout:
        return False, "Request timeout", endpoint
    except Exception as e:
        return False, f"Error: {e}", endpoint


def _test_reportportal(ctx: CLIContext) -> tuple[bool, str, Optional[str]]:
    url = ctx.settings.rp_url
    token = ctx.settings.rp_token
    project = ctx.settings.rp_project

    if not url or not token:
        return False, "URL or token not configured", None

    # rp_url already has trailing slash stripped by Settings.load()
    if project:
        endpoint = f"{url}/api/v1/{project}/launch"
    else:
        endpoint = f"{url}/api/v1/user"

    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=10,
            verify=True,
            params={"limit": 1},
            )
        if response.status_code == 200:
            project_info = f" | Project: {project}" if project else ""
            return True, f"Connected and authenticated{project_info}", endpoint
        elif response.status_code == 401:
            return False, "Invalid token (HTTP 401)", endpoint
        elif response.status_code == 403:
            return False, "Forbidden (HTTP 403)", endpoint
        elif response.status_code == 404:
            return False, "Endpoint not found (HTTP 404) - URL or project may be wrong", endpoint
        else:
            return False, f"Failed (HTTP {response.status_code})", endpoint
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection failed: {e}", endpoint
    except requests.exceptions.Timeout:
        return False, "Request timeout", endpoint
    except Exception as e:
        return False, f"Error: {e}", endpoint


def _test_testing_farm(ctx: CLIContext) -> tuple[bool, str, Optional[str]]:
    token = ctx.settings.tf_token

    if not token:
        return False, "Token not configured", None

    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, token):
        return False, f"Invalid token format (expected UUID, got: {token[:20]}...)", None

    endpoint = "https://api.testing-farm.io/v0.1/requests"
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(
            endpoint,
            headers=headers,
            timeout=10,
            verify=True,
            params={"limit": 1},
            )
        if response.status_code == 200:
            return True, "Token valid (can access API)", endpoint
        elif response.status_code == 401:
            return False, "Invalid token (HTTP 401)", endpoint
        elif response.status_code in [403, 404]:
            return False, f"Authorization failed (HTTP {response.status_code})", endpoint
        else:
            return True, f"Connected (HTTP {response.status_code})", endpoint
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection failed: {e}", endpoint
    except requests.exceptions.Timeout:
        return False, "Request timeout", endpoint
    except Exception as e:
        return False, f"Error: {e}", endpoint


def _test_rog(ctx: CLIContext) -> tuple[bool, str, Optional[str]]:
    token = ctx.settings.rog_token

    if not token:
        return False, "Token not configured (optional)", None

    # RoG GitLab URL is not stored in Settings, use the known internal instance
    url = "https://gitlab.engineering.redhat.com"
    endpoint = f"{url}/api/v4/user"
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(endpoint, headers=headers, timeout=10, verify=True)
        if response.status_code == 200:
            data = response.json()
            username = data.get("username", "Unknown")
            return True, f"Authenticated as: {username}", endpoint
        elif response.status_code == 401:
            return False, "Invalid token (HTTP 401)", endpoint
        else:
            return False, f"Failed (HTTP {response.status_code})", endpoint
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection failed: {e}", endpoint
    except requests.exceptions.Timeout:
        return False, "Request timeout", endpoint
    except Exception as e:
        return False, f"Error: {e}", endpoint


@click.command(name='validate-config')
@click.pass_obj
def cmd_validate_config(ctx: CLIContext) -> None:
    """Validate connectivity and authentication for all configured API endpoints."""
    ctx.enter_command('validate')

    tests = [
        ("Errata Tool", _test_errata_tool),
        ("Jira", _test_jira),
        ("ReportPortal", _test_reportportal),
        ("Testing Farm", _test_testing_farm),
        ("RoG (GitLab)", _test_rog),
    ]

    click.echo("=" * 70)
    click.echo("NEWA Configuration Validation")
    click.echo("=" * 70)
    click.echo()

    results: dict[str, tuple[bool, str]] = {}
    urls_tested: dict[str, str] = {}

    for name, test_func in tests:
        click.echo(f"Testing {name}...", nl=False)
        success, message, endpoint = test_func(ctx)
        results[name] = (success, message)
        if endpoint:
            urls_tested[name] = endpoint
        status = click.style("✓", fg="green") if success else click.style("✗", fg="red")
        click.echo(f" {status} {message}")

    click.echo()
    click.echo("=" * 70)
    click.echo("Summary")
    click.echo("=" * 70)

    passed = sum(1 for success, _ in results.values() if success)
    total = len(results)
    click.echo(f"Passed: {passed}/{total}")
    click.echo()

    click.echo("URLs tested:")
    for name, url in urls_tested.items():
        click.echo(f"  • {name}:")
        click.echo(f"    {url}")
    click.echo()

    if passed < total:
        click.echo("Failed services:")
        for name, (success, message) in results.items():
            if not success:
                click.echo(f"  • {name}: {message}")
        click.echo()
