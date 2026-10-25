import pytest

from slomp import industries as ind


@pytest.fixture(autouse=True)
def _no_learned_words():
    """Each test starts with no learned industry words (industries.use_lexicon), whatever an earlier one set."""
    ind.use_lexicon(None)
    yield
    ind.use_lexicon(None)
