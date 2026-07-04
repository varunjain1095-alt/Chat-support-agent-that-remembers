import sys

def test_p0_01_dependency_install():
    """P0-01 [UNIT] — Dependency install check: verify all required packages are importable."""
    import anthropic
    import mem0
    import zep_cloud
    import openai
    import dotenv
    import pytest
    
    assert anthropic is not None
    assert mem0 is not None
    assert zep_cloud is not None
    assert openai is not None
    assert dotenv is not None
    assert pytest is not None


def test_p0_02_config_loads():
    """P0-02 [UNIT] — Config loads from .env: assert all API keys are non-empty strings."""
    import config
    
    assert isinstance(config.ANTHROPIC_API_KEY, str) and config.ANTHROPIC_API_KEY.strip()
    assert isinstance(config.MEM0_API_KEY, str) and config.MEM0_API_KEY.strip()
    assert isinstance(config.ZEP_API_KEY, str) and config.ZEP_API_KEY.strip()
    assert isinstance(config.OPENAI_API_KEY, str) and config.OPENAI_API_KEY.strip()
