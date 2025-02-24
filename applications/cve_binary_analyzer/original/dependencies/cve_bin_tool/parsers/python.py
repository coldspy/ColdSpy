# Copyright (C) 2024 Intel Corporation
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re
import subprocess
from re import MULTILINE, compile, search

from packaging.version import parse as parse_version

from cve_bin_tool.parsers import Parser
from cve_bin_tool.strings import parse_strings
from cve_bin_tool.util import ProductInfo, ScanInfo


class PythonRequirementsParser(Parser):
    """
    Parser for Python requirements files.
    This parser is designed to parse Python requirements files (usually named
    requirements.txt) and generate PURLs (Package URLs) for the listed packages.
    """

    def __init__(self, cve_db, logger):
        """Initialize the python requirements file parser."""
        self.purl_pkg_type = "pypi"
        super().__init__(cve_db, logger)

    def generate_purl(self, product, version, vendor, qualifier={}, subpath=None):
        """Generates PURL after normalizing all components."""
        product = re.sub(r"[^a-zA-Z0-9._-]", "", product).lower()
        version = re.sub(r"[^a-zA-Z0-9.+-]", "", version)
        vendor = "UNKNOWN"

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

    def run_checker(self, filename):
        """
        Parse the requirements file and yield PURLs for the listed packages.
        Args:
            filename (str): The path to the requirements file.
        Yields:
            str: PURLs for the packages listed in the file.
        """
        self.filename = filename
        try:
            output = subprocess.check_output(
                [
                    "pip3",
                    "install",
                    "-r",
                    self.filename,
                    "--dry-run",
                    "--ignore-installed",
                    "--report",
                    "-",
                    "--quiet",
                ],
                stderr=subprocess.STDOUT,
            )
        except subprocess.CalledProcessError as e:
            self.logger.error(e.output)
            pip_version = str(subprocess.check_output(["pip3", "--version"]))
            # Output will look like:
            # pip 20.0.2 from /usr/lib/python3/dist-packages/pip (python 3.8)
            pip_version = pip_version.split(" ")[1]
            if parse_version(pip_version) < parse_version("22.2"):
                self.logger.error(
                    f"{filename} not scanned: pip --dry-run was unable to get package versions."
                )
                self.logger.error(
                    "pip version >= 22.2 is required to scan Python requirements files."
                )
        else:
            output = subprocess.check_output(
                [
                    "pip3",
                    "install",
                    "-r",
                    self.filename,
                    "--dry-run",
                    "--ignore-installed",
                    "--report",
                    "-",
                    "--quiet",
                ],
            )
            lines = json.loads(output)
            for line in lines["install"]:
                product = line["metadata"]["name"]
                version = line["metadata"]["version"]
                vendor = self.find_vendor(product, version)
                if vendor is not None:
                    yield from vendor
            self.logger.debug(f"Done scanning file: {self.filename}")


class PythonParser(Parser):
    """
    Parser for Python package metadata files.
    This parser is designed to parse Python package metadata files (usually named
    PKG-INFO or METADATA) and generate PURLs (Package URLs) for the package.
    """

    def __init__(self, cve_db, logger):
        """Initialize the python package metadata parser."""
        self.purl_pkg_type = "pypi"
        super().__init__(cve_db, logger)

    def generate_purl(self, product, version, vendor, qualifier={}, subpath=None):
        """Generates PURL after normalizing all components."""
        product = re.sub(r"[^a-zA-Z0-9._-]", "", product).lower()
        version = re.sub(r"[^a-zA-Z0-9.+-]", "", version)
        vendor = "UNKNOWN"

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

    def run_checker(self, filename):
        """
        This generator runs only for python packages.
        There are no actual checkers.
        The ProductInfo is computed without the help of any checkers from PKG-INFO or METADATA.
        """
        self.filename = filename
        lines = parse_strings(self.filename)
        lines = "\n".join(lines.splitlines()[:3])
        try:
            product = search(compile(r"^Name: (.+)$", MULTILINE), lines).group(1)
            version = search(compile(r"^Version: (.+)$", MULTILINE), lines).group(1)
            vendor_package_pair = self.cve_db.get_vendor_product_pairs(product)
            if vendor_package_pair != []:
                for pair in vendor_package_pair:
                    vendor = pair["vendor"]
                    file_path = self.filename
                    self.logger.debug(f"{file_path} is {vendor}.{product} {version}")
                    yield ScanInfo(ProductInfo(vendor, product, version), file_path)

        # There are packages with a METADATA file in them containing different data from what the tool expects
        except AttributeError:
            self.logger.debug(f"{filename} is an invalid METADATA/PKG-INFO")
        self.logger.debug(f"Done scanning file: {filename}")
