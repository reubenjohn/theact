"""Tests for entry-point modules: __main__.py files.

Covers:
- src/theact/__main__.py (calls cli.main)
- src/theact/creator/__main__.py (calls asyncio.run(create_game()))
"""

import importlib
import sys
from unittest.mock import MagicMock, patch


class TestTheactMainEntry:
    def test_theact_main_calls_cli_main(self):
        """python -m theact should call theact.cli.main()."""
        mock_main = MagicMock()

        # Remove module from cache so reload/import is clean
        sys.modules.pop("theact.__main__", None)

        with patch("theact.cli.main", mock_main):
            importlib.import_module("theact.__main__")

        mock_main.assert_called_once()


class TestCreatorMainEntry:
    def test_creator_main_function(self):
        """theact.creator.__main__.main() should call asyncio.run(create_game())."""
        mock_create_game = MagicMock()
        mock_asyncio_run = MagicMock()

        with (
            patch("theact.creator.__main__.create_game", mock_create_game),
            patch("theact.creator.__main__.asyncio.run", mock_asyncio_run),
        ):
            from theact.creator.__main__ import main

            main()

        mock_asyncio_run.assert_called_once_with(mock_create_game())

    def test_creator_module_callable(self):
        """The creator __main__ module exposes a callable main() function."""
        from theact.creator.__main__ import main

        assert callable(main)
