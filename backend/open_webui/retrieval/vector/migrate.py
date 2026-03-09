import argparse
import logging
import json
import sys

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def process_metadata(metadata):
    KEYS_TO_EXCLUDE = ["content", "pages", "tables", "paragraphs", "sections", "figures"]
    result = {}
    if not metadata:
        return result
    for key, value in metadata.items():
        if key in KEYS_TO_EXCLUDE:
            continue
        if isinstance(value, (list, dict)):
            result[key] = str(value)
        else:
            result[key] = value
    return result

def get_chroma_client(path):
    try:
        import chromadb
    except ImportError:
        log.error("chromadb is not installed. Please install it with 'pip install chromadb'")
        return None
    return chromadb.PersistentClient(path=path)

def migrate_to_milvus(chroma_client, milvus_uri, milvus_token, milvus_db, prefix="open_webui"):
    try:
        from pymilvus import MilvusClient, DataType
    except ImportError:
        log.error("pymilvus is not installed. Please install it with 'pip install pymilvus'")
        return False

    log.info(f"Connecting to Milvus at {milvus_uri}...")
    target_client = MilvusClient(uri=milvus_uri, token=milvus_token, db_name=milvus_db)

    collections = chroma_client.list_collections()
    for collection in collections:
        collection_name = collection.name
        target_collection_name = f"{prefix}_{collection_name}".replace("-", "_")

        log.info(f"Processing Chroma collection: {collection_name}")
        total_count = collection.count()
        if total_count == 0:
            log.info(f"Collection {collection_name} is empty. Skipping.")
            continue

        first_item = collection.get(include=["embeddings"], limit=1)
        if not first_item.get("embeddings"):
            continue
        dim = len(first_item["embeddings"][0])

        if not target_client.has_collection(target_collection_name):
            log.info(f"Creating Milvus collection {target_collection_name} with dim {dim}")
            schema = target_client.create_schema(auto_id=False, enable_dynamic_field=True)
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=65535)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
            schema.add_field(field_name="data", datatype=DataType.JSON)
            schema.add_field(field_name="metadata", datatype=DataType.JSON)

            index_params = target_client.prepare_index_params()
            index_params.add_index(field_name="vector", metric_type="COSINE", index_type="AUTOINDEX")

            target_client.create_collection(
                collection_name=target_collection_name,
                schema=schema,
                index_params=index_params
            )

        batch_size = 500
        offset = 0
        while offset < total_count:
            result = collection.get(include=["documents", "metadatas", "embeddings"], limit=batch_size, offset=offset)
            ids = result.get("ids", [])
            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            embeddings = result.get("embeddings", [])

            if not ids:
                break

            data_to_insert = []
            for i in range(len(ids)):
                data_to_insert.append({
                    "id": ids[i],
                    "vector": embeddings[i],
                    "data": {"text": documents[i] if documents[i] else ""},
                    "metadata": process_metadata(metadatas[i] if metadatas and i < len(metadatas) and metadatas[i] else {})
                })

            log.info(f"Inserting batch of {len(data_to_insert)} items into {target_collection_name} (offset {offset}/{total_count})...")
            target_client.upsert(collection_name=target_collection_name, data=data_to_insert)
            offset += batch_size

    return True

def migrate_to_pgvector(chroma_client, pgvector_url):
    try:
        from sqlalchemy import create_engine, text, MetaData, Table, inspect
        from sqlalchemy.orm import sessionmaker
    except ImportError:
        log.error("sqlalchemy or psycopg2 is not installed.")
        return False

    log.info(f"Connecting to PGVector at {pgvector_url}...")
    engine = create_engine(pgvector_url)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Ensure pgvector extension
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
    session.commit()

    inspector = inspect(engine)
    if not inspector.has_table("document_chunk"):
        log.error("Table 'document_chunk' does not exist in the target PG database.")
        log.error("Please start Open WebUI at least once with PGVECTOR_DB_URL to initialize the schema.")
        return False

    collections = chroma_client.list_collections()
    for collection in collections:
        collection_name = collection.name
        log.info(f"Processing Chroma collection: {collection_name}")
        total_count = collection.count()
        if total_count == 0:
            continue

        batch_size = 500
        offset = 0
        while offset < total_count:
            result = collection.get(include=["documents", "metadatas", "embeddings"], limit=batch_size, offset=offset)
            ids = result.get("ids", [])
            documents = result.get("documents", [])
            metadatas = result.get("metadatas", [])
            embeddings = result.get("embeddings", [])

            if not ids:
                break

            items = []
            for i in range(len(ids)):
                doc_text = documents[i] if documents and i < len(documents) and documents[i] else ""
                meta = process_metadata(metadatas[i] if metadatas and i < len(metadatas) and metadatas[i] else {})
                items.append({
                    "id": ids[i],
                    "vector": embeddings[i],
                    "collection_name": collection_name,
                    "text": doc_text,
                    "vmetadata": meta
                })

            log.info(f"Inserting batch of {len(items)} items into pgvector collection '{collection_name}' (offset {offset}/{total_count})...")
            for item in items:
                session.execute(
                    text("""
                        INSERT INTO document_chunk (id, vector, collection_name, text, vmetadata)
                        VALUES (:id, :vector, :collection_name, :text, :vmetadata)
                        ON CONFLICT (id) DO UPDATE SET
                            vector = EXCLUDED.vector,
                            collection_name = EXCLUDED.collection_name,
                            text = EXCLUDED.text,
                            vmetadata = EXCLUDED.vmetadata
                    """),
                    {
                        "id": item["id"],
                        "vector": str(item["vector"]),
                        "collection_name": item["collection_name"],
                        "text": item["text"],
                        "vmetadata": json.dumps(item["vmetadata"])
                    }
                )
            session.commit()
            offset += batch_size

    session.close()
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone migration script from Chroma to another VectorDB.")
    parser.add_argument("--source-path", type=str, required=True, help="Path to the ChromaDB data directory")
    parser.add_argument("--target-db", type=str, required=True, choices=["milvus", "pgvector"], help="Target vector DB")
    parser.add_argument("--milvus-uri", type=str, help="Milvus URI (e.g., http://localhost:19530)")
    parser.add_argument("--milvus-token", type=str, help="Milvus token", default="")
    parser.add_argument("--milvus-db", type=str, help="Milvus DB name", default="default")
    parser.add_argument("--pgvector-url", type=str, help="PGVector connection URL")

    args = parser.parse_args()

    chroma_client = get_chroma_client(args.source_path)
    if not chroma_client:
        sys.exit(1)

    if args.target_db == "milvus":
        if not args.milvus_uri:
            log.error("--milvus-uri is required for Milvus.")
            sys.exit(1)
        success = migrate_to_milvus(chroma_client, args.milvus_uri, args.milvus_token, args.milvus_db)
    elif args.target_db == "pgvector":
        if not args.pgvector_url:
            log.error("--pgvector-url is required for PGVector.")
            sys.exit(1)
        success = migrate_to_pgvector(chroma_client, args.pgvector_url)

    if success:
        log.info("Migration finished successfully.")
    else:
        log.error("Migration failed.")
        sys.exit(1)
