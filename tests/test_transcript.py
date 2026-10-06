from atb.transcript import Turn, clean_vtt, to_text


def test_clean_parse_filter_merge_and_sides():
    text = """WEBVTT

cue-id
00:00:01.000 --> 00:00:02.000
<v Jane Doe (Acme Corp)>Yeah!</v>

00:00:03.000 --> 00:00:04.000
<v Jane Doe (Acme Corp)>We need SSO
before renewal.</v>

00:00:04.500 --> 00:00:04.900
<v Jane Doe (Acme Corp)>It is time sensitive.</v>

00:00:05.000 --> 00:00:06.000
<v Alex Smith (Customer Co)>Let's discuss the timeline.

00:00:07.000 --> 00:00:08.000
<v Pat Lee pat@example.internal>We can send a proposal.</v>
"""
    turns = clean_vtt(text, ["example.internal"], ["acme corp"])
    assert turns == [
        Turn(
            "00:00:03",
            "00:00:04",
            "Jane Doe (Acme Corp)",
            "internal",
            "We need SSO before renewal. It is time sensitive.",
        ),
        Turn(
            "00:00:05",
            "00:00:06",
            "Alex Smith (Customer Co)",
            "customer",
            "Let's discuss the timeline.",
        ),
        Turn(
            "00:00:07",
            "00:00:08",
            "Pat Lee pat@example.internal",
            "internal",
            "We can send a proposal.",
        ),
    ]


def test_no_closing_tag_and_format():
    turns = clean_vtt("WEBVTT\n\n00:01:02.120 --> 00:01:05.400\n<v Jane Doe>Hello there, team.")
    assert to_text(turns) == "[00:01:02] Jane Doe (unknown): Hello there, team."
