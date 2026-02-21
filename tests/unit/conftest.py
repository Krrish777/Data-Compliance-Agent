"""
Pytest configuration and shared fixtures for unit tests
"""
import sys
from pathlib import Path

# Add project root directory to Python path (for "from src.X import Y" style imports)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests requiring external resources"
    )
