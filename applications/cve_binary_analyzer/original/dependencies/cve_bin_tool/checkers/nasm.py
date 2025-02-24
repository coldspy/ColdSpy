# Copyright (C) 2022 Orange
# SPDX-License-Identifier: GPL-3.0-or-later


"""
CVE checker for nasm:

https://www.cvedetails.com/product/14272/Nasm-Netwide-Assembler.html?vendor_id=2638

"""
from __future__ import annotations

from cve_bin_tool.checkers import Checker


class NasmChecker(Checker):
    CONTAINS_PATTERNS: list[str] = []
    FILENAME_PATTERNS: list[str] = []
    VERSION_PATTERNS = [r"NASM ([0-9]+\.[0-9]+\.[0-9]+)"]
    VENDOR_PRODUCT = [("nasm", "netwide_assembler")]
