from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter("docintel_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram("docintel_http_request_duration_seconds", "HTTP request latency", ["method", "route"])
SCANS = Counter("docintel_scans_total", "Document scan outcomes", ["outcome"])
CONFIRMATIONS = Counter("docintel_confirmations_total", "Operator confirmations", ["outcome"])
IMAGE_REJECTIONS = Counter("docintel_image_rejections_total", "Rejected intake images", ["code"])
WORKER_REQUESTS = Counter("docintel_ocr_worker_requests_total", "OCR worker calls", ["outcome"])
WORKER_LATENCY = Histogram("docintel_ocr_worker_duration_seconds", "OCR worker call latency")
AUTH_FAILURES = Counter("docintel_auth_failures_total", "Workload identity failures", ["reason"])
SOURCE_LOOKUP = Counter("docintel_source_lookup_urls_total", "QR source lookup URLs seen (never fetched)", ["decision"])
