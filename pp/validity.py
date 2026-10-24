"""Passport validity vs the fixed reference date 2026-10-01.

Rule (RF internal passport):
    age at issue < 14          -> invalid outright (no such passport);
    issue age 14..19           -> expires on the holder's 20th birthday;
    issue age 20..44           -> expires on the holder's 45th birthday;
    issue age >= 45            -> no expiry.
BOUNDARY (fixed per plan): an expiry date ON the reference date already counts
as expired -> invalid. (exp > target required to be valid.)

Sanity anchor: computing this on train labels yields exactly 105 invalid docs.
"""
from datetime import date

from .constants import TARGET_DATE


def _birthday_in(year, birth):
    """birth date shifted to the given year (Feb 29 -> Feb 28 fallback)."""
    try:
        return date(year, birth.month, birth.day)
    except ValueError:
        return date(year, birth.month, 28)


def age_at(birth, issue):
    """Exact age in whole years on the issue date."""
    return issue.year - birth.year - ((issue.month, issue.day) < (birth.month, birth.day))


def expiry_date(birth, issue):
    """Expiry date of the passport, or None if it never expires.

    Returns (expiry, reason). Assumes issue >= birth + 14 years.
    """
    age = age_at(birth, issue)
    if age < 14:
        return None, "issue_age_under_14"
    if age < 20:
        return _birthday_in(birth.year + 20, birth), "expires_at_20"
    if age < 45:
        return _birthday_in(birth.year + 45, birth), "expires_at_45"
    return None, "no_expiry"


def is_valid(birth, issue, target=None):
    """(valid: bool, reason: str) for the passport on the target date.

    birth/issue are datetime.date. Invalid when: age at issue < 14, or the
    expiry date is <= target (expiry ON target date is already invalid).
    """
    target = target or TARGET_DATE
    if issue < birth:
        return False, "issue_before_birth"
    age = age_at(birth, issue)
    if age < 14:
        return False, "issue_age_under_14"
    exp, why = expiry_date(birth, issue)
    if exp is not None and exp <= target:
        return False, why
    return True, "valid"
