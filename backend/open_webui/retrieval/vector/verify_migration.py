import argparse
import logging
import os
import sys
from typing import Optional

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Add backend directory to sys.path if running as a standalone script
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from open_webui.retrieval.vector.dbs.chroma import ChromaClient
from open_webui.retrieval.vector.factory import Vector

def verify_migration(target_vector_db_name: str):
    """
    Verifies that the target vector database contains the same collections and item counts as ChromaDB.
    """
    try:
        source_client = ChromaClient()
    except Exception as e:
        log.error(f"Failed to initialize ChromaClient. Error: {e}")
        return False

    try:
        target_client = Vector.get_vector(target_vector_db_name)
    except Exception as e:
        log.error(f"Failed to initialize target Vector DB client ({target_vector_db_name}). Error: {e}")
        return False

    try:
        chroma_collections = source_client.client.list_collections()
        if not chroma_collections:
            log.info("No collections found in ChromaDB. Verification complete (both should be empty).")
            return True
    except Exception as e:
        log.error(f"Failed to list collections from ChromaDB: {e}")
        return False

    all_matched = True

    for collection in chroma_collections:
        collection_name = collection.name

        # Check if target has the collection
        has_coll = target_client.has_collection(collection_name)
        if not has_coll:
            log.error(f"❌ Collection '{collection_name}' is missing in {target_vector_db_name}.")
            all_matched = False
            continue

        # Get count from Chroma
        try:
            chroma_collection = source_client.client.get_collection(name=collection_name)
            source_count = chroma_collection.count()
        except Exception as e:
            log.error(f"Failed to get count for collection '{collection_name}' in Chroma: {e}")
            all_matched = False
            continue

        # Get count from target
        try:
            # We use get() and count the ids
            # For databases that don't support count, we can do a generic approach or specific ones
            target_count = 0
            if hasattr(target_client, 'client') and hasattr(target_client.client, 'count'):
                target_count = target_client.client.count(collection_name=collection_name)
            elif target_vector_db_name == "milvus" and hasattr(target_client, 'client'):
                res = target_client.client.query(collection_name=f"{target_client.collection_prefix}_{collection_name}", filter="", output_fields=["count(*)"])
                target_count = res[0]["count(*)"] if res else 0
            elif target_vector_db_name == "pgvector" and hasattr(target_client, 'session'):
                from open_webui.retrieval.vector.dbs.pgvector import DocumentChunk
                target_count = target_client.session.query(DocumentChunk).filter(DocumentChunk.collection_name == collection_name).count()
            else:
                # Warning: Getting all items might be slow for very large collections if VectorDB lacks limit/offset for get
                # Some implementations support fetching without limit.
                log.info(f"Using generic get() to count collection {collection_name} in {target_vector_db_name}...")

                # Fetch only IDs to minimize memory payload
                # Note: This heavily depends on VectorDBBase.get() implementation for specific DB
                # Since VectorDBBase.get() might only return the first batch, we'll try to find if there is a way
                target_result = target_client.get(collection_name=collection_name)

                if target_result and target_result.ids:
                    # IDs usually a list of list
                    target_count = len(target_result.ids[0]) if isinstance(target_result.ids[0], list) else len(target_result.ids)
                else:
                    target_count = 0

        except Exception as e:
            log.error(f"Failed to get count for collection '{collection_name}' in {target_vector_db_name}: {e}")
            all_matched = False
            continue

        if source_count == target_count:
            log.info(f"✅ Collection '{collection_name}' matches: {source_count} items.")
        else:
            log.error(f"❌ Collection '{collection_name}' mismatch! Chroma: {source_count}, {target_vector_db_name}: {target_count}")
            all_matched = False

    if all_matched:
        log.info(f"Verification successful. All collections and item counts match between Chroma and {target_vector_db_name}.")
        return True
    else:
        log.error("Verification failed. There are discrepancies between Chroma and the target database.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify vector data migration from ChromaDB to another vector database.")
    parser.add_argument(
        "--target",
        type=str,
        required=False,
        help="The target vector database (e.g., pgvector, milvus). Defaults to VECTOR_DB env variable."
    )

    args = parser.parse_args()

    # Determine target DB from args or environment variable
    target_db = args.target or os.environ.get("VECTOR_DB")

    if not target_db:
        log.error("Target vector database must be specified via --target or VECTOR_DB environment variable.")
        sys.exit(1)

    if target_db.lower() == "chroma":
        log.error("Target database cannot be 'chroma' (migration is FROM chroma).")
        sys.exit(1)

    log.info(f"Starting verification: comparing ChromaDB to {target_db}...")

    success = verify_migration(target_db.lower())

    if success:
        sys.exit(0)
    else:
        sys.exit(1)
