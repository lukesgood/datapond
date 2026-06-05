"""
LDAP / Active Directory authentication (environment-configurable).

Enterprise directories are table-stakes for the regulated, on-prem markets DataPond
targets. When LDAP_ENABLED=true, login falls back to an LDAP bind for users not
authenticated locally, then auto-provisions them as auth_method='ldap' users so the
rest of the platform (RBAC, RLS, audit) works unchanged.

All settings come from env (Helm: auth.ldap.*); the bind password is a K8s secret.
Off by default — purely additive, the local admin keeps working.

  LDAP_ENABLED            "true" to enable
  LDAP_URL                ldap://host:389 or ldaps://host:636
  LDAP_BIND_DN            service account DN for search (blank = anonymous search)
  LDAP_BIND_PASSWORD      service account password
  LDAP_USER_BASE          search base, e.g. ou=people,dc=corp,dc=com
  LDAP_USER_FILTER        filter with {username}, e.g. (uid={username}) or
                          (sAMAccountName={username}) for AD
  LDAP_USER_DN_TEMPLATE   optional direct-bind DN, e.g. uid={username},ou=people,dc=corp,dc=com
                          (skips the service-account search entirely)
  LDAP_ATTR_EMAIL         email attribute (default: mail)
  LDAP_ATTR_NAME          display-name attribute (default: cn)
  LDAP_DEFAULT_ROLE       role for LDAP users (default: viewer)
  LDAP_ADMIN_GROUP        optional group DN/CN; members get the admin role
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def ldap_enabled() -> bool:
    return os.getenv("LDAP_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _cfg() -> dict:
    return {
        "url":          os.getenv("LDAP_URL", "").strip(),
        "bind_dn":      os.getenv("LDAP_BIND_DN", "").strip(),
        "bind_pw":      os.getenv("LDAP_BIND_PASSWORD", "").strip(),
        "user_base":    os.getenv("LDAP_USER_BASE", "").strip(),
        "user_filter":  os.getenv("LDAP_USER_FILTER", "(uid={username})").strip(),
        "dn_template":  os.getenv("LDAP_USER_DN_TEMPLATE", "").strip(),
        "attr_email":   os.getenv("LDAP_ATTR_EMAIL", "mail").strip(),
        "attr_name":    os.getenv("LDAP_ATTR_NAME", "cn").strip(),
        "default_role": os.getenv("LDAP_DEFAULT_ROLE", "viewer").strip(),
        "admin_group":  os.getenv("LDAP_ADMIN_GROUP", "").strip(),
    }


def _escape_filter(value: str) -> str:
    """RFC 4515 filter escaping — prevents LDAP injection via the username."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\5c")
        elif ch == "*":
            out.append("\\2a")
        elif ch == "(":
            out.append("\\28")
        elif ch == ")":
            out.append("\\29")
        elif ch == "\x00":
            out.append("\\00")
        else:
            out.append(ch)
    return "".join(out)


def ldap_authenticate(username: str, password: str) -> Optional[dict]:
    """Verify credentials against LDAP. Returns a user dict on success, else None.

    Never authenticates on an empty password (an empty bind is an anonymous bind in
    LDAP, which would succeed without verifying the user)."""
    if not ldap_enabled():
        return None
    if not username or not password:
        return None
    cfg = _cfg()
    if not cfg["url"]:
        logger.warning("[ldap] enabled but LDAP_URL is empty")
        return None

    try:
        from ldap3 import Server, Connection, ALL, SUBTREE
    except Exception as e:  # pragma: no cover
        logger.warning(f"[ldap] ldap3 not installed: {e}")
        return None

    safe = _escape_filter(username)
    try:
        server = Server(cfg["url"], get_info=ALL, connect_timeout=5)
        email = name = None
        member_of = []

        if cfg["dn_template"]:
            # Direct bind — no service account needed.
            user_dn = cfg["dn_template"].format(username=safe)
        else:
            # Search for the user with the (optional) service account.
            search_conn = Connection(
                server,
                user=cfg["bind_dn"] or None,
                password=cfg["bind_pw"] or None,
                auto_bind=True, receive_timeout=10,
            )
            flt = cfg["user_filter"].format(username=safe)
            search_conn.search(
                cfg["user_base"], flt, search_scope=SUBTREE,
                attributes=[cfg["attr_email"], cfg["attr_name"], "memberOf"],
            )
            if not search_conn.entries:
                search_conn.unbind()
                logger.info(f"[ldap] user not found: {username}")
                return None
            entry = search_conn.entries[0]
            user_dn = entry.entry_dn
            email = _attr(entry, cfg["attr_email"])
            name = _attr(entry, cfg["attr_name"])
            member_of = _attr_list(entry, "memberOf")
            search_conn.unbind()

        # Bind AS the user — this is the actual password check.
        user_conn = Connection(server, user=user_dn, password=password, receive_timeout=10)
        if not user_conn.bind():
            logger.info(f"[ldap] bind failed for {username}")
            return None

        # Direct-bind path: fetch attributes now that we're bound.
        if cfg["dn_template"]:
            try:
                user_conn.search(user_dn, "(objectClass=*)", search_scope="BASE",
                                 attributes=[cfg["attr_email"], cfg["attr_name"], "memberOf"])
                if user_conn.entries:
                    e = user_conn.entries[0]
                    email = _attr(e, cfg["attr_email"])
                    name = _attr(e, cfg["attr_name"])
                    member_of = _attr_list(e, "memberOf")
            except Exception:
                pass
        user_conn.unbind()

        role = cfg["default_role"]
        if cfg["admin_group"] and any(cfg["admin_group"].lower() in g.lower() for g in member_of):
            role = "admin"

        return {
            "username": username,
            "email": email or f"{username}@ldap.local",
            "display_name": name or username,
            "role": role,
            "external_id": user_dn,
        }
    except Exception as e:
        logger.warning(f"[ldap] authentication error for {username}: {e}")
        return None


def _attr(entry, name: str):
    try:
        v = entry[name].value
        if isinstance(v, list):
            return v[0] if v else None
        return v
    except Exception:
        return None


def _attr_list(entry, name: str) -> list:
    try:
        v = entry[name].value
        if v is None:
            return []
        return v if isinstance(v, list) else [v]
    except Exception:
        return []
