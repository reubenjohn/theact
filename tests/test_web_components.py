"""Unit tests for StreamingTextBlock._text_to_html.

Uses object.__new__() to bypass __init__ (which requires NiceGUI context),
then sets _color manually. The _text_to_html method is stateless aside from
self._color, so this is safe.
"""

from __future__ import annotations


from theact.web.components import StreamingTextBlock


def _make_bare_block(color: str = "#ffffff") -> StreamingTextBlock:
    """Create a StreamingTextBlock without invoking __init__."""
    block = object.__new__(StreamingTextBlock)
    block._color = color
    return block


class TestTextToHtml:
    """Tests for StreamingTextBlock._text_to_html."""

    def test_plain_text_wrapped_in_div(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("hello")
        assert result.startswith("<div ")
        assert result.endswith("</div>")
        assert ">hello</div>" in result

    def test_html_entities_escaped(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result
        assert "alert(&#x27;xss&#x27;)" in result

    def test_newlines_become_br(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("line1\nline2")
        assert "line1<br>line2" in result
        assert "\n" not in result

    def test_ampersand_escaped(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("A & B")
        assert "A &amp; B" in result
        assert "A & B" not in result

    def test_color_applied(self) -> None:
        block = _make_bare_block(color="#ff0000")
        result = block._text_to_html("test")
        assert "color: #ff0000" in result

    def test_empty_string(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("")
        assert result.startswith("<div ")
        assert result.endswith("></div>")
        # The div should contain no visible text content
        inner = result.split(">", 1)[1].rsplit("</div>", 1)[0]
        assert inner == ""

    def test_whitespace_preserved_via_pre_wrap(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("some text")
        assert "pre-wrap" in result

    # --- Additional edge cases ---

    def test_consecutive_newlines(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("a\n\nb")
        assert "a<br><br>b" in result

    def test_double_escape_of_existing_entities(self) -> None:
        """Text that already contains '&amp;' should be double-escaped."""
        block = _make_bare_block()
        result = block._text_to_html("&amp;")
        # The '&' in '&amp;' gets escaped to '&amp;', so full result is '&amp;amp;'
        assert "&amp;amp;" in result

    def test_quotes_in_text(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("He said \"hello\" and she said 'hi'")
        # html.escape() with default quote=True escapes both " and '
        assert "&quot;hello&quot;" in result
        assert "&#x27;hi&#x27;" in result

    def test_double_quotes_escaped(self) -> None:
        """html.escape() escapes double quotes to &quot; by default."""
        block = _make_bare_block()
        result = block._text_to_html('say "hi"')
        assert "say &quot;hi&quot;" in result

    def test_tab_characters(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("col1\tcol2")
        # Tabs are not escaped by html.escape; they remain as-is
        assert "col1\tcol2" in result
        # pre-wrap in CSS means the browser will render the tab
        assert "pre-wrap" in result

    def test_mixed_newlines_and_html_chars(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("<b>bold</b>\n&more")
        assert "&lt;b&gt;bold&lt;/b&gt;<br>&amp;more" in result

    def test_unicode_characters(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("Hello \u2014 world \u2603 \U0001f600")
        assert "\u2014" in result  # em-dash preserved
        assert "\u2603" in result  # snowman preserved
        assert "\U0001f600" in result  # emoji preserved

    def test_very_long_text(self) -> None:
        block = _make_bare_block()
        long_text = "x" * 10_000
        result = block._text_to_html(long_text)
        assert len(result) > 10_000
        assert "x" * 100 in result

    def test_only_newlines(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("\n\n\n")
        assert "<br><br><br>" in result

    def test_leading_and_trailing_whitespace(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("  hello  ")
        # Whitespace is preserved in the HTML (rendered by pre-wrap)
        assert "  hello  " in result

    def test_less_than_and_greater_than(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("1 < 2 > 0")
        assert "1 &lt; 2 &gt; 0" in result

    def test_default_color(self) -> None:
        block = _make_bare_block()  # default is #ffffff
        result = block._text_to_html("test")
        assert "color: #ffffff" in result

    def test_color_with_named_color(self) -> None:
        block = _make_bare_block(color="red")
        result = block._text_to_html("test")
        assert "color: red" in result

    def test_newline_at_end(self) -> None:
        block = _make_bare_block()
        result = block._text_to_html("text\n")
        assert "text<br>" in result
