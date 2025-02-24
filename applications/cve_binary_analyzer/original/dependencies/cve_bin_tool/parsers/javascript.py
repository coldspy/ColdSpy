# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: GPL-3.0-or-later
"""Python script containing all functionalities related to parsing of javascript's package-lock.json files."""

import json
import re

from cve_bin_tool.parsers import Parser


class JavascriptParser(Parser):
    """Parser for javascript's package-lock.json files"""

    def __init__(self, cve_db, logger):
        super().__init__(cve_db, logger)
        self.purl_pkg_type = "npm"

    def generate_purl(self, product, version, vendor, qualifier={}, subpath=None):
        """Generates PURL after normalizing all components."""
        product = re.sub(r"[^a-zA-Z0-9._-]", "", product).lower()
        version = re.sub(r"[^a-zA-Z0-9.+\-]", "", version)
        vendor = "UNKNOWN"  # Typically, the vendor is not explicitly defined for npm packages

        if not product or not version:
            return None

        purl = super().generate_purl(
            product,
            version,
            vendor,
            qualifier,
            subpath,
        )

        return purl

    def get_package_name(self, name):
        """Returns npm package name by decomposing string"""
        return name.split("/")[-1] if "/" in name else name

    def run_checker(self, filename):
        """Process package-lock.json file and extract product and dependency details"""
        self.filename = filename
        with open(self.filename) as fh:
            data = json.load(fh)
            if "name" in data and "version" in data:
                product = data["name"]
                version = data["version"]
                vendor = self.find_vendor(product, version)
            else:
                vendor = None
            if vendor is not None:
                yield from vendor

            # npm generates a similarly named .package-lock.js file (note the starting `.`)
            # that will trigger this
            product_version_mapping = list()
            if data.get("lockfileVersion"):
                # Valid package-lock.json file contains lockfileVersion
                if isinstance(data, dict) and data.get("lockfileVersion", 0) >= 2:
                    for package_name, package_dependency in data["packages"].items():
                        product = self.get_package_name(package_name)
                        version = package_dependency.get("version")
                        product_version_mapping.append((product, version))

                        for n, v in package_dependency.get("requires", {}).items():
                            product = self.get_package_name(n)
                            version = v
                            if v == "*":
                                continue
                            product_version_mapping.append((product, version))
                else:
                    # Now process dependencies
                    for i in data["dependencies"]:
                        # To handle @actions/<product>: lines, extract product name from line
                        product = self.get_package_name(i)
                        # Handle different formats. Either <product> : <version> or
                        # <product>: {
                        #       ...
                        #       "version" : <version>
                        #       ...
                        #       }
                        try:
                            version = data["dependencies"][i]["version"]
                        except Exception:
                            # Cater for case when version field not present
                            version = data["dependencies"][i]
                        product_version_mapping.append((product, version))

                        for n, v in data["dependencies"][i].get("requires", {}).items():
                            product = self.get_package_name(n)
                            version = v
                            if v == "*":
                                continue
                            product_version_mapping.append((product, version))

            for product, version in product_version_mapping:
                vendor = self.find_vendor(product, version)
                if vendor is not None:
                    yield from vendor
            self.logger.debug(f"Done scanning file: {self.filename}")
