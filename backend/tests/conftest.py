"""Shared pytest fixtures for EmailPet backend tests."""
import pytest


@pytest.fixture
def fake_imap():
    """Returns a mock IMAP client. Tests fill in behavior as needed."""
    pass


@pytest.fixture
def fake_smtp():
    """Returns a mock SMTP client."""
    pass


@pytest.fixture
def mock_llm_response():
    """Returns mock LLM structured output."""
    pass
