# 📄 PDF Interleave

A Python-based PDF interleaving tool supporting:

-   CLI usage
-   RAM-only Web version
-   Configurable page ordering
-   Sequential concatenation of N PDFs
-   Image-to-PDF conversion with optional EXIF auto-orientation
-   Secure ephemeral downloads

------------------------------------------------------------------------

## 🚀 Features

### CLI Mode

Merge two PDFs by alternating pages:

-   Ascending or descending order
-   Custom page ranges
-   List or slice selection
-   Append / truncate / error policies

Example:

``` bash
pdf_interleave merge   -a recto.pdf --order-a asc   -b verso.pdf --order-b desc   -o merged.pdf
```

Concatenate PDFs in the exact order provided:

``` bash
pdf_interleave concat cover.pdf chapter-1.pdf chapter-2.pdf appendix.pdf -o book.pdf
```

Convert images to one PDF, one image per page:

``` bash
pdf_interleave images page-1.jpg page-2.png page-3.webp -o images.pdf --auto-orient
```

------------------------------------------------------------------------

### 🌐 Web Mode (RAM-Only)

-   Interleave 2 PDFs
-   Concatenate up to 20 PDFs by default
-   Convert images to a PDF with reorder/remove controls
-   Extract screenshots from an uploaded video at precise seconds or a configurable interval
-   15 MB per file
-   Output generated fully in memory
-   Temporary download link (default: 5 minutes)
-   Uploaded videos and extracted frames use temporary files that are deleted after processing

Run server:

``` bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

------------------------------------------------------------------------

## 🏗 Project Structure

- `core/merge.py`, `core/pagerange.py`, `core/validate.py`, `core/video_screenshots.py`: core logic
- `cli/app.py`, `main.py`: CLI entrypoint
- `web/app.py`, `web/store.py`, `web/rate_limit.py`, `web/templates/`: FastAPI web adapter

------------------------------------------------------------------------

## ⚙ Configuration

Environment Variables:

MAX_FILE_MB=15\
MAX_UPLOAD_FILES=20\
DOWNLOAD_TTL_SECONDS=300\
MAX_ACTIVE_JOBS=20\
RATE_LIMIT_MERGE_PER_MIN=10\
RATE_LIMIT_DOWNLOAD_PER_MIN=30\
ONE_SHOT_DOWNLOAD=true\
MAX_VIDEO_DURATION_SECONDS=600\
MAX_VIDEO_FRAMES=120\
MAX_VIDEO_OUTPUT_MB=100\
VIDEO_FRAME_INTERVAL_SECONDS=1\
VIDEO_PROCESS_TIMEOUT_SECONDS=300\
FFMPEG_BINARY=ffmpeg\
FFPROBE_BINARY=ffprobe

The video screenshot feature requires the `ffmpeg` and `ffprobe` executables
to be installed on the server. The web interface exposes a **Video screenshots**
operation: enter precise seconds such as `3, 8.5, 42` to process several
captures in one batch, or leave that field empty to use the interval mode. The
result is a temporary ZIP archive containing JPEG frames.

------------------------------------------------------------------------

## 🔒 Security Principles

-   No persistent storage of generated files
-   Video input and intermediate screenshots are removed in `finally` blocks
-   Token-based download access
-   TTL expiration
-   Rate limiting
-   No caching headers

------------------------------------------------------------------------

## 🧪 Testing

Recommended:

-   pytest for core logic
-   HTTP client tests for web layer
-   Load tests for memory validation

------------------------------------------------------------------------

## 📦 Installation

``` bash
pip install -r requirements.txt
```

For video screenshots, install `ffmpeg` (which also provides `ffprobe`) with
your operating system package manager, for example `brew install ffmpeg` or
`apt install ffmpeg`.

Run CLI:

``` bash
pdf_interleave merge -a A.pdf -b B.pdf -o out.pdf
```

Run Web:

``` bash
uvicorn web.app:app --reload
```

------------------------------------------------------------------------

## 📜 License

This project is licensed under the **MIT License**.

See [LICENSE](LICENSE) for the full text.

------------------------------------------------------------------------

## 👨‍💻 Author

Medhi FOULGOC
