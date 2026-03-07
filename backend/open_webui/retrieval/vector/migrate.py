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
from open_webui.retrieval.vector.main import VectorItem

def migrate_chroma_to_target(target_vector_db_name: str):
    """
    Migrates all vectors from ChromaDB to the specified target vector database.
    """
    try:
        source_client = ChromaClient()
    except Exception as e:
        log.error(f"Failed to initialize ChromaClient. Ensure Chroma is accessible. Error: {e}")
        return False

    try:
        # We temporarily set VECTOR_DB config here for Vector.get_vector to work correctly,
        # but the best way is using the `target_vector_db_name` directly to instantiate target client
        target_client = Vector.get_vector(target_vector_db_name)
    except Exception as e:
        log.error(f"Failed to initialize target Vector DB client ({target_vector_db_name}). Error: {e}")
        return False

    # Get all collections from ChromaDB
    try:
        chroma_collections = source_client.client.list_collections()
        if not chroma_collections:
            log.info("No collections found in ChromaDB. Nothing to migrate.")
            return True
        log.info(f"Found {len(chroma_collections)} collections in ChromaDB.")
    except Exception as e:
        log.error(f"Failed to list collections from ChromaDB: {e}")
        return False

    for collection in chroma_collections:
        collection_name = collection.name
        log.info(f"Processing collection: {collection_name}")

        try:
            # We must use the raw chromadb client to fetch embeddings, as VectorDBBase.get() does not return them
            chroma_collection = source_client.client.get_collection(name=collection_name)

            total_count = chroma_collection.count()
            if total_count == 0:
                log.info(f"Collection {collection_name} is empty. Skipping.")
                continue

            log.info(f"Collection {collection_name} has {total_count} items. Migrating in batches...")

            batch_size = 500
            offset = 0

            while offset < total_count:
                # Fetch items in the collection, including embeddings in batches
                result = chroma_collection.get(include=["documents", "metadatas", "embeddings"], limit=batch_size, offset=offset)

                ids = result.get("ids", [])
                documents = result.get("documents", [])
                metadatas = result.get("metadatas", [])
                embeddings = result.get("embeddings", [])

                if not ids:
                    break

                # Ensure all required data is present
                if not embeddings or len(embeddings) != len(ids):
                    log.warning(f"Missing embeddings for some items in collection {collection_name} at offset {offset}. Skipping this batch.")
                    offset += batch_size
                    continue

                # Construct VectorItem list
                items_to_insert = []
                for i in range(len(ids)):
                    # Handle possible None values in metadata
                    meta = metadatas[i] if metadatas and i < len(metadatas) and metadatas[i] is not None else {}
                    doc = documents[i] if documents and i < len(documents) and documents[i] is not None else ""

                    items_to_insert.append(
                        VectorItem(
                            id=ids[i],
                            text=doc,
                            vector=embeddings[i],
                            metadata=meta,
                        )
                    )

                # Insert into target database
                log.info(f"Inserting batch of {len(items_to_insert)} items into {target_vector_db_name} collection: {collection_name} (offset {offset}/{total_count})...")

                # Use upsert or insert based on what target DB supports. VectorDBBase defines both.
                # `upsert` is generally safer for migrations.
                target_client.upsert(collection_name=collection_name, items=items_to_insert)

                offset += batch_size

            log.info(f"Successfully migrated collection: {collection_name}")

        except Exception as e:
            log.error(f"Error migrating collection {collection_name}: {e}")
            continue

    log.info("Migration process completed.")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate vector data from ChromaDB to another vector database.")
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

    log.info(f"Starting migration from ChromaDB to {target_db}...")

    success = migrate_chroma_to_target(target_db.lower())

    if success:
        log.info("Migration finished successfully.")
        sys.exit(0)
    else:
        log.error("Migration failed.")
        sys.exit(1)
