# Vector Database Migration Guide

This guide describes how to migrate your vector data from the default ChromaDB to a different supported vector database (such as PGVector or Milvus) without needing to re-index your documents.

By migrating the vectors directly, you can switch databases quickly while preserving all your existing embeddings and metadata.

## Overview

The migration process involves:
1. Setting up the target vector database (e.g., PostgreSQL with pgvector, or Milvus).
2. Running the provided migration script to copy all collections and vectors from ChromaDB to the target database.
3. Updating your Open WebUI configuration to use the new vector database.

## Prerequisites

- Your current Open WebUI instance with ChromaDB data (typically located in the `DATA_DIR/vector_db` directory).
- The target vector database installed and running.
- Python dependencies for the target vector database installed in your Python environment.

## Supported Target Databases

The standalone migration script supports migrating from Chroma to:
- `pgvector`
- `milvus`

## Migration Steps

### 1. Run the Migration Script

A migration script is provided at `backend/open_webui/retrieval/vector/migrate.py`. This script is standalone and can be executed independently from the Open WebUI server.

For example, to migrate from Chroma to PGVector:

```bash
cd backend/

# Install the necessary dependencies if not already installed
pip install chromadb psycopg2-binary SQLAlchemy

# Run the migration script
python -m open_webui.retrieval.vector.migrate \
    --source-path /app/backend/data/vector_db \
    --target-db pgvector \
    --pgvector-url postgresql://user:password@localhost:5432/dbname
```

To migrate from Chroma to Milvus:

```bash
cd backend/

# Install the necessary dependencies if not already installed
pip install chromadb pymilvus

# Run the migration script
python -m open_webui.retrieval.vector.migrate \
    --source-path /app/backend/data/vector_db \
    --target-db milvus \
    --milvus-uri http://localhost:19530
```

The script will:
- Connect to your local ChromaDB directory.
- Connect to the target vector database.
- Iterate through all collections in ChromaDB.
- Extract all vectors, text, and metadata in batches.
- Upsert them into the target database.

### 2. Verify the Migration

After the migration completes, you can start the Open WebUI server to verify that the target vector database contains all the collections and item counts. The script includes detailed logs to confirm each migrated collection's count.

### 3. Update Configuration

Once the migration is finished, you need to update your Open WebUI environment variables so the application uses the new vector database.

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