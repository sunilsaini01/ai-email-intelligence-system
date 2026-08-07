"""
Regression tests for EmailPreprocessor (Module 11).

Why these specific cases: they're the inputs that actually break naive
preprocessing in production — not just "does it run on a clean sentence".
"""

from app.preprocessing.email_preprocessor import EmailPreprocessor, PreprocessingConfig


def test_empty_string_returns_empty_string():
    preprocessor = EmailPreprocessor(PreprocessingConfig(lemmatize=False))
    assert preprocessor.process("") == ""


def test_none_input_returns_empty_string_not_a_crash():
    preprocessor = EmailPreprocessor(PreprocessingConfig(lemmatize=False))
    assert preprocessor.process(None) == ""


def test_non_string_input_returns_empty_string_not_a_crash():
    preprocessor = EmailPreprocessor(PreprocessingConfig(lemmatize=False))
    assert preprocessor.process(12345) == ""


def test_html_tags_are_stripped():
    preprocessor = EmailPreprocessor(PreprocessingConfig(lemmatize=False, lowercase=False))
    result = preprocessor.process("<html><body><p>Hello World</p></body></html>")
    assert "<" not in result
    assert "Hello" in result


def test_email_signature_is_removed():
    preprocessor = EmailPreprocessor(PreprocessingConfig(lemmatize=False, lowercase=False))
    result = preprocessor.process("Meeting at 5pm.\n--\nJohn Smith\nAI Engineer")
    assert "Meeting at 5pm." in result
    assert "AI Engineer" not in result


def test_process_never_raises_on_malformed_html():
    # BeautifulSoup is generally forgiving, but the preprocessor's own contract
    # (see its docstring) is "never raises — empty string on total failure".
    # This locks that contract in as a test, not just a comment.
    preprocessor = EmailPreprocessor(PreprocessingConfig(lemmatize=False))
    result = preprocessor.process("<div><span>unclosed tags <b>everywhere")
    assert isinstance(result, str)
