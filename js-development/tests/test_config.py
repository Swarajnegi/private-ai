import pytest
from unittest.mock import patch

from jarvis_core.config import validate_paths

def test_validate_paths_root_not_found():
    with patch("jarvis_core.config.JARVIS_ROOT") as mock_jarvis_root:
        mock_jarvis_root.exists.return_value = False

        with pytest.raises(FileNotFoundError, match=r"\[Config\] JARVIS_ROOT not found"):
            validate_paths()

def test_validate_paths_success():
    with patch("jarvis_core.config.JARVIS_ROOT") as mock_jarvis_root, \
         patch("jarvis_core.config.DB_ROOT") as mock_db_root, \
         patch("jarvis_core.config.BACKUP_ROOT") as mock_backup_root:

        mock_jarvis_root.exists.return_value = True

        validate_paths()

        mock_db_root.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_backup_root.mkdir.assert_called_once_with(parents=True, exist_ok=True)
