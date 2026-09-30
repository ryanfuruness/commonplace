"""Run the server: python -m commonplace"""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "commonplace.server:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8080")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
