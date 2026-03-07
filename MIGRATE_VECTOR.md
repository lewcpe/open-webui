# Vector Database Migration Guide

This guide describes how to migrate your vector data from the default ChromaDB to a different supported vector database (such as PGVector or Milvus) without needing to re-index your documents.

By migrating the vectors directly, you can switch databases quickly while preserving all your existing embeddings and metadata.

## Overview

The migration process involves:
1. Setting up the target vector database (e.g., PostgreSQL with pgvector, or Milvus).
2. Running the provided migration script to copy all collections and vectors from ChromaDB to the target database.
3. Running a verification script to ensure the migration was successful.
4. Updating your Open WebUI configuration to use the new vector database.

## Prerequisites

- Your current Open WebUI instance with ChromaDB data.
- The target vector database installed and running.
- Python dependencies for the target vector database installed in your Open WebUI environment.

## Supported Target Databases

The migration script supports migrating from Chroma to any database supported by Open WebUI, but is primarily tested with:
- `pgvector`
- `milvus`
- `qdrant`
- `pinecone`
- `opensearch`
- `elasticsearch`

## Migration Steps

### 1. Run the Migration Script

A migration script is provided at `backend/open_webui/retrieval/vector/migrate.py`. You need to run this script with the appropriate environment variables to connect to both your source (Chroma) and target databases.

For example, to migrate from Chroma to PGVector:

```bash
cd backend/
export VECTOR_DB=pgvector
export PGVECTOR_DB_URL=postgresql://user:password@localhost:5432/dbname
# The script will automatically read from your existing Chroma configuration (e.g. DATA_DIR/vector_db)
python -m open_webui.retrieval.vector.migrate
```

To migrate to Milvus:

```bash
cd backend/
export VECTOR_DB=milvus
export MILVUS_URI=http://localhost:19530
export MILVUS_DB=default
python -m open_webui.retrieval.vector.migrate
```

The script will:
- Connect to ChromaDB.
- Connect to the target vector database specified by `VECTOR_DB`.
- Iterate through all collections in ChromaDB.
- Extract all vectors, text, and metadata.
- Insert them into the target database.

### 2. Verify the Migration

After the migration completes, you can verify that all collections and document counts match using the verification script:

```bash
cd backend/
# Keep the same environment variables set as before
python -m open_webui.retrieval.vector.verify_migration
```

This script will report whether the collections and item counts match between ChromaDB and your target database.

### 3. Update Configuration

Once the migration is verified, you need to update your Open WebUI environment variables so the application uses the new vector database.

For PGVector, add or update the following in your `.env` file or environment:

```env
VECTOR_DB=pgvector
PGVECTOR_DB_URL=postgresql://user:password@localhost:5432/dbname
```

For Milvus, add or update:

```env
VECTOR_DB=milvus
MILVUS_URI=http://localhost:19530
MILVUS_DB=default
```

### 4. Restart Open WebUI

Restart your Open WebUI service for the changes to take effect. It will now connect to the new vector database.

## Notes

- **Dimension Mismatch**: Ensure your target database is configured to handle the exact vector dimension size that was used in ChromaDB (Open WebUI's default embedding model uses 384 dimensions).
- **Backups**: Always backup your `DATA_DIR` before starting a migration.
- **Rollback**: If the migration fails, you can safely continue using ChromaDB by removing the new environment variables and restarting the application. Your ChromaDB data is not modified or deleted during the migration.