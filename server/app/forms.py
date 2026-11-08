"""Parse and validate the add/edit service form for any integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .integrations import Integration


@dataclass
class ParsedForm:
    common: dict[str, Any]
    config: dict[str, Any]
    secrets: dict[str, str]
    errors: list[str]


def is_http_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises ValueError for an invalid port
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def has_credentials(value: str) -> bool:
    """True for URLs like http://user:pass@host. Those would be stored and shown unencrypted."""
    parts = urlsplit(value)
    return bool(parts.username or parts.password)


CREDENTIALS_IN_URL = ("{label} must not contain a username or password. "
                      "Use the separate login fields (they are stored encrypted).")


def default_config(cls: type[Integration]) -> dict[str, Any]:
    return {f.name: f.default for f in cls.config_fields()}


def _text(form: Mapping[str, Any], name: str) -> str:
    value = form.get(name)
    return value.strip() if isinstance(value, str) else ""


def _range_error(label: str, lo: int | None, hi: int | None) -> str:
    if lo is not None and hi is not None:
        return f"{label} must be between {lo} and {hi}."
    if lo is not None:
        return f"{label} must be at least {lo}."
    return f"{label} must be at most {hi}."


NEW_CATEGORY = "__new__"


def _parse_category(form: Mapping[str, Any], errors: list[str]) -> str:
    """Category comes from the dropdown (existing or "+ new") or a plain text field."""
    if "category_choice" not in form:
        return _text(form, "category")  # plain text field (API clients, older forms)
    choice = _text(form, "category_choice")
    new = _text(form, "category_new")
    if choice == NEW_CATEGORY:
        if not new:
            errors.append("Enter a name for the new category, or pick an existing one.")
        return new
    # Without JavaScript the "new" box is always visible; honour it if no category was picked.
    return choice or new


def parse_service_form(
    cls: type[Integration], form: Mapping[str, Any], existing_secrets: dict[str, str]
) -> ParsedForm:
    errors: list[str] = []

    name = _text(form, "name")
    category = _parse_category(form, errors)
    link_url = _text(form, "link_url")
    if not name:
        errors.append("Name is required.")
    elif len(name) > 100:
        errors.append("Name must be 100 characters or fewer.")
    if len(category) > 50:
        errors.append("Category must be 50 characters or fewer.")
    if link_url and not is_http_url(link_url):
        errors.append("Link URL must start with http:// or https://.")
    elif link_url and has_credentials(link_url):
        errors.append(CREDENTIALS_IN_URL.format(label="Link URL"))
    common = {
        "name": name,
        "category": category,
        "link_url": link_url,
        "enabled": form.get("enabled") is not None,
    }

    config: dict[str, Any] = {}
    field_errors = False
    for f in cls.config_fields():
        if f.kind == "bool":
            config[f.name] = form.get(f.name) is not None
            continue
        raw = _text(form, f.name)
        if not raw:
            if f.required:
                errors.append(f"{f.label} is required.")
                field_errors = True
            config[f.name] = f.default
            continue
        if f.kind == "int":
            try:
                value = int(raw)
            except ValueError:
                errors.append(f"{f.label} must be a whole number.")
                field_errors = True
                config[f.name] = raw
                continue
            too_low = f.min_value is not None and value < f.min_value
            too_high = f.max_value is not None and value > f.max_value
            if too_low or too_high:
                errors.append(_range_error(f.label, f.min_value, f.max_value))
                field_errors = True
            config[f.name] = value
        elif f.kind == "url":
            if not is_http_url(raw):
                errors.append(f"{f.label} must start with http:// or https://.")
                field_errors = True
            elif has_credentials(raw):
                errors.append(CREDENTIALS_IN_URL.format(label=f.label))
                field_errors = True
            config[f.name] = raw
        else:
            config[f.name] = raw

    if not field_errors:
        errors.extend(cls.validate_config(config))

    secrets = dict(existing_secrets)
    for f in cls.secret_fields():
        if form.get(f"clear__{f.name}") is not None:
            secrets.pop(f.name, None)
        raw = form.get(f.name)
        if isinstance(raw, str) and raw.strip():
            secrets[f.name] = raw.strip()
        if f.required and f.name not in secrets:
            errors.append(f"{f.label} is required.")

    return ParsedForm(common=common, config=config, secrets=secrets, errors=errors)
