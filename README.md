# 📄 PDF Interleave

A Python-based PDF interleaving tool supporting:

-   CLI usage
-   RAM-only Web version
-   Configurable page ordering
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

------------------------------------------------------------------------

### 🌐 Web Mode (RAM-Only)

-   Max 2 PDFs
-   15 MB per file
-   Output generated fully in memory
-   Temporary download link (default: 5 minutes)
-   No file stored on disk

Run server:

``` bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

------------------------------------------------------------------------

## 🏗 Project Structure

- `core/merge.py`, `core/pagerange.py`, `core/validate.py`: core logic
- `cli/app.py`, `main.py`: CLI entrypoint
- `web/app.py`, `web/store.py`, `web/rate_limit.py`, `web/templates/`: FastAPI web adapter

------------------------------------------------------------------------

## ⚙ Configuration

Environment Variables:

MAX_FILE_MB=15\
DOWNLOAD_TTL_SECONDS=300\
MAX_ACTIVE_JOBS=20\
RATE_LIMIT_MERGE_PER_MIN=10\
RATE_LIMIT_DOWNLOAD_PER_MIN=30\
ONE_SHOT_DOWNLOAD=true

------------------------------------------------------------------------

## 🔒 Security Principles

-   No persistent storage of PDFs
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
