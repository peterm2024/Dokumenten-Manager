"""
Paket der Tool-Plugins (siehe tools/base_tool.py und tool_manager.py).

Existiert vor allem, damit `tools` ein echtes Paket ist: Der ToolManager lädt die
Module zur Laufzeit über den Dateipfad, PyInstaller sieht diese Importe also nicht.
Erst als Paket lassen sich beim Release-Build alle Tool-Module zuverlässig
einsammeln (`--collect-submodules tools`, siehe build_exe.py und FALLSTRICKE #39) -
und damit auch die Projektmodule, die nur ein Tool importiert (z.B. dubletten.py).
"""
