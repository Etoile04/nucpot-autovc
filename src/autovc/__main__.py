import uvicorn


def main():
    uvicorn.run("autovc.main:create_app", host="0.0.0.0", port=8000, factory=True, reload=True)


if __name__ == "__main__":
    main()
