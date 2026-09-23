"""PyInstaller 的入口脚本（必须在包外面）。"""

import sys

from chat_jev.bundle import main

sys.exit(main())
