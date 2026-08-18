"""Quoted-reply splitting for ticket messages that arrived by e-mail."""

from app.integrations.email.quoting import split_quoted_reply

_STECK_MAIL = """Hallo.

Ja... Wir haben gestern in der ETV auch über Probleme mit den Mietern gesprochen.
Liebe Grüße...

Wagner Hausverwaltung Support <support@wagner-hausverwaltung.com>
schrieb am Di., 18. Aug. 2026, 10:10:

> Neue Nachricht zu Ticket #01a0109c4c807b51
>
> *Problemprotokoll*
"""


def test_gmail_style_german_reply_header_is_cut() -> None:
    visible, quoted = split_quoted_reply(_STECK_MAIL)
    assert visible.endswith("Liebe Grüße...")
    assert "schrieb am" not in visible
    assert quoted is not None and quoted.startswith("Wagner Hausverwaltung Support")


def test_apple_mail_am_schrieb_header() -> None:
    body = "Danke, passt.\n\nAm 18.08.2026 um 10:10 schrieb Max Mustermann <m@x.de>:\n> alt"
    visible, quoted = split_quoted_reply(body)
    assert visible == "Danke, passt."
    assert quoted is not None and "schrieb Max" in quoted


def test_english_on_wrote_header() -> None:
    body = "Fine by me.\n\nOn Tue, Aug 18, 2026 at 10:10 AM WHV <s@w.de> wrote:\n> old"
    visible, quoted = split_quoted_reply(body)
    assert visible == "Fine by me."
    assert quoted is not None


def test_outlook_von_gesendet_block() -> None:
    body = (
        "Erledigt.\n\nVon: WHV Support\nGesendet: Dienstag, 18. August 2026 10:10\n"
        "An: Steck\nBetreff: Ticket\n\nalt"
    )
    visible, quoted = split_quoted_reply(body)
    assert visible == "Erledigt."
    assert quoted is not None and quoted.startswith("Von:")


def test_bare_gt_block_at_end_is_cut() -> None:
    body = "Kurz: ja.\n\n> Frage eins\n> Frage zwei\n"
    visible, quoted = split_quoted_reply(body)
    assert visible == "Kurz: ja."
    assert quoted == "> Frage eins\n> Frage zwei"


def test_von_alone_mid_text_is_not_a_header() -> None:
    """'Von:' also opens ordinary sentences — only a real Outlook block cuts."""
    body = "Von: mir aus gerne.\nWir machen das so.\nGruß"
    visible, quoted = split_quoted_reply(body)
    assert visible == body
    assert quoted is None


def test_pure_quote_keeps_body_rather_than_showing_nothing() -> None:
    body = "> nur zitiert\n> sonst nichts"
    visible, quoted = split_quoted_reply(body)
    assert visible == body
    assert quoted is None


def test_plain_message_untouched() -> None:
    body = "Hallo,\n\nkönnen Sie bitte den Schlüssel bringen?\n\nDanke"
    assert split_quoted_reply(body) == (body, None)


def test_empty_body() -> None:
    assert split_quoted_reply("") == ("", None)
