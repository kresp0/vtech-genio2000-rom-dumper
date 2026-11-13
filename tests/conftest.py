# SPDX-License-Identifier: 0BSD
# Copyright (C) 2026 Santiago Crespo
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'tools'))
sys.dont_write_bytecode = True
