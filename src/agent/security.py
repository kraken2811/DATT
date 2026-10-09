"""Runtime policy shared by API, tools and checkpoint initialization."""
import os


def persistent_history_required() -> bool:
    return os.getenv('DATT_REQUIRE_PERSISTENCE') == '1'


def production_auth_required() -> bool:
    return persistent_history_required() or os.getenv('DATT_ENVIRONMENT', '').lower() in ('production', 'prod')


def operational_auth_required() -> bool:
    return production_auth_required() or any(os.getenv(k) == '1' for k in
        ('DATT_STRICT_AUTH', 'DATT_REQUIRE_OPERATIONAL_AUTH'))
