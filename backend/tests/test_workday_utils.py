"""Unit tests for Workday tenant extraction utilities."""

import pytest

from app.utils.workday import extract_tenant_from_sender, extract_workday_tenant


class TestExtractWorkdayTenant:
    """Tests for extract_workday_tenant(source_url)."""

    @pytest.mark.parametrize(
        "url, expected",
        [
            ("https://meredith.wd1.myworkdayjobs.com/en-US/careers/job/SWE_R123", "meredith"),
            ("https://meredith.wd3.myworkdayjobs.com/jobs/job/Role_JR456", "meredith"),
            ("https://acme.wd5.myworkdayjobs.com/External/job/NYC/Engineer_R789", "acme"),
            ("https://bigcorp.wd501.myworkdayjobs.com/careers/job/Analyst", "bigcorp"),
        ],
    )
    def test_myworkdayjobs_variants(self, url, expected):
        assert extract_workday_tenant(url) == expected

    def test_myworkday_com(self):
        assert extract_workday_tenant("https://acme.myworkday.com/acme/d/home") == "acme"

    def test_myworkdaysite_com(self):
        assert extract_workday_tenant("https://bigco.myworkdaysite.com/en/careers") == "bigco"

    def test_non_workday_url_returns_none(self):
        assert extract_workday_tenant("https://www.google.com/careers") is None

    def test_none_returns_none(self):
        assert extract_workday_tenant(None) is None

    def test_empty_string_returns_none(self):
        assert extract_workday_tenant("") is None

    def test_case_insensitive(self):
        assert extract_workday_tenant("https://ACME.WD5.MYWORKDAYJOBS.COM/jobs") == "acme"

    def test_no_scheme_returns_none(self):
        assert extract_workday_tenant("not-a-url") is None

    def test_greenhouse_url_returns_none(self):
        assert extract_workday_tenant("https://boards.greenhouse.io/company/jobs/123") is None

    def test_lever_url_returns_none(self):
        assert extract_workday_tenant("https://jobs.lever.co/company/abc-123") is None


class TestExtractTenantFromSender:
    """Tests for extract_tenant_from_sender(sender_email)."""

    def test_normal_tenant(self):
        assert extract_tenant_from_sender("meredith@myworkday.com") == "meredith"

    def test_display_name_format(self):
        assert extract_tenant_from_sender("Workday <meredith@myworkday.com>") == "meredith"

    def test_display_name_with_quotes(self):
        assert extract_tenant_from_sender('"Meredith HR" <meredith@myworkday.com>') == "meredith"

    @pytest.mark.parametrize("shared", ["myview", "noreply", "donotreply", "no-reply", "workday"])
    def test_shared_senders_return_none(self, shared):
        assert extract_tenant_from_sender(f"{shared}@myworkday.com") is None

    def test_shared_sender_case_insensitive(self):
        assert extract_tenant_from_sender("NoReply@myworkday.com") is None

    def test_non_myworkday_domain_returns_none(self):
        assert extract_tenant_from_sender("meredith@myworkdayjobs.com") is None

    def test_subdomain_returns_none(self):
        assert extract_tenant_from_sender("info@sub.myworkday.com") is None

    def test_none_returns_none(self):
        assert extract_tenant_from_sender(None) is None

    def test_empty_string_returns_none(self):
        assert extract_tenant_from_sender("") is None

    def test_no_at_sign_returns_none(self):
        assert extract_tenant_from_sender("not-an-email") is None

    def test_case_insensitive_tenant(self):
        assert extract_tenant_from_sender("ACME@myworkday.com") == "acme"

    def test_case_insensitive_domain(self):
        assert extract_tenant_from_sender("acme@MYWORKDAY.COM") == "acme"
