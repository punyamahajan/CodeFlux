import uvicorn

from codeflux.config import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run("codeflux.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()

