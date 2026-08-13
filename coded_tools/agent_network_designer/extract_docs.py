# Copyright © 2025-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

import logging
import os
from typing import Any
from typing import Dict
from typing import Union

from leaf_common.serialization.util.text_file_reader import TextFileReader
from neuro_san.interfaces.coded_tool import CodedTool
from pypdf import PdfReader
from pypdf.errors import PyPdfError

logger = logging.getLogger(__name__)


class ExtractDocs(CodedTool):
    """
    CodedTool implementation extracts the curated knowledge documents for a domain.
    Returns a dictionary mapping each document file name to its text.

    Documents are returned WHOLE and verbatim - never chunked or summarized - because the
    operating standards they carry have to reach the designed agents word for word, with
    their ids intact.
    """

    KNOWDOCS = "coded_tools/agent_network_designer/knowdocs"

    def __init__(self):
        self.default_path = None

        # Curated knowledge domains. To add a domain: drop a folder of .md files under
        # knowdocs/ and add one line here.
        self.docs_path = {
            "oracle_database_patching": f"{self.KNOWDOCS}/oracle_database_patching",
            "kubernetes_cluster_upgrade": f"{self.KNOWDOCS}/kubernetes_cluster_upgrade",
            "clinical_trial_database_lock": f"{self.KNOWDOCS}/clinical_trial_database_lock",
        }

    def invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        :param args: An argument dictionary with the following keys:
            - "directory" (str): The directory containing the documents.

        :param sly_data: A dictionary whose keys are defined by the agent hierarchy,
            but whose values are meant to be kept out of the chat stream.

            This dictionary is largely to be treated as read-only.
            It is possible to add key/value pairs to this dict that do not
            yet exist as a bulletin board, as long as the responsibility
            for which coded_tool publishes new entries is well understood
            by the agent chain implementation and the coded_tool implementation
            adding the data is not invoke()-ed more than once.

            Keys expected for this implementation are:
                None

        :return:
            If successful:
                A dictionary containing extracted text with the keys:
                - "file_name": The path and name of the processed document file.
                - "text": The extracted text from the document.
            Otherwise:
                A text string error message in the format:
                "Error: <error message>"
        """
        app_name: str = args.get("app_name", None)
        logger.debug("############### Curated knowledge reader ###############")
        logger.debug("Domain: %s", app_name)
        available = ", ".join(sorted(self.docs_path.keys()))
        if app_name is None:
            return f"Error: No domain provided. Available curated domains: {available}"

        # Unlike the airline example, an unknown domain is an explicit miss rather than a silent
        # fallback: the designer has to KNOW it missed so it can say so and fall back to general
        # knowledge, instead of interviewing the user from the wrong domain's standards.
        directory = self.docs_path.get(app_name, None)
        if directory is None:
            return f'Error: No curated knowledge for domain "{app_name}". Available curated domains: {available}'

        if not isinstance(directory, (str, bytes, os.PathLike)):
            raise TypeError(f"Expected str, bytes, or os.PathLike object, got {type(directory).__name__} instead")

        docs = {}
        for root, _, files in os.walk(directory):
            for file in files:
                # Build the full path to the file
                file_path = os.path.join(root, file)

                if file.lower().endswith(".pdf"):
                    # Extract PDF content
                    content = self.extract_pdf_content(file_path)
                    # Store in the dictionary using a relative path (relative to the main directory)
                    rel_path = os.path.relpath(file_path, directory)
                    docs[rel_path] = content
                elif file.lower().endswith((".txt", ".md")):
                    # Extract text file content
                    content = self.extract_txt_content(file_path)
                    # Store in the dictionary using a relative path
                    rel_path = os.path.relpath(file_path, directory)
                    docs[rel_path] = content
        logger.debug("############### Documents extraction done ###############")
        if not docs:
            logger.debug("No knowledge documents found in the directory.")
            return f'ERROR: No knowledge documents found for domain "{app_name}" under {directory}.'
        return {"files": docs}

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Union[Dict[str, Any], str]:
        """
        Delegates to the synchronous invoke method for now.
        """
        return self.invoke(args, sly_data)

    @staticmethod
    def extract_pdf_content(pdf_path: str) -> str:
        """
        Extract text from a PDF file using pypdf, while attempting to preserve
        pagination (by inserting page headers).

        :param pdf_path: Full path to the PDF file.
        :return: Extracted text from the PDF.
        """
        text_output = []
        try:
            reader = PdfReader(pdf_path)
            for page_num, page in enumerate(reader.pages):
                # Add a page header for pagination
                text_output.append(f"\n\n--- Page {page_num + 1} ---\n\n")
                # Extract text from the page (fall back to empty string if None)
                page_text = page.extract_text() or ""
                text_output.append(page_text)
        except (PyPdfError, OSError) as e:
            error = f"Error reading PDF {pdf_path}: {e}"
            logger.error(error)
            return f"ERROR: {error}"

        return "".join(text_output)

    @staticmethod
    def extract_txt_content(txt_path: str) -> str:
        """
        Extract text from a plain text file.

        :param txt_path: Full path to the TXT file.
        :return: Content of the text file.
        """
        try:
            return TextFileReader.read_text_file(txt_path)
        except OSError as e:
            error = f"Error reading TXT {txt_path}: {e}"
            logger.error(error)
            return f"ERROR: {error}"
