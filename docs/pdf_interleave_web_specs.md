# 📄 PDF Interleave --- Web Version Specifications (RAM-Only)

**Date:** 2026-02-26

------------------------------------------------------------------------

## 1. Objective

Transform the existing CLI-based PDF interleave tool into a web
application that:

-   Accepts **maximum 2 PDF files**
-   Limits each file to **15 MB**
-   Generates the output entirely in **RAM**
-   Allows download for a **limited time (default: 5 minutes)**
-   Does **NOT persist any PDF on disk**
-   Keeps the CLI fully functional and unchanged

------------------------------------------------------------------------

## 2. Functional Requirements

### Upload Constraints

-   Maximum files: 2
-   Max file size: 15 MB each
-   MIME type: application/pdf
-   Reject encrypted PDFs (unless supported later)

### Output

-   Output generated fully in memory (BytesIO)
-   Estimated size: \~30 MB max
-   Stored in memory with TTL

------------------------------------------------------------------------

## 3. Memory-Only Storage Design

### RAM Store Structure

dict[token](#token) = { "bytes": pdf_bytes, "created_at": timestamp,
"expires_at": timestamp, "filename": str, "size": int }

### Token

-   Generated using secrets.token_urlsafe(32)
-   Opaque token
-   No metadata exposed

### TTL

-   Default: 300 seconds
-   Configurable via environment variable
-   Automatic purge:
    -   Background cleanup task
    -   Or lazy cleanup on access

------------------------------------------------------------------------

## 4. Web Architecture

### Core Separation

-   core/ → business logic (unchanged)
-   cli/ → CLI interface (unchanged)
-   web/ → FastAPI adapter

### Recommended Stack

-   FastAPI
-   Uvicorn (dev)
-   Gunicorn + Uvicorn workers (prod)
-   Jinja2 templates (minimal UI)

------------------------------------------------------------------------

## 5. Endpoints

### UI

GET / → Upload form\
POST /merge → Process merge\
GET /download/{token} → Download file

### Optional API

POST /api/merge\
GET /api/status/{token}\
DELETE /api/token/{token}

------------------------------------------------------------------------

## 6. Security & Limits

Environment Variables:

MAX_FILE_MB=15\
DOWNLOAD_TTL_SECONDS=300\
MAX_ACTIVE_JOBS=20\
RATE_LIMIT_MERGE_PER_MIN=10\
RATE_LIMIT_DOWNLOAD_PER_MIN=30\
ONE_SHOT_DOWNLOAD=true

### Headers

Cache-Control: no-store\
Pragma: no-cache

------------------------------------------------------------------------

## 7. Rate Limiting

-   Per IP limits
-   Merge requests per minute
-   Download requests per minute
-   Maximum concurrent active jobs

------------------------------------------------------------------------

## 8. Error Handling

User-facing errors:

-   File too large
-   Invalid PDF
-   Encrypted PDF not supported
-   Invalid page order
-   Link expired

------------------------------------------------------------------------

## 9. Performance

-   Suitable for moderate concurrency
-   No disk IO
-   Memory usage bounded by configuration
-   StreamingResponse for downloads

------------------------------------------------------------------------

## 10. Deployment

-   Container-friendly
-   No volume required
-   Ensure no temp files are created
-   Recommended: memory limits set at container level

------------------------------------------------------------------------

End of Web Specifications
