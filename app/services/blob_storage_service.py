"""Build Sequence #TBD -- Phase 6, evidence ingestion. Azure Blob Storage
helpers for project evidence files. Single container ('evidence-files'),
with blobs organized under a per-project prefix (project_id/filename) so
files from different projects never collide and can be listed/cleaned up
per-project easily.

Never stores files with public access -- the container itself is private
(confirmed set at creation); all reads by CompliFyre's own backend go
through this module's authenticated client, never a public URL.
"""
import os
import uuid
from azure.storage.blob import BlobServiceClient

CONTAINER_NAME = "evidence-files"


def _get_blob_service_client():
    conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not set in the environment")
    return BlobServiceClient.from_connection_string(conn_str)


def upload_evidence_file(project_id: int, original_filename: str, file_bytes: bytes, content_type: str = None) -> dict:
    """Uploads a single evidence file's bytes to blob storage under a
    project-scoped, collision-safe path. Returns a dict with the storage
    path (what gets saved to ProjectEvidenceFile.storage_path) and the
    actual size uploaded -- never returns a public URL, since the container
    is private and reads must go through this module's own authenticated
    client, not a direct link.

    The stored blob name is deliberately NOT just the original filename --
    two different uploads for the same project could otherwise collide if a
    client uploads two files with the same name (e.g. two different
    "Policy.pdf" files at different times). A UUID prefix keeps every upload
    unique regardless of what the client named their file; original_filename
    is preserved separately in the database for display purposes.
    """
    client = _get_blob_service_client()
    container_client = client.get_container_client(CONTAINER_NAME)

    safe_name = original_filename.replace("/", "_").replace("\\", "_")
    blob_name = f"{project_id}/{uuid.uuid4().hex}_{safe_name}"

    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(
        file_bytes,
        overwrite=False,  # the UUID prefix should make collisions impossible; overwrite=False
        # is a deliberate safeguard, not a real expected case -- if this ever fires, something
        # is wrong upstream (e.g. a retry re-generating the exact same UUID, astronomically
        # unlikely) and should fail loudly rather than silently overwrite a different file.
        content_settings=_build_content_settings(content_type) if content_type else None,
    )

    return {
        "storage_path": blob_name,
        "size_bytes": len(file_bytes),
    }


def download_evidence_file(storage_path: str) -> bytes:
    """Downloads a single evidence file's bytes from blob storage, given the
    storage_path saved on its ProjectEvidenceFile record. Used by EVE's
    mapping step to read file content -- always goes through this
    authenticated client, never a public URL (the container has none).
    """
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=CONTAINER_NAME, blob=storage_path)
    return blob_client.download_blob().readall()


def delete_evidence_file(storage_path: str) -> None:
    """Deletes a single evidence file from blob storage. Used when a
    ProjectEvidenceFile record is removed, so storage doesn't silently
    accumulate orphaned blobs no database record points to anymore.
    """
    client = _get_blob_service_client()
    blob_client = client.get_blob_client(container=CONTAINER_NAME, blob=storage_path)
    blob_client.delete_blob()


def _build_content_settings(content_type: str):
    from azure.storage.blob import ContentSettings
    return ContentSettings(content_type=content_type)
