# 📄 PDF Interleave --- Web Version Specifications (RAM-Only)

**Date:** 2026-02-26

------------------------------------------------------------------------

## 1. Objective

Transform the existing CLI-based PDF interleave tool into a web
application that:

-   Accepts **maximum 2 PDF files**
-   Can extract screenshots at precise timestamps from one uploaded video
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
POST /video → Extract screenshots\
GET /download/{token} → Download file

### Optional API

POST /api/merge\
POST /api/video\
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
ONE_SHOT_DOWNLOAD=true\
MAX_VIDEO_DURATION_SECONDS=600\
MAX_VIDEO_FRAMES=120\
MAX_VIDEO_OUTPUT_MB=100\
VIDEO_PROCESS_TIMEOUT_SECONDS=300

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
-   No persistent disk IO; video processing uses short-lived temporary files
-   Memory usage bounded by configuration
-   StreamingResponse for downloads

------------------------------------------------------------------------

## 10. Video screenshots

The web adapter exposes `POST /video` for the HTML interface and
`POST /api/video` for API clients. The multipart fields are:

-   `video`: one video file, subject to the regular per-file upload limit
-   `timestamps`: optional list of precise seconds, separated by commas,
    semicolons or whitespace (for example `3, 8.5, 42`)
-   `interval_seconds`: positive fallback interval between screenshots when
    `timestamps` is empty (default: 1)
-   `max_frames`: optional requested maximum, capped by `MAX_VIDEO_FRAMES`

The response is a ZIP archive of JPEG files named `screenshots/frame-XXXXXX.jpg`.
The archive is kept in the existing RAM token store and follows the same TTL,
one-shot download and rate-limit rules as PDF results. Since video codecs need
seekable input, the uploaded video and intermediate JPEG files are written to
an OS temporary directory during processing and removed immediately afterward.

Video processing requires `ffmpeg` and `ffprobe` to be available on the server.
`MAX_VIDEO_DURATION_SECONDS`, `MAX_VIDEO_FRAMES`, `MAX_VIDEO_OUTPUT_MB` and
`VIDEO_PROCESS_TIMEOUT_SECONDS` bound resource usage.

------------------------------------------------------------------------

## 11. Deployment

-   Container-friendly
-   No volume required
-   Ensure temporary files are cleaned up after every video job
-   Recommended: memory limits set at container level

------------------------------------------------------------------------

End of Web Specifications
