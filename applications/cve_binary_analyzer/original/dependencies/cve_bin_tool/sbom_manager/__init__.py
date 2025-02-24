# Copyright (C) 2021 Anthony Harrison
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import re
from collections import defaultdict
from logging import Logger
from pathlib import Path

import defusedxml.ElementTree as ET
from lib4sbom.parser import SBOMParser
from packageurl import PackageURL

from cve_bin_tool.cvedb import CVEDB
from cve_bin_tool.input_engine import TriageData
from cve_bin_tool.log import LOGGER
from cve_bin_tool.util import ProductInfo, Remarks
from cve_bin_tool.validator import validate_cyclonedx, validate_spdx

from .swid_parser import SWIDParser


class SBOMManager:
    """
    Class: InputEngine

    This class is responsible for parsing various SBOM file formats (SPDX, CycloneDX, SWID) in the CVE Bin Tool.

    It provides methods for scanning SBOM files, parsing them, and retrieving vendor information.

    Attributes:
    - sbom_data (DefaultDict[ProductInfo, TriageData]): Dictionary containing parsed SBOM data.

    """

    SBOMtype = ["spdx", "cyclonedx", "swid"]

    sbom_data: defaultdict[ProductInfo, TriageData]

    def __init__(
        self,
        filename: str,
        sbom_type: str = "spdx",
        logger: Logger | None = None,
        validate: bool = True,
    ):
        self.filename = filename
        self.sbom_data = defaultdict(dict)
        self.type = "unknown"
        if sbom_type in self.SBOMtype:
            self.type = sbom_type
        self.logger = logger or LOGGER.getChild(self.__class__.__name__)
        self.validate = validate

        # Connect to the database
        self.cvedb = CVEDB(version_check=False)

    def common_prefix_split(self, product, version) -> list[ProductInfo]:
        """If the product have '-' in name try splitting it and try common prefixes.
        currently not being used, proposed to be used in future"""
        parsed_data: list[ProductInfo] = []
        found_common_prefix = False
        common_prefix = (
            "perl-",
            "golang-",
            "rubygem-",
            "python-",
            "py3-",
            "python3-",
            "python2-",
            "rust-",
            "nodejs-",
        )
        for prefix in common_prefix:
            if product.startswith(prefix):
                common_prefix_product = product[len(prefix) :]
                common_prefix_vendor = self.get_vendor(common_prefix_product)
                if len(common_prefix_vendor) > 1 or (
                    len(common_prefix_vendor) == 1
                    and common_prefix_vendor[0] != "UNKNOWN"
                ):
                    found_common_prefix = True
                    for vendor in common_prefix_vendor:
                        parsed_data.append(
                            ProductInfo(vendor, common_prefix_product, version)
                        )
                break
        if not found_common_prefix:
            # if vendor not found after removing common prefix try splitting it
            LOGGER.debug(
                f"No Vendor found for {product}, trying splitted product. "
                "Some results may be inaccurate due to vendor identification limitations."
            )
            splitted_product = product.split("-")
            for sp in splitted_product:
                temp = self.get_vendor(sp)
                if len(temp) > 1 or (len(temp) == 1 and temp[0] != "UNKNOWN"):
                    for vendor in temp:
                        # if vendor is not None:
                        parsed_data.append(ProductInfo(vendor, sp, version))
        return parsed_data

    def scan_file(self) -> dict[ProductInfo, TriageData]:
        """
        Parses the SBOM input file and returns the product information and
        corresponding triage data.

        Returns:
        - dict[ProductInfo, TriageData]: Parsed SBOM data.

        """
        self.logger.debug(
            f"Processing SBOM {self.filename} of type {self.type.upper()}"
        )
        modules = []
        try:
            if Path(self.filename).exists():
                if self.type == "swid":
                    swid = SWIDParser(self.validate)
                    modules = swid.parse(self.filename)
                else:
                    modules = self.parse_sbom()
        except (KeyError, FileNotFoundError, ET.ParseError) as e:
            LOGGER.debug(e, exc_info=True)

        LOGGER.debug(
            f"The number of modules identified in SBOM - {len(modules)}\n{modules}"
        )

        # Now process list of modules to create [vendor, product, version] tuples
        parsed_data: list[ProductInfo] = []
        for module_vendor, product, version in modules:
            # Using lower to normalize product names across databases
            product = product.lower()

            if module_vendor is None:
                # Now add vendor to create product record....
                vendor_set = self.get_vendor(product)
                for vendor in vendor_set:
                    # if vendor is not None:
                    parsed_data.append(ProductInfo(vendor, product, version))
            else:
                parsed_data.append(ProductInfo(module_vendor, product, version))

        for row in parsed_data:
            self.sbom_data[row]["default"] = {
                "remarks": Remarks.NewFound,
                "comments": "",
                "severity": "",
            }
            self.sbom_data[row]["paths"] = set(map(lambda x: x.strip(), "".split(",")))

        LOGGER.debug(f"SBOM Data {self.sbom_data}")
        return self.sbom_data

    def get_vendor(self, product: str) -> list:
        """
        Get the list of vendors for the product name.

        There may be more than one vendor for a given product name and all
        matches are returned.

        Args:
        - product (str): Product name.

        Returns:
        - list: The list of vendors for the product

        """
        vendorlist: list[str] = []
        vendor_package_pair = self.cvedb.get_vendor_product_pairs(product)
        if vendor_package_pair:
            # To handle multiple vendors, return all combinations of product/vendor mappings
            for v in vendor_package_pair:
                vendor = v["vendor"]
                vendorlist.append(vendor)
        else:
            vendorlist.append("UNKNOWN")
        return vendorlist

    def is_valid_string(self, string_type: str, ref_string: str) -> bool:
        """
        Validate the PURL, CPE string is the correct form.

        Args:
        - ref_string (str): PURL, CPE strings
        - string_type (str): ref_string type. (purl, cpe22 or cpe23)

        Returns:
        - bool: True if the ref_string parameter is a valid purl or cpe string, False otherwise.

        """
        string_pattern: str
        if string_type == "purl":
            string_pattern = r"^(?P<scheme>.+):(?P<type>.+)/(?P<namespace>.+)/(?P<name>.+)@(?P<version>.+)\??(?P<qualifiers>.*)#?(?P<subpath>.*)$"

        elif string_type == "cpe23":
            string_pattern = r"^cpe:2\.3:[aho\*\-](:(((\?*|\*?)([a-zA-Z0-9\-\._]|(\\[\\\*\?\!\"#\$%&'\(\)\+,\-\.\/:;<=>@\[\]\^`\{\|}~]))+(\?*|\*?))|[\*\-])){5}(:(([a-zA-Z]{2,3}(-([a-zA-Z]{2}|[0-9]{3}))?)|[\*\-]))(:(((\?*|\*?)([a-zA-Z0-9\-\._]|(\\[\\\*\?\!\"#\$%&'\(\)\+,\-\.\/:;<=>@\[\]\^`\{\|}~]))+(\?*|\*?))|[\*\-])){4}"

        elif string_type == "cpe22":
            string_pattern = r"^[c][pP][eE]:/[AHOaho]?(:[A-Za-z0-9\._\-~%]*){0,6}"

        return re.match(string_pattern, ref_string) is not None

    def parse_sbom(self) -> [(str, str, str)]:
        """
        Parse the SBOM to extract a list of modules, including vendor, product, and version information.

        The parsed product information can be retrieved from different components of the SBOM, with the following order of preference:
        1. CPE 2.3 Identifiers
        2. CPE 2.2 Identifiers
        3. Package URLs (purl)
        4. Name and Version from the SBOM (Vendor will be unspecified)

        Returns:
        - List[(str, str, str)]: A list of tuples, each containing vendor, product, and version information for a module.

        """

        # Set up SBOM parser
        sbom_parser = SBOMParser(sbom_type=self.type)
        # Load SBOM
        sbom_parser.parse_file(self.filename)
        modules = []
        if self.validate and self.filename.endswith(".xml"):
            # Only for XML files
            if sbom_parser.get_type() == "spdx":
                valid_xml = validate_spdx(self.filename)
            else:
                valid_xml = validate_cyclonedx(self.filename)
            if not valid_xml:
                return modules
        packages = [x for x in sbom_parser.get_sbom()["packages"].values()]
        LOGGER.debug(f"Parsed SBOM {self.filename} {packages}")
        for package in packages:
            vendor = None
            package_name = None
            version = None

            # If Package URL or CPE record found, use this data in preference to package data
            ext_ref = package.get("externalreference")
            if ext_ref is not None:
                vendor, package_name, version = self.parse_ext_ref(ext_ref=ext_ref)

            # For any data not found in CPE or the Package URL get from package data
            if not vendor:
                pass  # Because no vendor was detected then all vendors with this named package
                # will be included in the output.

            if not package_name:
                package_name = package["name"]

            if (not version) and (package.get("version") is not None):
                version = package["version"]
            else:
                LOGGER.debug(f"No version found in {package}")

            if version:
                # Found at least package and version, save the results
                modules.append([vendor, package_name, version])

        LOGGER.debug(f"Parsed SBOM {self.filename} {modules}")
        return modules

    def parse_ext_ref(self, ext_ref) -> (str | None, str | None, str | None):
        """
        Parse external references in an SBOM to extract module information.

        Two passes are made through the external references, giving priority to CPE types,
        which will always match the CVE database.

        Args:
        - ext_ref (List[List[str]]): List of lists representing external references.
          Each inner list contains [category, type, locator].

        Returns:
        - Optional[Tuple[str | None, str | None, str | None]]: A tuple containing the vendor, product, and version
          information extracted from the external references, or None if not found.

        """
        decoded = {}
        for ref in ext_ref:
            ref_type = ref[1]
            ref_string = ref[2]
            if ref_type == "cpe23Type" and self.is_valid_string("cpe23", ref_string):
                decoded["cpe23Type"] = self.decode_cpe23(ref_string)

            elif ref_type == "cpe22Type" and self.is_valid_string("cpe22", ref_string):
                decoded["cpe22Type"] = self.decode_cpe22(ref_string)

            elif ref_type == "purl" and self.is_valid_string("purl", ref_string):
                decoded["purl"] = self.decode_purl(ref_string)

        # No ext-ref matches, return none
        return decoded.get(
            "cpe23Type",
            decoded.get("cpe22Type", decoded.get("purl", (None, None, None))),
        )

    def decode_cpe22(self, cpe22) -> (str | None, str | None, str | None):
        """
        Decode a CPE 2.2 formatted string to extract vendor, product, and version information.

        Args:
        - cpe22 (str): CPE 2.2 formatted string.

        Returns:
        - Tuple[str | None, str | None, str | None]: A tuple containing the vendor, product, and version
          information extracted from the CPE 2.2 string, or None if the information is incomplete.

        """

        cpe = cpe22.split(":")
        vendor, product, version = cpe[2], cpe[3], cpe[4]
        # Return available data, convert empty fields to None
        return [vendor or None, product or None, version or None]

    def decode_cpe23(self, cpe23) -> (str | None, str | None, str | None):
        """
        Decode a CPE 2.3 formatted string to extract vendor, product, and version information.

        Args:
        - cpe23 (str): CPE 2.3 formatted string.

        Returns:
        - Tuple[str | None, str | None, str | None]: A tuple containing the vendor, product, and version
          information extracted from the CPE 2.3 string, or None if the information is incomplete.

        """

        cpe = cpe23.split(":")
        vendor, product, version = cpe[3], cpe[4], cpe[5]
        # Return available data, convert empty fields to None
        return [vendor or None, product or None, version or None]

    def decode_purl(self, purl) -> (str | None, str | None, str | None):
        """
        Decode a Package URL (purl) to extract version information.

        Args:
        - purl (str): Package URL (purl) string.

        Returns:
        - Tuple[str | None, str | None, str | None]: A tuple containing the vendor (which is always None for purl),
          product, and version information extracted from the purl string, or None if the purl is invalid or incomplete.

        """
        vendor = None  # Because the vendor and product identifiers in the purl don't always align
        product = None  # with the CVE DB, only the version is parsed.
        version = None
        # Process purl identifier
        purl_info = PackageURL.from_string(purl).to_dict()
        version = purl_info.get("version")

        return [vendor or None, product or None, version or None]


if __name__ == "__main__":
    import sys

    file = sys.argv[1]
    sbom = SBOMManager(file)
    sbom.scan_file()
