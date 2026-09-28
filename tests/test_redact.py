"""redact_text unit tests. All secret-shaped values here are synthetic and
invented for this test file -- none are drawn from the real vault (see
redact.py's module docstring and the redaction plan this was built against:
"Never log, store, print, or include an actual secret value ... Test
fixtures must use synthetic invented values.")."""

from __future__ import annotations

from atb.redact import redact_text


def test_base64_blob_alone_on_a_line_is_redacted():
    blob = "QWxhZGRpbjpvcGVuIHNlc2FtZQBhbGFkZGluc2VjcmV0dmFsdWVzeW50aGV0aWM=="
    assert len(blob) >= 60
    text = f"Trial server creds:\n{blob}\nend of note."
    result = redact_text(text)
    assert blob not in result.text
    assert "[REDACTED:TOKEN]" in result.text
    assert len(result.findings) == 1
    assert result.findings[0].rule == "base64_blob"
    assert result.findings[0].line_number == 2


def test_bare_long_alphanumeric_run_is_redacted():
    token = "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz01"
    assert len(token) >= 60
    text = f"POC instance token:\n{token}\n"
    result = redact_text(text)
    assert token not in result.text
    assert result.findings[0].rule == "bare_token"


def test_pw_label_line_redacts_value_keeps_label():
    text = "Trial URL: https://example.poc.blackduck.com\npw: Sup3r$ecretVal9!"
    result = redact_text(text)
    assert "Sup3r$ecretVal9!" not in result.text
    assert "pw: [REDACTED:PASSWORD]" in result.text
    assert result.findings[0].rule == "pw_label_line"


def test_pw_label_mid_line_redacts_value_keeps_surrounding_prose():
    """pw: does not have to be at line start -- e.g. a sentence describing
    account creation with the password tacked on at the end."""
    value = "Zz9!qWpL2#Rt6$"
    text = f'created new user "test" pw: {value}'
    result = redact_text(text)
    assert value not in result.text
    assert 'created new user "test" pw:' in result.text
    assert "[REDACTED:PASSWORD]" in result.text
    assert result.findings[0].rule == "pw_label_line"


def test_password_and_pwd_labels_mid_line_are_redacted():
    value1 = "Xy1@Za2#Bc3$"
    value2 = "Qw9!Er8@Ty7#"
    text = f"Notes: password: {value1}\nAlso pwd: {value2}\n"
    result = redact_text(text)
    assert value1 not in result.text
    assert value2 not in result.text
    assert "Notes: password: [REDACTED:PASSWORD]" in result.text
    assert "Also pwd: [REDACTED:PASSWORD]" in result.text
    rules = [f.rule for f in result.findings]
    assert rules.count("pw_label_line") == 2


def test_bare_credential_near_trial_url_is_redacted():
    token = "Qx7$mK2!pLzR9vTn3Bq5"  # synthetic, 20 chars, 4 char classes
    assert len(token) == 20
    text = f"Trial URL: https://sca999.poc.example.com/\n\n{token}\n"
    result = redact_text(text)
    assert token not in result.text
    assert result.findings[0].rule == "bare_credential_near_trial_url"


def test_title_cased_word_near_trial_url_is_not_redacted():
    """Only 2 character classes (upper+lower) -- an ordinary Title-Cased
    word/product name, not a credential -- so the diversity gate rejects it
    even though it sits right next to a trial URL."""
    text = "Trial URL: https://sca999.poc.example.com/\n\nKubernetesClusterOnePr\n"
    result = redact_text(text)
    assert "KubernetesClusterOnePr" in result.text
    assert result.findings == []


def test_lowercase_digit_version_string_near_trial_url_is_not_redacted():
    """Only 2 character classes (lower+digit) -- a version-string-shaped
    token, not a credential."""
    text = "Trial URL: https://sca999.poc.example.com/\n\nrelease2026buildxyzz\n"
    result = redact_text(text)
    assert "release2026buildxyzz" in result.text
    assert result.findings == []


def test_mixed_class_bare_token_with_no_nearby_trial_context_is_not_redacted():
    """Same shape/diversity as the positive case, but nothing nearby says
    'this is a credential neighborhood' -- proximity gate must hold."""
    token = "Qx7$mK2!pLzR9vTn3Bq5"
    text = f"Some unrelated notes about the roadmap.\n\n{token}\n\nMore unrelated notes.\n"
    result = redact_text(text)
    assert token in result.text
    assert result.findings == []


def test_semver_and_git_sha_near_trial_url_are_not_redacted():
    text = (
        "Trial URL: https://sca999.poc.example.com/\n"
        "v1.2.3-beta.10\n"
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0\n"
    )
    result = redact_text(text)
    assert "v1.2.3-beta.10" in result.text
    assert "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0" in result.text
    assert result.findings == []


def test_json_credential_key_value_is_redacted():
    text = '{"llmKey":"synthetic-fake-key-value-12345","other":"keepme"}'
    result = redact_text(text)
    assert "synthetic-fake-key-value-12345" not in result.text
    assert '"llmKey":"[REDACTED:SECRET]"' in result.text
    assert "keepme" in result.text
    assert result.findings[0].rule == "json_secret_value"


def test_standalone_label_line_redacts_next_nonblank_line():
    text = "token\nsyntheticTokenValue1234567890\n"
    result = redact_text(text)
    assert "syntheticTokenValue1234567890" not in result.text
    assert result.findings[0].rule == "standalone_label"
    assert result.findings[0].line_number == 2


def test_new_token_with_date_label_variant_is_redacted():
    text = "new token 2026-01-05\nsyntheticvalue999\n"
    result = redact_text(text)
    assert "syntheticvalue999" not in result.text
    assert result.findings[0].rule == "standalone_label"


def test_trial_account_username_and_password_pair_redacted():
    text = "Trial Account\n    synthuser\n    synthpass1\nmore notes here"
    result = redact_text(text)
    assert "synthuser" not in result.text
    assert "synthpass1" not in result.text
    rules = [f.rule for f in result.findings]
    assert "trial_account_username" in rules
    assert "trial_account_password" in rules


def test_trial_account_title_cased_name_is_not_redacted():
    """The 'not Title-Cased' gate exists so a real contact name under a
    heading (rather than a generic credential) survives."""
    text = "Trial Account\n    Jordan\n    Smith"
    result = redact_text(text)
    assert "Jordan" in result.text
    assert "Smith" in result.text
    assert result.findings == []


def test_email_address_is_never_redacted():
    """Deliberate rejection (see redact.py docstring): a genuine customer
    contact email is structurally indistinguishable from an internal POC
    alias, and contacts are the product's primary extraction target. Emails
    are left alone entirely, always."""
    text = "Key contact: Jamie Rivera, jamie.rivera@customercompany.com"
    result = redact_text(text)
    assert "jamie.rivera@customercompany.com" in result.text
    assert result.findings == []


def test_bare_label_words_in_prose_are_not_redacted():
    text = (
        "Jamie doesn't have admin level access yet.\n"
        "They will need to login with their own user account.\n"
    )
    result = redact_text(text)
    assert result.text == text
    assert result.findings == []


def test_fenced_code_block_placeholder_is_not_redacted():
    text = "```bash\ncurl -H \"Authorization: Bearer $BD_TOKEN\" -a TOKEN https://api.example.com\n```"
    result = redact_text(text)
    assert "$BD_TOKEN" in result.text
    assert "-a TOKEN" in result.text
    assert result.findings == []


def test_title_cased_contact_with_job_title_is_not_redacted():
    text = "Attendee: Alex Morgan, VP of Engineering"
    result = redact_text(text)
    assert result.text == text
    assert result.findings == []


def test_trial_url_itself_is_not_redacted():
    text = "Trial instance: https://acme-corp.poc.blackduck.com/login"
    result = redact_text(text)
    assert result.text == text
    assert result.findings == []


def test_customer_account_label_redacts_username_and_password_pair():
    """Generalization of the 'label line, then username + password' pattern
    beyond the literal 'Trial Account' heading -- e.g. 'Customer account:'."""
    username = "fluke"  # synthetic, 5 lowercase chars
    password = "x1N2IN#7x9OI"  # synthetic, 12 chars, 4 char classes
    text = f"Customer account:\n{username}\n{password}\n"
    result = redact_text(text)
    assert username not in result.text
    assert password not in result.text
    rules = [f.rule for f in result.findings]
    assert "credential_pair_username" in rules
    assert "credential_pair_password" in rules


def test_login_label_with_single_bare_token_is_redacted():
    value = "Zz9!qWpL2#Rt"  # synthetic, mixed-class
    text = f"Login:\n{value}\nmore notes\n"
    result = redact_text(text)
    assert value not in result.text
    rules = [f.rule for f in result.findings]
    assert "credential_pair_value" in rules


def test_contacts_label_with_title_cased_names_is_not_redacted():
    """CRITICAL false-positive guard: a colon-labeled contact list with
    bare, no-space, Title-Cased names must never be redacted -- contacts are
    the product's primary extraction target."""
    text = "Contacts:\nMarcus\nVinitha\n"
    result = redact_text(text)
    assert result.text == text
    assert result.findings == []


def test_attendees_label_with_title_cased_names_is_not_redacted():
    text = "Attendees:\nJordan\nPriya\n"
    result = redact_text(text)
    assert result.text == text
    assert result.findings == []


def test_colon_label_followed_by_markdown_bullets_is_not_redacted():
    text = "Notes:\n- first item\n- second item\n"
    result = redact_text(text)
    assert result.text == text
    assert result.findings == []


def test_widened_window_catches_bare_credential_four_lines_from_trial_url():
    """+-5 non-blank-line window (widened from +-3) now reaches a mixed-class
    bare token 4 non-blank lines away from a trial URL."""
    token = "Qx7$mK2!pLzR9vTn3Bq5"  # synthetic, 20 chars, 4 char classes
    text = (
        "Trial URL: https://sca999.poc.example.com/\n"
        "line two\n"
        "line three\n"
        "line four\n"
        f"{token}\n"
    )
    result = redact_text(text)
    assert token not in result.text
    assert result.findings[0].rule == "bare_credential_near_trial_url"


def test_bare_credential_eight_lines_from_trial_url_still_not_redacted():
    """Outside the +-5 window entirely -- proximity gate must still hold."""
    token = "Qx7$mK2!pLzR9vTn3Bq5"
    text = (
        "Trial URL: https://sca999.poc.example.com/\n"
        "line two\n"
        "line three\n"
        "line four\n"
        "line five\n"
        "line six\n"
        "line seven\n"
        f"{token}\n"
    )
    result = redact_text(text)
    assert token in result.text
    assert result.findings == []


def test_findings_never_contain_the_secret_value():
    blob = "QWxhZGRpbjpvcGVuIHNlc2FtZQBhbGFkZGluc2VjcmV0dmFsdWVzeW50aGV0aWM=="
    text = f"pw: {'x' * 25}!Aa1\n{blob}\n"
    result = redact_text(text)
    for finding in result.findings:
        # Finding is a plain dataclass with exactly rule/line_number/length --
        # assert none of its field values is or contains the raw secret text.
        assert blob not in repr(finding)
        assert "x" * 25 not in repr(finding)
        assert isinstance(finding.redacted_length, int)
