from git_retell import message


def test_trailers_are_dropped_but_prose_is_kept():
    body = (
        "Explain.\n\nCo-Authored-By: A <a@example.invalid>\nSigned-off-by: B\n  folded"
    )
    assert message.without_trailers(body) == "Explain."
    assert message.without_trailers("Co-Authored-By: A") == ""
    assert message.without_trailers("Explain.\n\nNote: still temporary.") == (
        "Explain.\n\nNote: still temporary."
    )
    assert message.without_trailers("Explain.\n\nFixes: #3\nsee above") == (
        "Explain.\n\nFixes: #3\nsee above"
    )
    assert message.without_trailers("Explain.\n\nChapter: Setup\nCc: A") == "Explain."


def test_chapters_come_from_the_final_trailer_paragraph():
    assert message.chapter("Subject\n\nBody.\n\nchapter:  Setup \nCc: A") == "Setup"
    # A chapter line in the prose, or as the subject, starts nothing.
    assert message.chapter("Subject\n\nChapter: Setup\n\nMore prose.") is None
    assert message.chapter("Chapter: Setup") is None
    assert message.chapter_titles("S\n\nChapter:\nChapter: A\nChapter: B") == [
        "",
        "A",
        "B",
    ]
    assert message.chapter("S\n\nChapter:\nChapter: A") == "A"


def test_each_step_belongs_to_the_latest_chapter():
    messages = ["Intro", "A\n\nChapter: One", "B", "C\n\nChapter: Two"]
    assert message.chapters(messages) == [None, (1, "One"), (1, "One"), (2, "Two")]
