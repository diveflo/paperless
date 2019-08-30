import json
import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command

from documents.models import Document
from paperless.db import GnuPG

from ...mixins import Renderable

from documents.settings import (EXPORTER_FILE_NAME, 
                                EXPORTER_THUMBNAIL_NAME, 
                                EXPORTER_THUMBNAIL_WEBP_NAME)


class Command(Renderable, BaseCommand):

    help = """
        Using a manifest.json file, load the data from there, and import the
        documents it refers to.
    """.replace("    ", "")

    def add_arguments(self, parser):
        parser.add_argument("source")

    def __init__(self, *args, **kwargs):
        BaseCommand.__init__(self, *args, **kwargs)
        self.source = None
        self.manifest = None

    def handle(self, *args, **options):

        self.source = options["source"]

        if not os.path.exists(self.source):
            raise CommandError("That path doesn't exist")

        if not os.access(self.source, os.R_OK):
            raise CommandError("That path doesn't appear to be readable")

        manifest_path = os.path.join(self.source, "manifest.json")
        self._check_manifest_exists(manifest_path)

        with open(manifest_path) as f:
            self.manifest = json.load(f)

        self._check_manifest()

        # Fill up the database with whatever is in the manifest
        call_command("loaddata", manifest_path)

        self._import_files_from_manifest()

    @staticmethod
    def _check_manifest_exists(path):
        if not os.path.exists(path):
            raise CommandError(
                "That directory doesn't appear to contain a manifest.json "
                "file."
            )

    def _check_manifest(self):

        for record in self.manifest:

            if not record["model"] == "documents.document":
                continue

            if EXPORTER_FILE_NAME not in record:
                raise CommandError(
                    'The manifest file contains a record which does not '
                    'refer to an actual document file.'
                )

            doc_file = record[EXPORTER_FILE_NAME]
            if not os.path.exists(os.path.join(self.source, doc_file)):
                raise CommandError(
                    'The manifest file refers to "{}" which does not '
                    'appear to be in the source directory.'.format(doc_file)
                )

    def _import_files_from_manifest(self):

        for record in self.manifest:

            if not record["model"] == "documents.document":
                continue

            doc_file = record[EXPORTER_FILE_NAME]
            thumb_file = record[EXPORTER_THUMBNAIL_NAME]
            thumb_webp_file = record[EXPORTER_THUMBNAIL_WEBP_NAME]
            document = Document.objects.get(pk=record["pk"])

            document_path = os.path.join(self.source, doc_file)
            thumbnail_path = os.path.join(self.source, thumb_file)

            if thumb_webp_file:
                thumbnail_webp_path = os.path.join(self.source, 
                                                   thumb_webp_file)

            if settings.PASSPHRASE:
                _write_encrypted_to_document(document_path, 
                                             document.source_path)

                _write_encrypted_to_document(thumbnail_path,
                                             document.thumbnail_path)

                _write_encrypted_to_document(thumbnail_webp_path,
                                             document.thumbnail_webp_path)

            else:
                shutil.copy(document_path, document.source_path)
                shutil.copy(thumbnail_path, document.thumbnail_path)

                if os.path.exists(thumbnail_webp_path):
                    shutil.copy(thumbnail_webp_path, 
                                document.thumbnail_path_webp)

        # Reset the storage type to whatever we've used while importing

        storage_type = Document.STORAGE_TYPE_UNENCRYPTED
        if settings.PASSPHRASE:
            storage_type = Document.STORAGE_TYPE_GPG

        Document.objects.filter(
            pk__in=[r["pk"] for r in self.manifest]
        ).update(
            storage_type=storage_type
        )

    @staticmethod
    def _write_encrypted_to_document(file_to_encrypt, document_target):
        if not os.path.exists(file_to_encrypt):
            return

        with open(file_to_encrypt, "rb") as unencrypted:
            with open(document_target, "wb") as encrypted:
                print("Encrypting {} and saving it to {}".format(
                    file_to_encrypt, document_target))

                encrypted.write(GnuPG.encrypted(unencrypted))